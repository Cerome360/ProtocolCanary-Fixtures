"""Focused test for INFLATION and END_SPONSORING_FUTURE_RESERVES void operation arms (issue #543)."""
from __future__ import annotations

import base64
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import operation_xdr, xdr_codec

FIXTURE_PATH = (
    REPO_ROOT
    / "protocol-28"
    / "xdr"
    / "campaign"
    / "p28-xdr-operation-void-arms.toml"
)
RECORD_PATH = (
    REPO_ROOT
    / "protocol-28"
    / "evidence"
    / "records"
    / "p28-xdr-operation-void-arms.json"
)


def load_fixture(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationVoidArmsTests(unittest.TestCase):
    def test_void_arms_roundtrip(self) -> None:
        data, raw = load_fixture(FIXTURE_PATH)
        self.assertEqual(data["id"], "p28-xdr-operation-void-arms")
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "campaign")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

        # Decode with both the specialized and generic decoders
        decoded = xdr_codec.decode_transaction_envelope(raw)
        decoded_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(decoded, decoded_generic)

        # Envelope assertions
        self.assertEqual(decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)
        self.assertIsNotNone(decoded.v1)
        v1 = decoded.v1
        assert v1 is not None

        # Verify operations vector contains exactly two operations
        self.assertEqual(len(v1.tx.operations), 2)

        # Operation 1: INFLATION (OperationType 9, void payload)
        op1 = v1.tx.operations[0]
        self.assertIsNone(op1.source_account)
        self.assertEqual(
            op1.body.op_type, operation_xdr.OPERATION_TYPE_INFLATION
        )
        self.assertEqual(op1.body.op_type, 9)
        self.assertIsInstance(op1.body.operation, operation_xdr.InflationOp)
        self.assertEqual(vars(op1.body.operation), {})

        # Operation 2: END_SPONSORING_FUTURE_RESERVES (OperationType 17, void payload)
        op2 = v1.tx.operations[1]
        self.assertIsNone(op2.source_account)
        self.assertEqual(
            op2.body.op_type,
            operation_xdr.OPERATION_TYPE_END_SPONSORING_FUTURE_RESERVES,
        )
        self.assertEqual(op2.body.op_type, 17)
        self.assertIsInstance(
            op2.body.operation, operation_xdr.EndSponsoringFutureReservesOp
        )
        self.assertEqual(vars(op2.body.operation), {})

        # Byte-identical re-encoding with both encoders
        re_encoded = xdr_codec.encode_transaction_envelope(decoded)
        self.assertEqual(raw, re_encoded)
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_rejected_malformed_inputs(self) -> None:
        _, raw = load_fixture(FIXTURE_PATH)

        # Truncation at end
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_transaction_envelope(raw[:-1])

        # Truncation in operation bodies
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_transaction_envelope(raw[:80])

        # Trailing unconsumed bytes
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_transaction_envelope(raw + b"\x00")

        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_transaction_envelope(raw + b"\x00\x00\x00\x01")

        # Invalid envelope type discriminant (first 4 bytes)
        mutated_env = bytearray(raw)
        mutated_env[0:4] = (99).to_bytes(4, "big")
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_transaction_envelope(bytes(mutated_env))

    def test_evidence_record_exists(self) -> None:
        self.assertTrue(RECORD_PATH.is_file(), f"Missing record: {RECORD_PATH}")


if __name__ == "__main__":
    unittest.main()
