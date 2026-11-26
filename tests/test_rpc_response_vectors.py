"""Structural conformance tests for the live Testnet RPC response vectors.

Issue #299 / F-042. The JSON files under ``tests/vectors/rpc/`` are captured
JSON-RPC envelopes, not guessed fixtures. Three are the existing public
Testnet captures from 2026-10-18 UTC; the health and fee-stat captures were
collected from the same endpoint on 2026-10-30 UTC. This suite validates the
envelope and the documented response shape offline, then mutates valid
responses to prove that the checks fail closed.

Issue #616 adds a ``getLedgers`` response vector. No captured
``get-ledgers.json`` exists in the corpus, so the vector is built from the
captured ``get-latest-ledger.json`` ledger: the result hash, sequence and
close time, its real ``LedgerHeader`` prefixed with that hash to form the
documented ``LedgerHeaderHistoryEntry`` ``headerXdr``, and its real
``LedgerCloseMeta`` ``metadataXdr``. The transaction summary statistics live
inside that ``metadataXdr`` (the ``LedgerCloseMeta`` V1/V2 arms carry the
transaction-processing results), not as extra top-level fields, so the vector
asserts the union arm and binds the metadata to the same ledger header rather
than inventing counts. The vector is validated against a test-only JSON
Schema mirroring the documented getLedgers response shape with the
repository's jsonschema_lite engine; the repository does not ship
``schemas/rpc-response.schema.json``.

Run with: ``python3 -m unittest tests/test_rpc_response_vectors.py``
"""
from __future__ import annotations

import base64
import binascii
import copy
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VECTOR_DIR = REPO_ROOT / "tests" / "vectors" / "rpc"
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"

_spec = importlib.util.spec_from_file_location("validate_rpc_captures", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
sys.modules["validate_rpc_captures"] = validate
_spec.loader.exec_module(validate)

_schema_spec = importlib.util.spec_from_file_location(
    "jsonschema_lite_rpc_response", REPO_ROOT / "tools" / "validate" / "jsonschema_lite.py"
)
jsonschema_lite = importlib.util.module_from_spec(_schema_spec)
assert _schema_spec is not None and _schema_spec.loader is not None
sys.modules["jsonschema_lite_rpc_response"] = jsonschema_lite
_schema_spec.loader.exec_module(jsonschema_lite)

METHODS = (
    "getNetwork",
    "getLatestLedger",
    "getVersionInfo",
    "getHealth",
    "getFeeStats",
)
METHOD_BY_FILENAME = {
    "get-fee-stats.json": "getFeeStats",
    "get-health.json": "getHealth",
    "get-latest-ledger.json": "getLatestLedger",
    "get-network.json": "getNetwork",
    "get-version-info.json": "getVersionInfo",
}
CAPTURE_FIELDS = ("capturedAt", "endpointHost", "request", "response")
ALLOWED_HOST = "soroban-testnet.stellar.org"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
FEE_STRING_FIELDS = {
    "max",
    "min",
    "mode",
    "p10",
    "p20",
    "p30",
    "p40",
    "p50",
    "p60",
    "p70",
    "p80",
    "p90",
    "p95",
    "p99",
    "transactionCount",
}
FEE_FIELDS = FEE_STRING_FIELDS | {"ledgerCount"}


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_canonical_base64(value: object) -> bool:
    if not _is_nonempty_string(value):
        return False
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return False
    return base64.b64encode(decoded).decode("ascii") == value


def _require_keys(value: object, expected: set[str], label: str, problems: list[str]) -> dict:
    if not isinstance(value, dict):
        problems.append(f"{label} must be an object")
        return {}
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        problems.append(f"{label} is missing required field(s) {missing}")
    if extra:
        problems.append(f"{label} has unexpected field(s) {extra}")
    return value


def _check_xdr_string(value: object, label: str, problems: list[str]) -> None:
    if not _is_canonical_base64(value):
        problems.append(f"{label} must be a non-empty canonical base64 string")


def _check_result(method: str, result: object, problems: list[str]) -> None:
    if method == "getNetwork":
        data = _require_keys(
            result,
            {"friendbotUrl", "passphrase", "protocolVersion"},
            "getNetwork.result",
            problems,
        )
        if not _is_nonempty_string(data.get("friendbotUrl")):
            problems.append("getNetwork.result.friendbotUrl must be a non-empty string")
        if not _is_nonempty_string(data.get("passphrase")):
            problems.append("getNetwork.result.passphrase must be a non-empty string")
        if not _is_int(data.get("protocolVersion")) or data["protocolVersion"] < 1:
            problems.append("getNetwork.result.protocolVersion must be a positive integer")
        return

    if method == "getLatestLedger":
        data = _require_keys(
            result,
            {"id", "protocolVersion", "sequence", "closeTime", "headerXdr", "metadataXdr"},
            "getLatestLedger.result",
            problems,
        )
        if not HEX64_RE.fullmatch(data.get("id", "")):
            problems.append("getLatestLedger.result.id must be 64 lowercase hex characters")
        for key in ("protocolVersion", "sequence"):
            if not _is_int(data.get(key)) or data[key] < 1:
                problems.append(f"getLatestLedger.result.{key} must be a positive integer")
        if not _is_nonempty_string(data.get("closeTime")):
            problems.append("getLatestLedger.result.closeTime must be a non-empty string")
        _check_xdr_string(data.get("headerXdr"), "getLatestLedger.result.headerXdr", problems)
        _check_xdr_string(data.get("metadataXdr"), "getLatestLedger.result.metadataXdr", problems)
        return

    if method == "getVersionInfo":
        data = _require_keys(
            result,
            {"version", "commitHash", "buildTimestamp", "captiveCoreVersion", "protocolVersion"},
            "getVersionInfo.result",
            problems,
        )
        for key in ("version", "commitHash", "buildTimestamp", "captiveCoreVersion"):
            if not _is_nonempty_string(data.get(key)):
                problems.append(f"getVersionInfo.result.{key} must be a non-empty string")
        if not _is_int(data.get("protocolVersion")) or data["protocolVersion"] < 1:
            problems.append("getVersionInfo.result.protocolVersion must be a positive integer")
        return

    if method == "getHealth":
        data = _require_keys(
            result,
            {
                "status",
                "latestLedger",
                "latestLedgerCloseTime",
                "oldestLedger",
                "oldestLedgerCloseTime",
                "ledgerRetentionWindow",
            },
            "getHealth.result",
            problems,
        )
        if not _is_nonempty_string(data.get("status")):
            problems.append("getHealth.result.status must be a non-empty string")
        for key in ("latestLedger", "oldestLedger", "ledgerRetentionWindow"):
            if not _is_int(data.get(key)) or data[key] < 0:
                problems.append(f"getHealth.result.{key} must be a non-negative integer")
        for key in ("latestLedgerCloseTime", "oldestLedgerCloseTime"):
            if not _is_nonempty_string(data.get(key)):
                problems.append(f"getHealth.result.{key} must be a non-empty string")
        return

    if method == "getFeeStats":
        data = _require_keys(
            result,
            {"sorobanInclusionFee", "inclusionFee", "latestLedger"},
            "getFeeStats.result",
            problems,
        )
        for fee_name in ("sorobanInclusionFee", "inclusionFee"):
            fee = _require_keys(data.get(fee_name), FEE_FIELDS, f"getFeeStats.result.{fee_name}", problems)
            for key in FEE_STRING_FIELDS:
                if not _is_nonempty_string(fee.get(key)):
                    problems.append(f"getFeeStats.result.{fee_name}.{key} must be a non-empty string")
            if not _is_int(fee.get("ledgerCount")) or fee["ledgerCount"] < 0:
                problems.append(f"getFeeStats.result.{fee_name}.ledgerCount must be a non-negative integer")
        if not _is_int(data.get("latestLedger")) or data["latestLedger"] < 1:
            problems.append("getFeeStats.result.latestLedger must be a positive integer")


def capture_problems(capture: object, expected_method: str | None = None) -> list[str]:
    """Return structural problems for one captured JSON-RPC response."""
    if not isinstance(capture, dict):
        return ["a capture must be a JSON object"]

    problems: list[str] = []
    if set(capture) != set(CAPTURE_FIELDS):
        problems.append("capture fields must be exactly capturedAt, endpointHost, request, response")
    if "capturedAt" in capture:
        instant_problem = validate._check_instant(capture["capturedAt"])
        if instant_problem:
            problems.append(instant_problem.replace("checkedAt", "capturedAt", 1))
    if capture.get("endpointHost") != ALLOWED_HOST:
        problems.append(f"endpointHost must be {ALLOWED_HOST!r}")

    request = _require_keys(capture.get("request"), {"jsonrpc", "id", "method"}, "request", problems)
    method = request.get("method")
    if request.get("jsonrpc") != "2.0":
        problems.append("request.jsonrpc must be '2.0'")
    if method not in METHODS:
        problems.append(f"request.method must be one of {list(METHODS)}")
    if expected_method is not None and method != expected_method:
        problems.append(f"request.method {method!r} does not match expected {expected_method!r}")

    response = _require_keys(capture.get("response"), {"jsonrpc", "id", "result"}, "response", problems)
    if response.get("jsonrpc") != "2.0":
        problems.append("response.jsonrpc must be '2.0'")
    if "id" in request and response.get("id") != request.get("id"):
        problems.append("response.id must match request.id")
    if "result" in response and method in METHODS:
        _check_result(method, response["result"], problems)
    return problems


def load_captures() -> dict[str, dict]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(VECTOR_DIR.glob("*.json"))
    }


class RpcResponseVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.captures = load_captures()

    def test_corpus_covers_exactly_the_five_supported_methods(self) -> None:
        self.assertEqual(
            sorted(self.captures),
            [
                "get-fee-stats.json",
                "get-health.json",
                "get-latest-ledger.json",
                "get-network.json",
                "get-version-info.json",
            ],
        )
        self.assertEqual(
            {capture["request"]["method"] for capture in self.captures.values()},
            set(METHODS),
        )

    def test_every_live_capture_matches_its_method_schema(self) -> None:
        for filename, capture in self.captures.items():
            expected = METHOD_BY_FILENAME[filename]
            with self.subTest(vector=filename):
                self.assertEqual(capture_problems(capture, expected), [], capture)

    def test_captures_are_public_uncredentialed_testnet_records(self) -> None:
        for filename, capture in self.captures.items():
            with self.subTest(vector=filename):
                self.assertEqual(capture["endpointHost"], ALLOWED_HOST)
                raw = json.dumps(capture, sort_keys=True).lower()
                for forbidden in ("authorization", "bearer", "api_key", "apikey", "secret", "password"):
                    self.assertNotIn(forbidden, raw)
        self.assertEqual(self.captures["get-network.json"]["response"]["result"]["protocolVersion"], 29)

    def test_mutated_missing_field_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.captures["get-health.json"])
        del mutated["response"]["result"]["status"]
        problems = capture_problems(mutated, "getHealth")
        self.assertTrue(any("status" in problem for problem in problems), problems)

    def test_mutated_wrong_type_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.captures["get-fee-stats.json"])
        mutated["response"]["result"]["latestLedger"] = "5469717"
        problems = capture_problems(mutated, "getFeeStats")
        self.assertTrue(any("latestLedger" in problem for problem in problems), problems)

    def test_mutated_method_and_jsonrpc_envelope_are_rejected(self) -> None:
        mutated = copy.deepcopy(self.captures["get-network.json"])
        mutated["request"]["method"] = "getHealth"
        mutated["response"]["jsonrpc"] = "1.0"
        problems = capture_problems(mutated, "getNetwork")
        self.assertTrue(any("does not match" in problem for problem in problems), problems)
        self.assertTrue(any("response.jsonrpc" in problem for problem in problems), problems)


# ---------------------------------------------------------------------------
# getLedgers response vector (issue #616)
# ---------------------------------------------------------------------------

RETENTION_WINDOW = 120_960  # Stellar RPC's stock history retention, in ledgers.
SECONDS_PER_LEDGER = 5
CANONICAL_BASE64_RE = r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"

# The documented getLedgers result shape (its ledger fields are hash, sequence,
# ledgerCloseTime, headerXdr and metadataXdr). Verified against
# https://developers.stellar.org/docs/data/apis/rpc/api-reference/methods/getLedgers.
GET_LEDGERS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "getLedgers response (test-only mirror of the documented shape)",
    "type": "object",
    "required": ["jsonrpc", "id", "result"],
    "additionalProperties": False,
    "properties": {
        "jsonrpc": {"const": "2.0"},
        "id": {"type": ["integer", "string"]},
        "result": {
            "type": "object",
            "required": [
                "ledgers",
                "latestLedger",
                "latestLedgerCloseTime",
                "oldestLedger",
                "oldestLedgerCloseTime",
                "cursor",
            ],
            "additionalProperties": False,
            "properties": {
                "ledgers": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/ledger"},
                },
                "latestLedger": {"type": "integer", "minimum": 1},
                "latestLedgerCloseTime": {"type": "string", "pattern": "^[0-9]+$"},
                "oldestLedger": {"type": "integer", "minimum": 0},
                "oldestLedgerCloseTime": {"type": "string", "pattern": "^[0-9]+$"},
                "cursor": {"type": "string", "minLength": 1},
            },
        },
    },
    "$defs": {
        "hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "xdr": {"type": "string", "minLength": 4, "pattern": CANONICAL_BASE64_RE},
        "ledger": {
            "type": "object",
            "required": ["hash", "sequence", "ledgerCloseTime", "headerXdr", "metadataXdr"],
            "additionalProperties": False,
            "properties": {
                "hash": {"$ref": "#/$defs/hash"},
                "sequence": {"type": "integer", "minimum": 1},
                "ledgerCloseTime": {"type": "string", "pattern": "^[0-9]+$"},
                "headerXdr": {"$ref": "#/$defs/xdr"},
                "metadataXdr": {"$ref": "#/$defs/xdr"},
            },
        },
    },
}


def build_get_ledgers_vector() -> dict:
    """The getLedgers response for the ledger captured by getLatestLedger.

    ``getLatestLedger`` returns a ``LedgerHeader`` while ``getLedgers`` returns
    a ``LedgerHeaderHistoryEntry``, which is that header preceded by the
    ledger's 32-byte hash and followed by its zero-valued extension union.
    Prefixing those bytes reconstructs exactly the entry a getLedgers answer
    for the same ledger carries; nothing in the header itself is synthesized.
    """
    capture = json.loads(
        (VECTOR_DIR / "get-latest-ledger.json").read_text(encoding="utf-8")
    )
    latest = capture["response"]["result"]
    header_xdr = base64.b64encode(
        bytes.fromhex(latest["id"])
        + base64.b64decode(latest["headerXdr"], validate=True)
        + b"\x00\x00\x00\x00"
    ).decode("ascii")
    ledger = {
        "hash": latest["id"],
        "sequence": latest["sequence"],
        "ledgerCloseTime": latest["closeTime"],
        "headerXdr": header_xdr,
        "metadataXdr": latest["metadataXdr"],
    }
    latest_close = int(latest["closeTime"])
    return {
        "jsonrpc": "2.0",
        "id": 8675309,
        "result": {
            "ledgers": [ledger],
            "latestLedger": latest["sequence"],
            "latestLedgerCloseTime": latest["closeTime"],
            "oldestLedger": latest["sequence"] - RETENTION_WINDOW,
            "oldestLedgerCloseTime": str(
                latest_close - RETENTION_WINDOW * SECONDS_PER_LEDGER
            ),
            "cursor": str(latest["sequence"]),
        },
    }


def header_history_entry_problems(header_xdr: str, ledger_hash: str) -> list[str]:
    """Why the header XDR is not this ledger's LedgerHeaderHistoryEntry, or ``[]``."""
    problems: list[str] = []
    if not _is_canonical_base64(header_xdr):
        return ["headerXdr must be non-empty canonical base64"]
    decoded = base64.b64decode(header_xdr, validate=True)
    if len(decoded) < 36:
        return ["headerXdr is too short to hold a hash and a LedgerHeader"]
    if decoded[:32].hex() != ledger_hash:
        problems.append("headerXdr does not start with this ledger's hash")
    ledger_version = int.from_bytes(decoded[32:36], "big")
    if not 1 <= ledger_version <= 100:
        problems.append(f"headerXdr ledgerVersion {ledger_version} is implausible")
    # LedgerHeaderHistoryEntry.ext is an empty (v0) union: four zero bytes.
    if decoded[-4:] != b"\x00\x00\x00\x00":
        problems.append("headerXdr does not end with the empty history-entry extension")
    return problems


def ledger_close_meta_problems(metadata_xdr: str, ledger_hash: str) -> list[str]:
    """Why the metadata XDR is not this ledger's LedgerCloseMeta, or ``[]``."""
    problems: list[str] = []
    if not _is_canonical_base64(metadata_xdr):
        return ["metadataXdr must be non-empty canonical base64"]
    decoded = base64.b64decode(metadata_xdr, validate=True)
    if len(decoded) < 36:
        return ["metadataXdr is too short to hold the LedgerCloseMeta arm and header"]
    arm = int.from_bytes(decoded[:4], "big")
    if arm == 0:
        # LedgerCloseMetaV0 starts with LedgerHeaderHistoryEntry directly, but
        # its txProcessing is the V0 shape this suite does not ingest.
        problems.append("metadataXdr is LedgerCloseMetaV0, not the V1/V2 arm")
        offset = 4
    elif arm in (1, 2):
        # V1/V2 start with LedgerCloseMetaExt, then LedgerHeaderHistoryEntry.
        ext_arm = int.from_bytes(decoded[4:8], "big")
        if ext_arm == 0:
            offset = 8
        elif ext_arm == 1:
            offset = 20  # arm + arm + ExtensionPoint(4) + int64(8)
        else:
            return [f"metadataXdr LedgerCloseMetaExt arm {ext_arm} is unknown"]
    else:
        return [f"metadataXdr LedgerCloseMeta arm {arm} is unknown"]
    header = decoded[offset : offset + 36]
    if len(header) < 36:
        return ["metadataXdr ends before its embedded ledger header"]
    if header[:32].hex() != ledger_hash:
        problems.append("metadataXdr embeds a different ledger header hash")
    ledger_version = int.from_bytes(header[32:36], "big")
    if not 1 <= ledger_version <= 100:
        problems.append(f"metadataXdr embedded ledgerVersion {ledger_version} is implausible")
    return problems


class GetLedgersResponseVectorTests(unittest.TestCase):
    """getLedgers response schema and closing-ledger XDR checks (issue #616)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.vector = build_get_ledgers_vector()
        cls.ledger = cls.vector["result"]["ledgers"][0]
        cls.capture = json.loads(
            (VECTOR_DIR / "get-latest-ledger.json").read_text(encoding="utf-8")
        )

    def test_the_vector_conforms_to_the_rpc_response_schema(self) -> None:
        self.assertEqual(jsonschema_lite.validate(self.vector, GET_LEDGERS_SCHEMA), [])

    def test_the_vector_is_derived_from_the_captured_ledger(self) -> None:
        captured = self.capture["response"]["result"]
        self.assertEqual(self.ledger["hash"], captured["id"])
        self.assertEqual(self.ledger["sequence"], captured["sequence"])
        self.assertEqual(self.ledger["ledgerCloseTime"], captured["closeTime"])
        self.assertEqual(self.ledger["metadataXdr"], captured["metadataXdr"])
        self.assertEqual(self.capture["endpointHost"], ALLOWED_HOST)

    def test_the_envelope_describes_a_consistent_retention_window(self) -> None:
        result = self.vector["result"]
        self.assertEqual(result["latestLedger"], result["ledgers"][-1]["sequence"])
        self.assertEqual(result["latestLedgerCloseTime"], self.ledger["ledgerCloseTime"])
        self.assertEqual(result["oldestLedger"], result["latestLedger"] - RETENTION_WINDOW)
        self.assertLess(int(result["oldestLedgerCloseTime"]), int(result["latestLedgerCloseTime"]))
        self.assertEqual(
            int(result["latestLedgerCloseTime"]) - int(result["oldestLedgerCloseTime"]),
            RETENTION_WINDOW * SECONDS_PER_LEDGER,
        )
        self.assertEqual(result["cursor"], str(result["latestLedger"]))

    def test_the_ledger_sequence_and_timestamp_validate(self) -> None:
        self.assertIsInstance(self.ledger["sequence"], int)
        self.assertGreater(self.ledger["sequence"], 0)
        self.assertRegex(self.ledger["ledgerCloseTime"], r"^[0-9]+$")
        self.assertGreater(int(self.ledger["ledgerCloseTime"]), 0)

    def test_the_header_xdr_is_a_ledger_header_history_entry(self) -> None:
        self.assertEqual(
            header_history_entry_problems(self.ledger["headerXdr"], self.ledger["hash"]),
            [],
        )
        decoded = base64.b64decode(self.ledger["headerXdr"], validate=True)
        self.assertEqual(int.from_bytes(decoded[32:36], "big"), self.capture["response"]["result"]["protocolVersion"])
        self.assertGreater(len(decoded), 36)

    def test_the_metadata_xdr_is_the_ledger_close_meta_for_the_same_ledger(self) -> None:
        self.assertEqual(
            ledger_close_meta_problems(self.ledger["metadataXdr"], self.ledger["hash"]),
            [],
        )

    def test_the_metadata_carries_the_transaction_processing_summary(self) -> None:
        # LedgerCloseMeta V1/V2 is where Stellar RPC puts the per-transaction
        # results (txProcessing) and the closing ledger header; the metadata is
        # therefore strictly larger than the header it repeats. Counting the
        # transactions needs a full XDR codec, which this stdlib-only suite
        # does not have, so the union arm plus the hash binding is the check.
        decoded = base64.b64decode(self.ledger["metadataXdr"], validate=True)
        arm = int.from_bytes(decoded[:4], "big")
        self.assertIn(arm, (1, 2))
        self.assertGreater(len(decoded), len(base64.b64decode(self.ledger["headerXdr"])))
        self.assertEqual(ledger_close_meta_problems(self.ledger["metadataXdr"], self.ledger["hash"]), [])

    def test_header_and_metadata_are_canonical_base64(self) -> None:
        for field in ("headerXdr", "metadataXdr"):
            with self.subTest(field=field):
                self.assertTrue(_is_canonical_base64(self.ledger[field]))
                self.assertEqual(
                    base64.b64encode(base64.b64decode(self.ledger[field], validate=True)).decode(),
                    self.ledger[field],
                )

    def test_a_header_xdr_for_another_ledger_is_rejected(self) -> None:
        decoded = bytearray(base64.b64decode(self.ledger["headerXdr"], validate=True))
        decoded[0] ^= 0xFF
        problems = header_history_entry_problems(
            base64.b64encode(bytes(decoded)).decode(), self.ledger["hash"]
        )
        self.assertTrue(any("does not start with this ledger's hash" in p for p in problems), problems)

    def test_metadata_that_does_not_match_the_ledger_is_rejected(self) -> None:
        other_hash = "00" * 32
        problems = ledger_close_meta_problems(self.ledger["metadataXdr"], other_hash)
        self.assertTrue(any("different ledger header hash" in p for p in problems), problems)

    def test_non_xdr_strings_are_rejected(self) -> None:
        for value in ("", "not base64!", self.ledger["headerXdr"][:-6]):
            with self.subTest(value=value[:20]):
                self.assertTrue(header_history_entry_problems(value, self.ledger["hash"]))
                self.assertTrue(ledger_close_meta_problems(value, self.ledger["hash"]))

    def test_the_schema_rejects_broken_get_ledgers_vectors(self) -> None:
        mutations = (
            (lambda data: data["result"]["ledgers"][0].__setitem__("sequence", str(self.ledger["sequence"])), "$.result.ledgers[0].sequence"),
            (lambda data: data["result"]["ledgers"][0].__setitem__("hash", self.ledger["hash"].upper()), "does not match pattern"),
            (lambda data: data["result"]["ledgers"][0].__setitem__("hash", self.ledger["hash"][:-2]), "does not match pattern"),
            (lambda data: data["result"]["ledgers"][0].__setitem__("ledgerCloseTime", "2026-10-23T15:37:07Z"), "does not match pattern"),
            (lambda data: data["result"]["ledgers"][0].__setitem__("headerXdr", ""), "shorter than 4"),
            (lambda data: data["result"]["ledgers"][0].__setitem__("metadataXdr", "not base64!"), "does not match pattern"),
            (lambda data: data["result"]["ledgers"][0].pop("headerXdr"), "missing required property 'headerXdr'"),
            (lambda data: data["result"]["ledgers"][0].__setitem__("transactionCount", 3), "unexpected property 'transactionCount'"),
            (lambda data: data["result"].__setitem__("cursor", ""), "shorter than 1"),
            (lambda data: data["result"].__setitem__("oldestLedger", -1), "less than 0"),
            (lambda data: data["result"].__setitem__("surprise", True), "unexpected property 'surprise'"),
        )
        for mutate, expected in mutations:
            with self.subTest(expected=expected):
                document = copy.deepcopy(self.vector)
                mutate(document)
                messages = jsonschema_lite.validate(document, GET_LEDGERS_SCHEMA)
                self.assertTrue(any(expected in message for message in messages), messages)

    def test_the_vector_carries_no_credentials(self) -> None:
        raw = json.dumps(self.vector, sort_keys=True).lower()
        for forbidden in ("authorization", "bearer", "api_key", "apikey", "secret", "password"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, raw)


if __name__ == "__main__":
    unittest.main()
