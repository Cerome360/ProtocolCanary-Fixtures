"""Focused test for strict path-payment arms in Protocol 28 (issue #541)."""
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

RECEIVE_FIXTURE = (
    REPO_ROOT / "protocol-28" / "xdr" / "campaign" / "p28-xdr-operation-path_payment_strict_receive.toml"
)
SEND_FIXTURE = (
    REPO_ROOT / "protocol-28" / "xdr" / "campaign" / "p28-xdr-operation-path_payment_strict_send.toml"
)

RECEIVE_RECORD = (
    REPO_ROOT / "protocol-28" / "evidence" / "records" / "p28-xdr-operation-path_payment_strict_receive.json"
)
SEND_RECORD = (
    REPO_ROOT / "protocol-28" / "evidence" / "records" / "p28-xdr-operation-path_payment_strict_send.json"
)


def load_fixture(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationPathPaymentsTests(unittest.TestCase):
    def test_strict_receive_arm(self) -> None:
        data, raw = load_fixture(RECEIVE_FIXTURE)
        self.assertEqual(data["id"], "p28-xdr-operation-path_payment_strict_receive")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

        # Decode with both decoders
        decoded = xdr_codec.decode_transaction_envelope(raw)
        decoded_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(decoded, decoded_generic)
        self.assertEqual(decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        ops = decoded.v1.tx.operations
        self.assertEqual(len(ops), 1)
        op = ops[0]

        # Assert OperationType 2
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_PATH_PAYMENT_STRICT_RECEIVE)
        self.assertEqual(op.body.op_type, 2)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.PathPaymentStrictReceiveOp)

        # Distinct amount fields: sendMax and destAmount
        self.assertEqual(payload.send_max, 10_000)
        self.assertEqual(payload.dest_amount, 5_000)

        # Destination and assets
        self.assertEqual(payload.send_asset.asset_type, xdr_codec.ASSET_TYPE_NATIVE)
        self.assertEqual(payload.destination.key_type, xdr_codec.KEY_TYPE_ED25519)
        self.assertEqual(payload.destination.ed25519, bytes([0x55]) * 32)
        self.assertEqual(payload.dest_asset.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
        self.assertEqual(payload.dest_asset.alpha_num4.asset_code, b"USD\x00")
        self.assertEqual(payload.dest_asset.alpha_num4.issuer.ed25519, bytes([0x11]) * 32)

        # Five-entry path
        self.assertEqual(len(payload.path), 5)
        for i, asset in enumerate(payload.path, start=1):
            self.assertEqual(asset.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
            self.assertEqual(asset.alpha_num4.asset_code, f"AST{i}".encode("ascii"))
            self.assertEqual(asset.alpha_num4.issuer.ed25519, bytes([0x20 + i]) * 32)

        # Byte-identical re-encoding with both encoders
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_strict_send_arm(self) -> None:
        data, raw = load_fixture(SEND_FIXTURE)
        self.assertEqual(data["id"], "p28-xdr-operation-path_payment_strict_send")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

        # Decode with both decoders
        decoded = xdr_codec.decode_transaction_envelope(raw)
        decoded_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(decoded, decoded_generic)
        self.assertEqual(decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        ops = decoded.v1.tx.operations
        self.assertEqual(len(ops), 1)
        op = ops[0]

        # Assert OperationType 13
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_PATH_PAYMENT_STRICT_SEND)
        self.assertEqual(op.body.op_type, 13)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.PathPaymentStrictSendOp)

        # Distinct amount fields: sendAmount and destMin
        self.assertEqual(payload.send_amount, 8_000)
        self.assertEqual(payload.dest_min, 4_000)

        # Destination and assets
        self.assertEqual(payload.send_asset.asset_type, xdr_codec.ASSET_TYPE_NATIVE)
        self.assertEqual(payload.destination.key_type, xdr_codec.KEY_TYPE_ED25519)
        self.assertEqual(payload.destination.ed25519, bytes([0x55]) * 32)
        self.assertEqual(payload.dest_asset.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
        self.assertEqual(payload.dest_asset.alpha_num4.asset_code, b"EUR\x00")
        self.assertEqual(payload.dest_asset.alpha_num4.issuer.ed25519, bytes([0x12]) * 32)

        # Empty path
        self.assertEqual(len(payload.path), 0)
        self.assertEqual(payload.path, [])

        # Byte-identical re-encoding with both encoders
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_evidence_records_exist(self) -> None:
        self.assertTrue(RECEIVE_RECORD.is_file(), f"Missing record: {RECEIVE_RECORD}")
        self.assertTrue(SEND_RECORD.is_file(), f"Missing record: {SEND_RECORD}")


if __name__ == "__main__":
    unittest.main()
