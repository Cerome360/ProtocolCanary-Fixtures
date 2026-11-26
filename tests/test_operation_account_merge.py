"""Focused tests for Protocol 28 TransactionEnvelope embedding ACCOUNT_MERGE (issue #542).

Asserts:
- Decoded OperationBody::ACCOUNT_MERGE arm (OperationType 8).
- Absent Operation.sourceAccount override.
- Decoded classic Ed25519 MuxedAccount destination.
- Exact byte-for-byte roundtrip through independent Python TransactionEnvelope codec.
- Structural rejections (truncation, trailing bytes, invalid discriminant)
  are rejected by the independent codec.
"""
from __future__ import annotations

import base64
import sys
import tomllib
import unittest
from dataclasses import replace
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
    / "p28-xdr-operation-account_merge.toml"
)


def load_fixture(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationAccountMergeTests(unittest.TestCase):
    def test_fixture_metadata_and_decoded_fields(self) -> None:
        data, raw = load_fixture(FIXTURE_PATH)
        self.assertEqual(data["id"], "p28-xdr-operation-account_merge")
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "transaction-envelope")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

        # Decode through the independent Python TransactionEnvelope codec
        envelope = xdr_codec.decode_transaction_envelope(raw)
        envelope_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(envelope, envelope_generic)

        # Envelope assertions
        self.assertEqual(envelope.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)
        self.assertIsNotNone(envelope.v1)
        v1 = envelope.v1
        self.assertIsNotNone(v1)
        self.assertEqual(len(v1.tx.operations), 1)

        # Operation assertions
        op = v1.tx.operations[0]
        # Absent operation sourceAccount override
        self.assertIsNone(op.source_account)
        self.assertEqual(
            op.body.op_type, operation_xdr.OPERATION_TYPE_ACCOUNT_MERGE
        )
        self.assertEqual(op.body.op_type, 8)

        # AccountMergeOp payload assertions
        merge_op = op.body.operation
        self.assertIsInstance(merge_op, operation_xdr.AccountMergeOp)

        # Destination MuxedAccount assertions (classic Ed25519)
        dest = merge_op.destination
        self.assertIsInstance(dest, xdr_codec.MuxedAccount)
        self.assertEqual(dest.key_type, xdr_codec.KEY_TYPE_ED25519)
        self.assertEqual(dest.key_type, 0)
        self.assertEqual(dest.ed25519, bytes([0x55]) * 32)
        self.assertIsNone(dest.muxed)

        # Exact byte-for-byte re-encoding
        re_encoded = xdr_codec.encode_transaction_envelope(envelope)
        self.assertEqual(raw, re_encoded)
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", envelope))

    def test_rejected_malformed_inputs(self) -> None:
        _, raw = load_fixture(FIXTURE_PATH)

        # Truncation at end
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_transaction_envelope(raw[:-1])

        # Truncation in operation body
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

    def test_encoder_rejects_invalid_destination(self) -> None:
        _, raw = load_fixture(FIXTURE_PATH)
        envelope = xdr_codec.decode_transaction_envelope(raw)
        assert envelope.v1 is not None
        op = envelope.v1.tx.operations[0]

        # Invalid destination key: short bytes
        invalid_op_short = replace(
            op,
            body=replace(
                op.body,
                operation=replace(
                    op.body.operation,
                    destination=xdr_codec.MuxedAccount(
                        key_type=xdr_codec.KEY_TYPE_ED25519,
                        ed25519=b"\x55" * 16,
                    ),
                ),
            ),
        )
        invalid_tx = replace(envelope.v1.tx, operations=[invalid_op_short])
        invalid_envelope = replace(
            envelope,
            v1=replace(envelope.v1, tx=invalid_tx),
        )
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.encode_transaction_envelope(invalid_envelope)

        # Invalid destination key: None ed25519
        invalid_op_none = replace(
            op,
            body=replace(
                op.body,
                operation=replace(
                    op.body.operation,
                    destination=xdr_codec.MuxedAccount(
                        key_type=xdr_codec.KEY_TYPE_ED25519,
                        ed25519=None,
                    ),
                ),
            ),
        )
        invalid_tx_none = replace(envelope.v1.tx, operations=[invalid_op_none])
        invalid_envelope_none = replace(
            envelope,
            v1=replace(envelope.v1, tx=invalid_tx_none),
        )
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.encode_transaction_envelope(invalid_envelope_none)


if __name__ == "__main__":
    unittest.main()
