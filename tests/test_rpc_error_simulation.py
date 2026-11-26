"""Tests for the RPC error-simulation vectors (F-041, issue #298).

Run with: python3 -m unittest discover tests

The vectors in ``tests/fixtures/rpc-errors/error-simulation-vectors.json``
script the failure situations of CA-01 section 5 (HTTP 429, HTTP 5xx, a
timeout, JSON-RPC ``-32601``, other JSON-RPC errors, unrecognized error
formats, a body that is not JSON, a message with neither ``result`` nor
``error``, a ``result`` that is not an object) and record two things for each:

* what the engine does (``engine``): its CA-01 classification, exit code and
  retry behavior, taken from CA-01 section 5 and ``canary-rpc``'s client;
* what this repository's own capture tool, ``tools/evidence/capture_live.py``,
  does with the first reply (``capture_live``).

They are JSON and not TOML fixtures because a TOML fixture cannot do either
job: it cannot choose the endpoint or make it fail (CA-01 section 8), and it
cannot assert that an error is expected (CA-01 section 5, "a fixture never
converts an ``error`` into a pass").

No network: a scripted loopback server replays each vector's responses.

Issue #614 adds the HTTP 429 / JSON-RPC error-object contract: every 429
replay must carry a valid ``Retry-After`` header, every conforming JSON-RPC
error payload must match the JSON-RPC 2.0 error object, and the vector file
itself is validated against an ``rpc-error``-shaped schema (the repository
does not ship ``schemas/rpc-error.schema.json``, so the schema used here is
defined in this module from the JSON-RPC 2.0 and RFC 9110 rules and is run
with the repository's own jsonschema_lite engine).
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpc_vector_support as support  # noqa: E402

capture_live = support.capture_live
jsonschema_lite = support.load_tool(
    "canary_jsonschema_lite_rpc_errors", "tools/validate/jsonschema_lite.py"
)
VECTORS = json.loads(support.ERROR_VECTORS.read_text(encoding="utf-8"))

# The rows of the CA-01 section 5 table that a scripted endpoint can play. The
# other rows are not replayable here: an assertion failure is not an error, an
# oversized body needs 16 MiB, and an invalid [request] is the validator's job.
REPLAYABLE_ROWS = {
    "Transport error, HTTP 5xx, TLS failure",
    "Timeout",
    "HTTP 429",
    "JSON-RPC error object, any code",
    "JSON-RPC code -32601",
    "Body is not JSON, or has neither result nor error, or result is not an object",
}
ENGINE_CLASSES = {"transport", "application", "protocol"}
RETRIED_CLASS = "transport"
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 0.3


class ReplayServer:
    """A loopback endpoint that plays a vector's scripted responses in order.

    The last response repeats once the script is used up, so a vector with one
    entry means "every attempt gets this".
    """

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.requests: list[dict] = []
        self._served = 0
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    def next_response(self) -> dict:
        with self._lock:
            step = self.responses[min(self._served, len(self.responses) - 1)]
            self._served += 1
            return step

    def __enter__(self) -> ReplayServer:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                try:
                    owner.requests.append(json.loads(body.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    owner.requests.append({})
                step = owner.next_response()
                if step.get("hang_ms"):
                    time.sleep(step["hang_ms"] / 1000)
                if "body_json" in step:
                    payload = json.dumps(step["body_json"]).encode("utf-8")
                else:
                    payload = step.get("body_text", "").encode("utf-8")
                self.send_response(step["http_status"])
                self.send_header("Content-Type", "application/json")
                for name, value in step.get("headers", {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                """Keep the test output quiet."""

            def handle_one_request(self) -> None:
                # A client that gave up (the timeout vector) closes the socket
                # before the answer is written; that is its decision, not an error.
                try:
                    super().handle_one_request()
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

        ThreadingHTTPServer.daemon_threads = True
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # A short poll interval keeps shutdown() from waiting half a second per server.
        threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.01), daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> bool:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        return False


def call(server: ReplayServer, request_id: int = 1):
    """One capture_live call against the server, as the tool itself makes it."""
    return capture_live.capture_method(server.url, "getNetwork", request_id, TIMEOUT_SECONDS)


def capture_error(server: ReplayServer) -> str:
    with unittest.TestCase().assertRaises(capture_live.CaptureError) as caught:
        call(server)
    return str(caught.exception)


class VectorFileTests(unittest.TestCase):
    def test_the_file_declares_its_schema_sources_and_retry_policy(self) -> None:
        self.assertEqual(VECTORS["schema"], "rpc-error-simulation-vectors/1")
        self.assertRegex(VECTORS["sources"]["engine_commit"], r"^[0-9a-f]{40}$")
        for url in (VECTORS["sources"]["contract"], VECTORS["sources"]["engine_client"]):
            self.assertIn(VECTORS["sources"]["engine_commit"], url)
        policy = VECTORS["retry_policy"]
        self.assertEqual((policy["max_attempts"], policy["base_delay_ms"], policy["backoff"]), (MAX_ATTEMPTS, 200, "linear"))
        self.assertEqual(policy["retried_classes"], [RETRIED_CLASS])

    def test_every_vector_is_complete_and_ids_are_unique(self) -> None:
        ids = [vector["id"] for vector in VECTORS["vectors"]]
        self.assertEqual(len(ids), len(set(ids)))
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["id"]):
                self.assertRegex(vector["id"], r"^[a-z0-9][a-z0-9-]*$")
                self.assertEqual(set(vector), {"id", "summary", "ca01_row", "responses", "engine", "capture_live"})
                self.assertTrue(vector["responses"])
                for step in vector["responses"]:
                    self.assertIsInstance(step["http_status"], int)
                    self.assertTrue({"body_json", "body_text"} & set(step))

    def test_every_replayable_ca01_row_has_a_vector(self) -> None:
        rows = {vector["ca01_row"] for vector in VECTORS["vectors"]}
        self.assertEqual(rows, REPLAYABLE_ROWS)

    def test_the_engine_expectations_follow_ca01_section_5(self) -> None:
        for vector in VECTORS["vectors"]:
            engine = vector["engine"]
            with self.subTest(vector=vector["id"]):
                self.assertIn(engine["class"], ENGINE_CLASSES)
                self.assertEqual(engine["result_status"] == "error", engine["exit_code"] == 3)
                self.assertIn(engine["result_status"], {"pass", "error"})
                # Only transport-level failures are retried, and then up to the cap.
                self.assertEqual(engine["retried"], engine["class"] == RETRIED_CLASS)
                self.assertEqual(engine["attempts"], MAX_ATTEMPTS if engine["retried"] else 1)

    def test_a_rate_limit_that_clears_is_the_only_pass(self) -> None:
        passes = [v["id"] for v in VECTORS["vectors"] if v["engine"]["result_status"] == "pass"]
        self.assertEqual(passes, ["rate-limited-then-recovers"])
        recovering = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-then-recovers")
        statuses = [step["http_status"] for step in recovering["responses"]]
        self.assertEqual(statuses, [429, 429, 200])
        self.assertEqual(len(statuses), recovering["engine"]["attempts"])

    def test_an_exhausted_failure_never_ends_in_a_pass(self) -> None:
        for vector in VECTORS["vectors"]:
            if vector["id"] != "rate-limited-then-recovers":
                with self.subTest(vector=vector["id"]):
                    self.assertEqual(vector["engine"]["result_status"], "error")
                    self.assertEqual(vector["engine"]["exit_code"], 3)

    def test_a_json_rpc_error_is_never_retried_and_a_transport_error_always_is(self) -> None:
        for vector in VECTORS["vectors"]:
            klass = vector["engine"]["class"]
            with self.subTest(vector=vector["id"]):
                if vector["ca01_row"].startswith("JSON-RPC"):
                    self.assertEqual(klass, "application")
                    self.assertFalse(vector["engine"]["retried"])
                if vector["ca01_row"] in {"HTTP 429", "Timeout", "Transport error, HTTP 5xx, TLS failure"}:
                    self.assertEqual(klass, "transport")
                    self.assertTrue(vector["engine"]["retried"])


class CaptureToolClassificationTests(unittest.TestCase):
    """capture_live separates transport failures from application errors."""

    def test_each_vector_is_classified_as_its_capture_live_block_says(self) -> None:
        for vector in VECTORS["vectors"]:
            expectation = vector["capture_live"]
            with self.subTest(vector=vector["id"]), ReplayServer(vector["responses"]) as server:
                if expectation["outcome"] == "capture-error":
                    message = capture_error(server)
                    for needle in expectation["message_contains"]:
                        self.assertIn(needle, message)
                    for needle in expectation.get("message_excludes", []):
                        self.assertNotIn(needle, message)
                else:
                    result = call(server)
                    problems = capture_live.evaluate_asserts([{"kind": "field-exists", "field": "x"}], result)
                    for needle in expectation["evaluate_problem_contains"]:
                        self.assertTrue(any(needle in problem for problem in problems), problems)
                self.assertGreaterEqual(len(server.requests), 1)

    def test_a_transport_failure_and_an_application_error_never_read_alike(self) -> None:
        transport = [v for v in VECTORS["vectors"] if v["engine"]["class"] == "transport"]
        application = [v for v in VECTORS["vectors"] if v["engine"]["class"] == "application"]
        self.assertTrue(transport and application)
        for vector in transport + application:
            with self.subTest(vector=vector["id"]), ReplayServer(vector["responses"]) as server:
                message = capture_error(server)
                if vector in transport:
                    self.assertNotIn("JSON-RPC error", message)
                else:
                    self.assertIn("JSON-RPC error", message)
                    self.assertNotIn("answered HTTP", message)

    def test_method_not_found_is_reported_with_its_code_and_text(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "method-not-found")
        with ReplayServer(vector["responses"]) as server:
            message = capture_error(server)
        self.assertIn('"code": -32601', message)
        self.assertIn("method not found", message)

    def test_other_json_rpc_codes_keep_their_own_code(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "jsonrpc-error-other-code")
        with ReplayServer(vector["responses"]) as server:
            message = capture_error(server)
        self.assertIn('"code": -32602', message)
        self.assertNotIn("-32601", message)


class RateLimitSequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vector = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-then-recovers")

    def test_the_tool_surfaces_every_429_and_then_the_recovered_answer(self) -> None:
        # capture_live makes one call per method and does not retry; the engine
        # does. Played call by call the script shows both: each 429 is reported
        # as such, and the third attempt returns the real result.
        with ReplayServer(self.vector["responses"]) as server:
            first = capture_error(server)
            second = capture_error(server)
            third = call(server)
            self.assertEqual(len(server.requests), 3)
        self.assertIn("HTTP 429", first)
        self.assertIn("HTTP 429", second)
        self.assertEqual(third["protocolVersion"], 28)
        self.assertEqual(third["passphrase"], "Test SDF Network ; September 2015")

    def test_exhausted_rate_limiting_never_yields_a_result(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-exhausted")
        with ReplayServer(vector["responses"]) as server:
            for _ in range(MAX_ATTEMPTS + 2):
                self.assertIn("HTTP 429", capture_error(server))
            self.assertEqual(len(server.requests), MAX_ATTEMPTS + 2)

    def test_the_requests_are_read_only_json_rpc_posts(self) -> None:
        with ReplayServer(self.vector["responses"]) as server:
            capture_error(server)
        request = server.requests[0]
        self.assertEqual((request["jsonrpc"], request["method"], request["id"]), ("2.0", "getNetwork", 1))
        self.assertNotIn("params", request)


class UnrecognizedErrorFormatTests(unittest.TestCase):
    """An error in a shape nobody documented is still an error, never a pass."""

    def play(self, body: object):
        with ReplayServer([{"http_status": 200, "body_json": body}]) as server:
            return capture_error(server)

    def test_odd_error_values_are_reported_as_json_rpc_errors(self) -> None:
        for label, error in (
            ("string", "boom"),
            ("number", 42),
            ("null", None),
            ("empty object", {}),
            ("list", [{"code": 1}]),
            ("no code", {"message": "boom"}),
            ("code as text", {"code": "-32601", "message": "method not found"}),
        ):
            with self.subTest(error=label):
                message = self.play({"jsonrpc": "2.0", "id": 1, "error": error})
                self.assertIn("JSON-RPC error", message)

    def test_an_error_next_to_a_result_is_still_an_error(self) -> None:
        message = self.play({"jsonrpc": "2.0", "id": 1, "error": {"code": 1, "message": "x"}, "result": {"a": 1}})
        self.assertIn("JSON-RPC error", message)

    def test_shapes_that_are_not_json_rpc_at_all_are_errors(self) -> None:
        for label, body, needle in (
            ("array", [1, 2, 3], "not a JSON-RPC object"),
            ("string", "ok", "not a JSON-RPC object"),
            ("empty object", {}, "no result"),
            ("only a version", {"jsonrpc": "2.0"}, "no result"),
        ):
            with self.subTest(body=label):
                self.assertIn(needle, self.play(body))

    def test_an_answer_for_another_request_is_an_error(self) -> None:
        message = self.play({"jsonrpc": "2.0", "id": 999, "result": {"a": 1}})
        self.assertIn("does not match", message)

    def test_a_non_object_result_cannot_be_asserted_on(self) -> None:
        with ReplayServer([{"http_status": 200, "body_json": {"jsonrpc": "2.0", "id": 1, "result": "ok"}}]) as server:
            result = call(server)
        problems = capture_live.evaluate_asserts([{"kind": "field-exists", "field": "x"}], result)
        self.assertEqual(len(problems), 1)
        self.assertIn("not an object", problems[0])

    def test_other_http_statuses_are_transport_errors_not_results(self) -> None:
        for status in (400, 403, 404, 429, 500, 502, 503):
            with self.subTest(status=status), ReplayServer([{"http_status": status, "body_text": "no"}]) as server:
                message = capture_error(server)
                self.assertIn(f"HTTP {status}", message)
                self.assertNotIn("JSON-RPC error", message)




# JSON-RPC 2.0 section 5.1: the error code is an integer and the message is a
# short, single-sentence string. These are the codes the standard itself
# defines, with the exact message it gives each one.
STANDARD_ERROR_MESSAGES = {
    -32700: "parse error",
    -32600: "invalid request",
    -32601: "method not found",
    -32602: "invalid params",
    -32603: "internal error",
}
RETRY_AFTER_DELTA_RE = re.compile(r"^[0-9]+$")

# ``schemas/rpc-error.schema.json`` is named by issue #614 but is not shipped
# by this repository. This schema describes the vector document the fixture
# actually is, so it is checked with jsonschema_lite rather than mirrored by
# hand-written predicates.
RPC_ERROR_FILE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RPC error-simulation vectors (test-only mirror)",
    "type": "object",
    "required": ["schema", "sources", "retry_policy", "vectors"],
    "additionalProperties": False,
    "properties": {
        "schema": {"const": "rpc-error-simulation-vectors/1"},
        "description": {"type": "string", "minLength": 1},
        "sources": {
            "type": "object",
            "required": ["contract", "engine_client", "engine_commit"],
            "additionalProperties": False,
            "properties": {
                "contract": {"$ref": "#/$defs/httpsUrl"},
                "engine_client": {"$ref": "#/$defs/httpsUrl"},
                "engine_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            },
        },
        "retry_policy": {
            "type": "object",
            "required": ["max_attempts", "base_delay_ms", "backoff", "retried_classes"],
            "additionalProperties": False,
            "properties": {
                "max_attempts": {"type": "integer", "minimum": 1},
                "base_delay_ms": {"type": "integer", "minimum": 0},
                "backoff": {"enum": ["linear", "exponential"]},
                "retried_classes": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"enum": ["transport", "application", "protocol"]},
                },
                "note": {"type": "string", "minLength": 1},
            },
        },
        "vectors": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/vector"}},
    },
    "$defs": {
        "httpsUrl": {"type": "string", "pattern": "^https://[^\\s]+$"},
        "headers": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "Retry-After": {"type": "string", "minLength": 1},
            },
        },
        "response": {
            "type": "object",
            "required": ["http_status"],
            "additionalProperties": False,
            "properties": {
                "http_status": {"type": "integer", "minimum": 100, "maximum": 599},
                "headers": {"$ref": "#/$defs/headers"},
                "body_text": {"type": "string"},
                "body_json": {},
                "hang_ms": {"type": "integer", "minimum": 0},
            },
        },
        "engine": {
            "type": "object",
            "required": ["class", "result_status", "exit_code", "attempts", "retried"],
            "additionalProperties": False,
            "properties": {
                "class": {"enum": ["transport", "application", "protocol"]},
                "result_status": {"enum": ["pass", "error"]},
                "exit_code": {"type": "integer", "minimum": 0},
                "attempts": {"type": "integer", "minimum": 1},
                "retried": {"type": "boolean"},
                "message_contains": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
        },
        "capture": {
            "type": "object",
            "required": ["outcome"],
            "additionalProperties": False,
            "properties": {
                "outcome": {"enum": ["capture-error", "returned"]},
                "message_contains": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "message_excludes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "evaluate_problem_contains": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
        },
        "vector": {
            "type": "object",
            "required": ["id", "summary", "ca01_row", "responses", "engine", "capture_live"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
                "summary": {"type": "string", "minLength": 1},
                "ca01_row": {
                    "enum": [
                        "Transport error, HTTP 5xx, TLS failure",
                        "Timeout",
                        "HTTP 429",
                        "JSON-RPC error object, any code",
                        "JSON-RPC code -32601",
                        "Body is not JSON, or has neither result nor error, or result is not an object",
                    ]
                },
                "responses": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/response"},
                },
                "engine": {"$ref": "#/$defs/engine"},
                "capture_live": {"$ref": "#/$defs/capture"},
            },
        },
    },
}

# The JSON-RPC 2.0 error envelope (section 5): an error reply carries the
# request id, the version string, and an error object whose code is an
# integer and whose message is a string.
JSON_RPC_ERROR_SCHEMA = {
    "type": "object",
    "required": ["jsonrpc", "id", "error"],
    "additionalProperties": False,
    "properties": {
        "jsonrpc": {"const": "2.0"},
        "id": {"type": ["integer", "string", "null"]},
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "additionalProperties": False,
            "properties": {
                "code": {"type": "integer"},
                "message": {"type": "string", "minLength": 1},
                "data": {},
            },
        },
    },
}

# RFC 9110 section 10.2.3: a 429 response tells the client when to retry
# through Retry-After, either as delta-seconds or as an HTTP-date.
RATE_LIMIT_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["http_status", "headers"],
    "additionalProperties": True,
    "properties": {
        "http_status": {"const": 429},
        "headers": {
            "type": "object",
            "required": ["Retry-After"],
            "additionalProperties": False,
            "properties": {"Retry-After": {"type": "string", "minLength": 1}},
        },
    },
}


def retry_after_problems(value: object) -> list[str]:
    """Why ``value`` is not a valid Retry-After, or ``[]``."""
    if not isinstance(value, str) or not value:
        return [f"Retry-After {value!r} is not a non-empty string"]
    if RETRY_AFTER_DELTA_RE.fullmatch(value):
        return []
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return [f"Retry-After {value!r} is neither delta-seconds nor an HTTP-date"]
    if parsed is None:
        return [f"Retry-After {value!r} is neither delta-seconds nor an HTTP-date"]
    return []


def response_steps(body_key: str):
    """Every (vector, step) whose scripted response carries ``body_key``."""
    return [
        (vector, step)
        for vector in VECTORS["vectors"]
        for step in vector["responses"]
        if body_key in step
    ]


def post_raw(server: ReplayServer) -> tuple[int, str | None, bytes]:
    """One raw JSON-RPC POST, keeping the HTTP status, Retry-After and body."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getNetwork"}).encode("utf-8")
    request = urllib.request.Request(
        server.url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, response.headers.get("Retry-After"), response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.headers.get("Retry-After"), error.read()


class RateLimitAndJsonRpcErrorSchemaTests(unittest.TestCase):
    """The 429 and JSON-RPC error-object contract (issue #614)."""

    def test_the_vector_file_conforms_to_the_rpc_error_schema(self) -> None:
        self.assertEqual(jsonschema_lite.validate(VECTORS, RPC_ERROR_FILE_SCHEMA), [])

    def test_the_file_schema_rejects_broken_documents(self) -> None:
        mutations = (
            (lambda data: data.__setitem__("schema", "rpc-error-simulation-vectors/2"), "$.schema"),
            (lambda data: data["sources"].__setitem__("engine_commit", "HEAD"), "does not match pattern"),
            (lambda data: data["sources"].pop("engine_commit"), "missing required property 'engine_commit'"),
            (lambda data: data["retry_policy"].__setitem__("max_attempts", 0), "less than 1"),
            (lambda data: data["retry_policy"].__setitem__("backoff", "random"), "is not one of"),
            (lambda data: data["retry_policy"].__setitem__("retried_classes", []), "fewer than 1"),
            (lambda data: data["vectors"][0].__setitem__("surprise", True), "unexpected property 'surprise'"),
            (lambda data: data["vectors"][0]["responses"][0].pop("http_status"), "missing required property 'http_status'"),
            (lambda data: data["vectors"][0]["responses"][0].__setitem__("http_status", "429"), "expected integer"),
            (lambda data: data["vectors"][0]["responses"][0]["headers"].__setitem__("Retry-After", 1), "expected string"),
        )
        for mutate, expected in mutations:
            with self.subTest(expected=expected):
                document = json.loads(json.dumps(VECTORS))
                mutate(document)
                messages = jsonschema_lite.validate(document, RPC_ERROR_FILE_SCHEMA)
                self.assertTrue(
                    any(expected in message for message in messages),
                    messages,
                )

    def test_every_rate_limited_response_conforms_and_carries_a_valid_retry_after(self) -> None:
        rate_limited = [v for v in VECTORS["vectors"] if v["ca01_row"] == "HTTP 429"]
        self.assertEqual(len(rate_limited), 2)
        for vector in rate_limited:
            for index, step in enumerate(vector["responses"], start=1):
                if step["http_status"] != 429:
                    continue
                with self.subTest(vector=vector["id"], response=index):
                    self.assertEqual(
                        jsonschema_lite.validate(step, RATE_LIMIT_RESPONSE_SCHEMA), [], step
                    )
                    self.assertEqual(
                        retry_after_problems(step["headers"]["Retry-After"]), [], step
                    )

    def test_a_429_without_a_retry_after_is_rejected(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-exhausted")
        step = json.loads(json.dumps(vector["responses"][0]))
        step.pop("headers")
        self.assertTrue(jsonschema_lite.validate(step, RATE_LIMIT_RESPONSE_SCHEMA))
        step["headers"] = {}
        messages = jsonschema_lite.validate(step, RATE_LIMIT_RESPONSE_SCHEMA)
        self.assertTrue(any("Retry-After" in message for message in messages), messages)

    def test_retry_after_accepts_delta_seconds_and_http_dates_only(self) -> None:
        for value in ("0", "1", "120", "Wed, 21 Oct 2015 07:28:00 GMT"):
            with self.subTest(value=value):
                self.assertEqual(retry_after_problems(value), [])
        for value in ("", "-1", "1.5", "soon", 1, None, "Mon, 32 Oct 2015 07:28:00 GMT"):
            with self.subTest(value=value):
                self.assertTrue(retry_after_problems(value))

    def test_a_rate_limited_engine_run_is_a_retried_transport_failure(self) -> None:
        for vector in (v for v in VECTORS["vectors"] if v["ca01_row"] == "HTTP 429"):
            with self.subTest(vector=vector["id"]):
                self.assertEqual(vector["engine"]["class"], "transport")
                self.assertTrue(vector["engine"]["retried"])
                self.assertIn("HTTP 429", vector["capture_live"]["message_contains"])
                self.assertIn("JSON-RPC error", vector["capture_live"]["message_excludes"])

    def test_every_conforming_json_rpc_error_payload_matches_the_specification(self) -> None:
        checked = 0
        for vector, step in response_steps("body_json"):
            error = step["body_json"].get("error") if isinstance(step["body_json"], dict) else None
            if not isinstance(error, dict) or not isinstance(error.get("code"), int) or not isinstance(error.get("message"), str):
                continue
            checked += 1
            with self.subTest(vector=vector["id"]):
                self.assertEqual(
                    jsonschema_lite.validate(step["body_json"], JSON_RPC_ERROR_SCHEMA),
                    [],
                    step["body_json"],
                )
                self.assertEqual(step["body_json"]["id"], 1)
                self.assertEqual(step["body_json"]["jsonrpc"], "2.0")
                self.assertTrue(step["body_json"]["error"]["message"])
        self.assertGreaterEqual(checked, 2)

    def test_the_schema_rejects_error_objects_that_break_the_json_rpc_rules(self) -> None:
        broken = (
            ("missing code", {"jsonrpc": "2.0", "id": 1, "error": {"message": "boom"}}),
            ("code as text", {"jsonrpc": "2.0", "id": 1, "error": {"code": "-32601", "message": "method not found"}}),
            ("empty message", {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": ""}}),
            ("error as text", {"jsonrpc": "2.0", "id": 1, "error": "boom"}),
            ("error as null", {"jsonrpc": "2.0", "id": 1, "error": None}),
            ("error as list", {"jsonrpc": "2.0", "id": 1, "error": [{"code": 1}]}),
            ("wrong version", {"jsonrpc": "1.0", "id": 1, "error": {"code": -32601, "message": "method not found"}}),
            ("unexpected member", {"jsonrpc": "2.0", "id": 1, "error": {"code": 1, "message": "x", "retry": True}}),
        )
        for label, payload in broken:
            with self.subTest(case=label):
                self.assertTrue(
                    jsonschema_lite.validate(payload, JSON_RPC_ERROR_SCHEMA),
                    payload,
                )

    def test_standard_codes_use_the_standard_messages(self) -> None:
        by_code = {
            step["body_json"]["error"]["code"]: step["body_json"]["error"]["message"]
            for _vector, step in response_steps("body_json")
            if isinstance(step["body_json"], dict)
            and isinstance(step["body_json"].get("error"), dict)
            and isinstance(step["body_json"]["error"].get("code"), int)
        }
        self.assertEqual(by_code[-32601], "method not found")
        self.assertEqual(by_code[-32602], "invalid params")
        for code, message in by_code.items():
            with self.subTest(code=code):
                self.assertEqual(message.lower(), STANDARD_ERROR_MESSAGES[code])
                self.assertEqual(message, message.strip())
                self.assertNotIn("\n", message)

    def test_a_json_rpc_error_is_never_retried(self) -> None:
        for vector in (v for v in VECTORS["vectors"] if v["ca01_row"].startswith("JSON-RPC")):
            with self.subTest(vector=vector["id"]):
                self.assertEqual(vector["engine"]["class"], "application")
                self.assertFalse(vector["engine"]["retried"])
                self.assertEqual(vector["engine"]["attempts"], 1)

    def test_the_wire_429_carries_retry_after_and_no_json_rpc_error(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-exhausted")
        with ReplayServer(vector["responses"]) as server:
            status, retry_after, body = post_raw(server)
        self.assertEqual(status, 429)
        self.assertEqual(retry_after, "1")
        self.assertEqual(retry_after_problems(retry_after), [])
        self.assertEqual(body, b"Too Many Requests")
        self.assertNotIn(b"JSON-RPC error", body)

    def test_the_wire_json_rpc_error_keeps_its_code_and_message(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "method-not-found")
        with ReplayServer(vector["responses"]) as server:
            status, retry_after, body = post_raw(server)
        self.assertEqual(status, 200)
        self.assertIsNone(retry_after)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(jsonschema_lite.validate(payload, JSON_RPC_ERROR_SCHEMA), [])
        self.assertEqual(payload["error"]["code"], -32601)
        self.assertEqual(payload["error"]["message"], "method not found")
        self.assertEqual(payload["id"], 1)


if __name__ == "__main__":
    unittest.main()
