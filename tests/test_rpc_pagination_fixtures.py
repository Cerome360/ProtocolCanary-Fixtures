"""Tests for the RPC pagination boundary vectors (F-038, issue #295).

Run with: python3 -m unittest discover tests

``getLedgers`` and ``getTransactions`` accept a ``pagination.limit`` of up to
200 upstream, but the engine's approved bound (decision D-06, CA-01 section 3
rule 4) is 1..=50. The fixture loader rejects anything above it when the
fixture is loaded, so an out-of-spec page size never reaches an endpoint.

The valid boundaries are four vectors under ``tests/fixtures/rpc/pagination/``
(limit 1 and limit 50 for each method). The invalid ones are built here by
mutating those vectors, because an invalid fixture cannot live in a tree the
validator scans. The engine reports an invalid fixture with exit code 4; this
repository's validator reports it as an error and exits 1, which is what these
tests assert.

The multi-page ``getEvents`` cursor coverage (issue #615) is test-only data
built in this module: ``tests/fixtures/rpc/events/`` holds one request fixture,
not a recorded page sequence, so the pages are simulated here and every cursor
rule is proven both on the valid sequence and on a mutation that breaks it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpc_vector_support as support  # noqa: E402

validate = support.validate
jsonschema_lite = support.load_tool(
    "canary_jsonschema_lite_pagination", "tools/validate/jsonschema_lite.py"
)

METHODS = ("get-ledgers", "get-transactions")
LIMITS = (1, 50)
UPSTREAM_MAX_LIMIT = 200  # Stellar RPC's published ceiling, measured live on 2026-10-23.
D06_MAX_LIMIT = 50


def vector_name(method: str, limit: int) -> str:
    return f"pagination/{method}-limit-{limit}.toml"


class PaginationBoundaryVectorTests(unittest.TestCase):
    def test_the_four_boundary_vectors_validate_cleanly(self) -> None:
        for method in METHODS:
            for limit in LIMITS:
                with self.subTest(method=method, limit=limit):
                    report = support.run_validation({"a.toml": support.read_text(vector_name(method, limit))})
                    self.assertEqual(report.errors, [])

    def test_the_directory_validates_and_the_cli_exits_zero(self) -> None:
        directory = support.RPC_VECTORS / "pagination"
        self.assertEqual(validate.validate_directory(directory).errors, [])
        exit_code, stdout, _stderr = support.run_main([str(directory)])
        self.assertEqual(exit_code, 0)
        self.assertIn("OK: 4 fixture file(s) valid", stdout)

    def test_each_vector_pins_its_method_and_limit(self) -> None:
        for method in METHODS:
            for limit in LIMITS:
                with self.subTest(method=method, limit=limit):
                    data = support.load_toml(vector_name(method, limit))
                    self.assertEqual(data["method"], method)
                    self.assertEqual(data["request"]["pagination"], {"limit": limit})
                    self.assertEqual(data["surface"], "rpc")
                    self.assertEqual(data["id"], f"test-rpc-{method}-limit-{limit}")

    def test_the_vectors_cover_both_ends_of_the_approved_range(self) -> None:
        limits = {
            (data["method"], data["request"]["pagination"]["limit"])
            for data in (support.load_toml(vector_name(m, n)) for m in METHODS for n in LIMITS)
        }
        self.assertEqual(limits, {(m, n) for m in METHODS for n in (1, D06_MAX_LIMIT)})

    def test_the_assertions_describe_a_page_and_its_cursor(self) -> None:
        for method, listing in (("get-ledgers", "ledgers"), ("get-transactions", "transactions")):
            data = support.load_toml(vector_name(method, 50))
            asserted = {(a["kind"], a["field"], a.get("expected_type")) for a in data["assert"]}
            with self.subTest(method=method):
                self.assertEqual(
                    asserted,
                    {
                        ("field-type", listing, "array"),
                        ("field-type", "latestLedger", "number"),
                        ("field-type", "oldestLedger", "number"),
                        ("field-type", "cursor", "string"),
                    },
                )
                for assertion in data["assert"]:
                    self.assertIn(assertion["kind"], validate.RPC_ASSERT_KINDS)


class OutOfBoundLimitTests(unittest.TestCase):
    """Every limit above 50 is an invalid fixture, for both methods."""

    def mutated(self, method: str, literal: str):
        text = support.set_limit(support.read_text(vector_name(method, 50)), literal)
        return support.run_validation({"a.toml": text})

    def test_limit_51_and_200_are_rejected_as_invalid_fixtures(self) -> None:
        for method in METHODS:
            for limit in (D06_MAX_LIMIT + 1, UPSTREAM_MAX_LIMIT):
                with self.subTest(method=method, limit=limit):
                    report = self.mutated(method, str(limit))
                    self.assertFalse(report.ok)
                    self.assertTrue(
                        any(f"limit {limit} is outside 1..=50" in error for error in report.errors),
                        report.errors,
                    )

    def test_the_ceiling_is_exactly_50(self) -> None:
        for method in METHODS:
            with self.subTest(method=method):
                self.assertEqual(self.mutated(method, "50").errors, [])
                self.assertTrue(self.mutated(method, "51").errors)

    def test_the_floor_is_exactly_1(self) -> None:
        for method in METHODS:
            with self.subTest(method=method):
                self.assertEqual(self.mutated(method, "1").errors, [])
                report = self.mutated(method, "0")
                self.assertTrue(any("limit 0 is outside 1..=50" in e for e in report.errors), report.errors)

    def test_negative_and_very_large_limits_are_rejected(self) -> None:
        for literal, shown in (("-1", "-1"), ("-50", "-50"), ("4294967295", "4294967295"), ("9007199254740993", "9007199254740993")):
            with self.subTest(limit=literal):
                report = self.mutated("get-ledgers", literal)
                self.assertTrue(any(f"limit {shown} is outside 1..=50" in e for e in report.errors), report.errors)

    def test_the_upstream_limit_is_not_the_engine_limit(self) -> None:
        # The reconciliation the issue asks for, stated as numbers: upstream
        # allows 200, D-06 approves 50, and the validator follows D-06.
        self.assertGreater(UPSTREAM_MAX_LIMIT, D06_MAX_LIMIT)
        self.assertEqual(validate._RPC_MAX_LIMIT, D06_MAX_LIMIT)
        self.assertTrue(self.mutated("get-ledgers", str(UPSTREAM_MAX_LIMIT)).errors)

    def test_an_out_of_bound_limit_fails_the_command_line_run(self) -> None:
        # CI runs `python3 tools/validate/validate.py`; any error is exit 1.
        text = support.set_limit(support.read_text(vector_name("get-transactions", 50)), "51")
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "a.toml").write_text(text, encoding="utf-8")
            exit_code, _stdout, stderr = support.run_main([scratch])
            self.assertEqual(exit_code, 1)
            self.assertIn("limit 51 is outside 1..=50", stderr)
            self.assertIn("FAILED: 1 error(s)", stderr)
            json_code, json_out, _ = support.run_main([scratch, "--format", "json"])
            document = json.loads(json_out)
            self.assertEqual(json_code, 1)
            self.assertFalse(document["valid"])
            self.assertEqual(document["summary"]["errors"], 1)
            self.assertIn("limit 51 is outside 1..=50", document["errors"][0]["message"])


class NonIntegerLimitTests(unittest.TestCase):
    """A limit that is not an integer cannot be a page size."""

    def mutated(self, literal: str, method: str = "get-ledgers"):
        text = support.set_limit(support.read_text(vector_name(method, 50)), literal)
        return support.run_validation({"a.toml": text})

    def test_floats_strings_booleans_and_containers_are_rejected(self) -> None:
        for literal in ("50.0", "50.5", '"50"', "true", "false", "[50]", "{ n = 50 }"):
            for method in METHODS:
                with self.subTest(limit=literal, method=method):
                    report = self.mutated(literal, method)
                    self.assertTrue(
                        any("pagination: limit must be an integer" in e for e in report.errors),
                        report.errors,
                    )

    def test_an_unknown_pagination_key_is_rejected(self) -> None:
        text = support.replace_once(support.read_text(vector_name("get-ledgers", 1)), "limit = 1\n", "limit = 1\npageSize = 1\n")
        report = support.run_validation({"a.toml": text})
        self.assertTrue(any("unknown key 'pageSize'" in e for e in report.errors), report.errors)

    def test_an_empty_cursor_is_rejected_and_a_real_one_is_accepted_with_the_ceiling(self) -> None:
        base = support.read_text(vector_name("get-transactions", 50))
        ok = support.replace_once(base, "limit = 50\n", 'limit = 50\ncursor = "22974218153062401"\n')
        self.assertEqual(support.run_validation({"a.toml": ok}).errors, [])
        bad = support.replace_once(base, "limit = 50\n", 'limit = 50\ncursor = ""\n')
        self.assertTrue(any("cursor must be a non-empty string" in e for e in support.run_validation({"a.toml": bad}).errors))

    def test_a_start_ledger_outside_the_32_bit_range_is_rejected(self) -> None:
        for literal in ("-1", "4294967296"):
            with self.subTest(startLedger=literal):
                base = support.read_text(vector_name("get-ledgers", 50))
                text = support.replace_once(base, "startLedger = 5340000", f"startLedger = {literal}")
                report = support.run_validation({"a.toml": text})
                self.assertTrue(any("is not a ledger sequence" in e for e in report.errors), report.errors)


class SchemaAndLoaderTests(unittest.TestCase):
    def test_the_paged_methods_are_in_the_schema_vocabulary(self) -> None:
        schema_sync = support.load_tool("canary_schema_sync_rpc_vectors", "tools/validate/schema_sync.py")
        block = schema_sync.surface_block(schema_sync.load_schema(), "rpc")
        assert block is not None
        for method in METHODS:
            self.assertIn(method, block["properties"]["method"]["enum"])
            self.assertIn(method, validate.RPC_METHODS)

    def test_both_methods_take_the_same_three_parameters(self) -> None:
        for method in METHODS:
            self.assertEqual(
                set(validate._RPC_METHOD_PARAMS[method]),
                {"startLedger", "pagination", "xdrFormat"},
            )


# ---------------------------------------------------------------------------
# Multi-page getEvents cursor continuity (issue #615)
# ---------------------------------------------------------------------------

EVENTS_VECTOR = "events/get-events-multitopic.toml"
EVENT_PAGE_SIZE = 2
EVENT_PAGE_COUNT = 3
EVENT_START_LEDGER = 5_347_400
EVENT_LEDGER = 5_349_248
EVENT_CLOSED_AT = "2026-10-23T15:37:07Z"
EVENT_CONTRACT_ID = "CADR3ZIARTBJDBDMNBXCKEVMSAETCPCJK3NPOHUQBOMF5LWPODMQU5RQ"
EVENT_TOPIC = ["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"]
EVENT_VALUE = "AAAAEQAAAAEAAAAE"
# A real getEvents id is a 19-character TOID and a 10-character, zero-padded
# event index, separated by a hyphen (Stellar RPC getEvents reference), e.g.
# 0016010972359577600-0000000001. Fixed widths are what make lexicographic
# order the same as numeric order.
EVENT_ID_RE = re.compile(r"^[0-9]{19}-[0-9]{10}$")
TOID_BASE = EVENT_LEDGER << 32

# ``schemas/rpc-events.schema.json`` is named by issue #615 but is not shipped
# by this repository, so the documented result shape is expressed here as a
# JSON Schema and checked with the repository's own jsonschema_lite engine
# instead of by hand-written predicates. Source:
# https://developers.stellar.org/docs/data/apis/rpc/api-reference/methods/getEvents
BASE64_RE = r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"
RPC_EVENTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "getEvents result page (test-only mirror of the documented shape)",
    "type": "object",
    "required": [
        "events",
        "cursor",
        "latestLedger",
        "oldestLedger",
        "latestLedgerCloseTime",
        "oldestLedgerCloseTime",
    ],
    "additionalProperties": False,
    "properties": {
        "events": {"type": "array", "items": {"$ref": "#/$defs/event"}},
        "cursor": {"type": "string", "minLength": 1, "pattern": EVENT_ID_RE.pattern},
        "latestLedger": {"type": "integer", "minimum": 1},
        "oldestLedger": {"type": "integer", "minimum": 0},
        "latestLedgerCloseTime": {"type": "string", "pattern": "^[0-9]+$"},
        "oldestLedgerCloseTime": {"type": "string", "pattern": "^[0-9]+$"},
    },
    "$defs": {
        "scvalBase64": {"type": "string", "minLength": 4, "pattern": BASE64_RE},
        "txHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "event": {
            "type": "object",
            "required": [
                "type",
                "ledger",
                "ledgerClosedAt",
                "contractId",
                "id",
                "operationIndex",
                "transactionIndex",
                "txHash",
                "topic",
                "value",
            ],
            "additionalProperties": False,
            "properties": {
                "type": {"enum": ["contract", "system"]},
                "ledger": {"type": "integer", "minimum": 1},
                "ledgerClosedAt": {
                    "type": "string",
                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
                },
                "contractId": {"type": "string", "pattern": "^C[A-Z2-7]{55}$"},
                "id": {"type": "string", "pattern": EVENT_ID_RE.pattern},
                "operationIndex": {"type": "integer", "minimum": 0},
                "transactionIndex": {"type": "integer", "minimum": 0},
                "txHash": {"$ref": "#/$defs/txHash"},
                "topic": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/scvalBase64"},
                },
                "value": {"$ref": "#/$defs/scvalBase64"},
            },
        },
    },
}


def event_sort_key(event_id: str) -> tuple[int, int]:
    """The order Stellar RPC returns events in: TOID, then event index."""
    toid, index = event_id.split("-", 1)
    return int(toid), int(index)


def simulated_event_pages() -> list[dict]:
    """Three consecutive ``getEvents`` pages, built only for these tests.

    Test-only data: the identifiers are TOID-shaped but synthetic, so nothing
    here is offered as protocol conformance evidence. What is real is the rule
    the pages follow -- ascending ids, one cursor per page, and each page's
    cursor reused as the next request's ``pagination.cursor``.
    """
    pages = []
    toid = TOID_BASE
    for page_index in range(EVENT_PAGE_COUNT):
        events = []
        for event_index in range(EVENT_PAGE_SIZE):
            event_id = f"{toid:019d}-{event_index:010d}"
            events.append(
                {
                    "type": "contract",
                    "ledger": EVENT_LEDGER,
                    "ledgerClosedAt": EVENT_CLOSED_AT,
                    "contractId": EVENT_CONTRACT_ID,
                    "id": event_id,
                    "operationIndex": 0,
                    "transactionIndex": page_index * EVENT_PAGE_SIZE + event_index + 1,
                    "txHash": hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
                    "topic": list(EVENT_TOPIC),
                    "value": EVENT_VALUE,
                }
            )
            toid += 1 << 12  # the next transaction's TOID
        pages.append(
            {
                "events": events,
                "cursor": events[-1]["id"],
                "latestLedger": EVENT_LEDGER + 99,
                "oldestLedger": 5_228_388,
                "latestLedgerCloseTime": "1792770322",
                "oldestLedgerCloseTime": "1792165527",
            }
        )
    return pages


def simulated_page_requests(pages: list[dict]) -> list[dict]:
    """The request that produced each page: startLedger first, cursors after."""
    requests = [{"startLedger": EVENT_START_LEDGER, "pagination": {"limit": EVENT_PAGE_SIZE}}]
    for page in pages[:-1]:
        requests.append({"pagination": {"cursor": page["cursor"], "limit": EVENT_PAGE_SIZE}})
    return requests


def cursor_problems(pages: list[dict]) -> list[str]:
    """What breaks the cross-page cursor contract, or ``[]`` when it holds."""
    problems: list[str] = []
    seen: set[str] = set()
    previous_cursor_key: tuple[int, int] | None = None
    for number, page in enumerate(pages, start=1):
        cursor = page.get("cursor")
        if not isinstance(cursor, str) or not EVENT_ID_RE.fullmatch(cursor):
            problems.append(
                f"page {number}: cursor {cursor!r} is not a 19-digit TOID and a "
                "10-digit event index"
            )
            continue
        if cursor in seen:
            problems.append(f"page {number}: cursor {cursor!r} repeats an earlier page")
        seen.add(cursor)
        key = event_sort_key(cursor)
        if previous_cursor_key is not None and key <= previous_cursor_key:
            problems.append(
                f"page {number}: cursor {cursor!r} is not after the previous page's cursor"
            )
        events = page.get("events")
        if not isinstance(events, list) or not events:
            problems.append(f"page {number}: a page must carry at least one event")
            previous_cursor_key = key
            continue
        keys = []
        for event in events:
            event_id = event.get("id") if isinstance(event, dict) else None
            if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
                problems.append(f"page {number}: event id {event_id!r} is not TOID-shaped")
                continue
            keys.append(event_sort_key(event_id))
        if keys != sorted(set(keys)):
            problems.append(f"page {number}: event ids are not distinct and ascending")
        if events[-1].get("id") != cursor:
            problems.append(
                f"page {number}: cursor {cursor!r} is not the id of the final event"
            )
        if keys and previous_cursor_key is not None and keys[0] <= previous_cursor_key:
            problems.append(
                f"page {number}: the first event is not after the previous page's cursor"
            )
        previous_cursor_key = key
    return problems


def request_cursor_problems(pages: list[dict], requests: list[dict]) -> list[str]:
    """What breaks the request side of cursor continuity, or ``[]``."""
    problems: list[str] = []
    if len(pages) != len(requests):
        return [f"{len(requests)} request(s) for {len(pages)} page(s)"]
    first = requests[0].get("pagination") or {}
    if "cursor" in first:
        problems.append("page 1: a startLedger page must not also send a cursor")
    if "startLedger" not in requests[0]:
        problems.append("page 1: the first page needs a startLedger")
    for number in range(1, len(pages)):
        request = requests[number]
        previous = pages[number - 1]
        cursor = (request.get("pagination") or {}).get("cursor")
        expected = previous["cursor"]
        if cursor != expected:
            problems.append(
                f"page {number + 1}: request cursor {cursor!r} is not the previous "
                f"page's cursor {expected!r}"
            )
        if cursor != previous["events"][-1]["id"]:
            problems.append(
                f"page {number + 1}: request cursor is not the previous page's final event id"
            )
        page_events = pages[number]["events"]
        if cursor and page_events and event_sort_key(page_events[0]["id"]) <= event_sort_key(cursor):
            problems.append(
                f"page {number + 1}: the first event is not after the cursor that requested it"
            )
    return problems


def page_fixture(page_index: int, request: dict) -> str:
    """The event request fixture rewritten as one page of the sequence."""
    text = support.replace_once(
        support.read_text(EVENTS_VECTOR),
        'id = "test-rpc-events-multitopic"',
        f'id = "test-rpc-events-multitopic-page-{page_index + 1}"',
    )
    if "startLedger" in request:
        return text
    text = support.replace_once(text, f"startLedger = {EVENT_START_LEDGER}\n", "")
    cursor = request["pagination"]["cursor"]
    return support.replace_once(
        text,
        "[request.pagination]\nlimit = 2\n",
        f'[request.pagination]\nlimit = 2\ncursor = "{cursor}"\n',
    )


class EventPaginationCursorTests(unittest.TestCase):
    """Cursor continuity across a multi-page getEvents fixture sequence (#615)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = simulated_event_pages()
        cls.requests = simulated_page_requests(cls.pages)
        cls.event_fixture = support.load_toml(EVENTS_VECTOR)

    def test_the_event_fixture_still_validates_cleanly(self) -> None:
        self.assertEqual(support.run_validation({"a.toml": support.read_text(EVENTS_VECTOR)}).errors, [])
        exit_code, stdout, _ = support.run_main([str(support.RPC_VECTORS / "events")])
        self.assertEqual(exit_code, 0)
        self.assertIn("OK: 1 fixture file(s) valid", stdout)

    def test_every_simulated_page_matches_the_rpc_events_schema(self) -> None:
        for number, page in enumerate(self.pages, start=1):
            with self.subTest(page=number):
                self.assertEqual(jsonschema_lite.validate(page, RPC_EVENTS_SCHEMA), [], page)

    def test_cursors_are_formatted_distinct_and_monotonically_increasing(self) -> None:
        cursors = [page["cursor"] for page in self.pages]
        self.assertEqual(len(cursors), len(set(cursors)))
        self.assertEqual(cursors, sorted(cursors, key=event_sort_key))
        for cursor in cursors:
            with self.subTest(cursor=cursor):
                self.assertRegex(cursor, EVENT_ID_RE)
                self.assertEqual(f"{int(cursor.split('-', 1)[0]):019d}", cursor.split("-", 1)[0])
                self.assertEqual(len(cursor.split("-", 1)[1]), 10)

    def test_the_pages_hold_the_cross_page_cursor_contract(self) -> None:
        self.assertEqual(cursor_problems(self.pages), [])
        self.assertEqual(request_cursor_problems(self.pages, self.requests), [])

    def test_each_cursor_is_the_final_event_id_of_its_page(self) -> None:
        for number, page in enumerate(self.pages, start=1):
            with self.subTest(page=number):
                self.assertEqual(page["cursor"], page["events"][-1]["id"])

    def test_each_next_page_request_reuses_the_previous_cursor(self) -> None:
        self.assertNotIn("cursor", self.requests[0]["pagination"])
        self.assertIn("startLedger", self.requests[0])
        for number in range(1, len(self.requests)):
            with self.subTest(page=number + 1):
                self.assertEqual(
                    self.requests[number]["pagination"]["cursor"],
                    self.pages[number - 1]["cursor"],
                )
                self.assertEqual(
                    self.requests[number]["pagination"]["cursor"],
                    self.pages[number - 1]["events"][-1]["id"],
                )
                self.assertNotIn("startLedger", self.requests[number])

    def test_every_event_id_is_distinct_across_the_whole_sequence(self) -> None:
        ids = [event["id"] for page in self.pages for event in page["events"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids, key=event_sort_key))

    def test_the_simulated_pages_satisfy_the_existing_fixture_assertions(self) -> None:
        for number, page in enumerate(self.pages, start=1):
            with self.subTest(page=number):
                self.assertEqual(
                    support.capture_live.evaluate_asserts(self.event_fixture["assert"], page),
                    [],
                )

    def test_each_page_request_is_a_valid_event_fixture(self) -> None:
        files = {
            f"events/page-{number}.toml": page_fixture(number - 1, request)
            for number, request in enumerate(self.requests, start=1)
        }
        self.assertEqual(support.run_validation(files).errors, [])
        with tempfile.TemporaryDirectory() as scratch:
            for name, text in files.items():
                path = Path(scratch) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            exit_code, stdout, stderr = support.run_main([scratch])
        self.assertEqual(exit_code, 0, stderr)
        self.assertIn(f"OK: {EVENT_PAGE_COUNT} fixture file(s) valid", stdout)

    def test_a_repeated_cursor_is_reported(self) -> None:
        pages = copy.deepcopy(self.pages)
        pages[1]["cursor"] = pages[0]["cursor"]
        pages[1]["events"][-1]["id"] = pages[0]["cursor"]
        problems = cursor_problems(pages)
        self.assertTrue(any("repeats an earlier page" in problem for problem in problems), problems)

    def test_cursors_that_go_backwards_are_reported(self) -> None:
        pages = copy.deepcopy(self.pages)
        pages[0], pages[2] = pages[2], pages[0]
        problems = cursor_problems(pages)
        self.assertTrue(
            any("is not after the previous page's cursor" in problem for problem in problems),
            problems,
        )

    def test_malformed_cursors_are_reported(self) -> None:
        malformed = (
            "cursor-1",
            "001601935184075161-0000000000",  # 18-digit TOID
            "0016019351840751616-1",  # 1-digit event index
            "0016019351840751616_0000000000",
            "0016019351840751616-00000000000",
            " 0016019351840751616-0000000000",
        )
        for value in malformed:
            with self.subTest(cursor=value):
                pages = copy.deepcopy(self.pages)
                pages[0]["cursor"] = value
                problems = cursor_problems(pages)
                self.assertTrue(any("is not a 19-digit TOID" in problem for problem in problems), problems)

    def test_a_cursor_that_is_not_the_final_event_id_is_reported(self) -> None:
        pages = copy.deepcopy(self.pages)
        pages[0]["cursor"] = pages[0]["events"][0]["id"]
        problems = cursor_problems(pages)
        self.assertTrue(
            any("is not the id of the final event" in problem for problem in problems),
            problems,
        )

    def test_a_next_request_cursor_that_does_not_match_is_reported(self) -> None:
        requests = copy.deepcopy(self.requests)
        requests[1]["pagination"]["cursor"] = self.pages[0]["events"][0]["id"]
        problems = request_cursor_problems(self.pages, requests)
        self.assertTrue(any("is not the previous page's cursor" in problem for problem in problems), problems)

    def test_a_missing_next_request_cursor_is_reported(self) -> None:
        requests = copy.deepcopy(self.requests)
        del requests[1]["pagination"]["cursor"]
        self.assertTrue(request_cursor_problems(self.pages, requests))

    def test_a_cursor_on_the_first_page_is_reported(self) -> None:
        requests = copy.deepcopy(self.requests)
        requests[0]["pagination"]["cursor"] = self.pages[0]["cursor"]
        problems = request_cursor_problems(self.pages, requests)
        self.assertTrue(any("must not also send a cursor" in problem for problem in problems), problems)

    def test_a_page_whose_events_do_not_follow_its_cursor_is_reported(self) -> None:
        requests = copy.deepcopy(self.requests)
        requests[2]["pagination"]["cursor"] = self.pages[2]["cursor"]
        problems = request_cursor_problems(self.pages, requests)
        self.assertTrue(
            any("is not after the cursor that requested it" in problem for problem in problems),
            problems,
        )

    def test_the_rpc_events_schema_rejects_broken_pages(self) -> None:
        mutations = (
            (lambda page: page.__setitem__("cursor", 7), "$.cursor"),
            (lambda page: page.__setitem__("cursor", ""), "shorter than 1"),
            (lambda page: page["events"][0].pop("txHash"), "missing required property 'txHash'"),
            (lambda page: page["events"][0].__setitem__("id", "0016010972359577600-1"), "does not match pattern"),
            (lambda page: page["events"][0].__setitem__("txHash", "A" * 64), "does not match pattern"),
            (lambda page: page["events"][0].__setitem__("topic", []), "fewer than 1"),
            (lambda page: page["events"][0].__setitem__("value", "not base64!"), "does not match pattern"),
            (lambda page: page["events"][0].__setitem__("surprise", 1), "unexpected property 'surprise'"),
            (lambda page: page.__setitem__("latestLedgerCloseTime", 1792770322), "$.latestLedgerCloseTime"),
        )
        for mutate, expected in mutations:
            with self.subTest(expected=expected):
                page = copy.deepcopy(self.pages[0])
                mutate(page)
                messages = jsonschema_lite.validate(page, RPC_EVENTS_SCHEMA)
                self.assertTrue(
                    any(expected in message for message in messages),
                    messages,
                )


if __name__ == "__main__":
    unittest.main()
