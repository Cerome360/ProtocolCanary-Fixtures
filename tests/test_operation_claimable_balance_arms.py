"""Focused test for claim and clawback claimable-balance OperationBody variants (issue #546)."""
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

CLAIM_FIXTURE = (
    REPO_ROOT / "protocol-28" / "xdr" / "campaign" / "p28-xdr-operation-claim_claimable_balance.toml"
)
CLAWBACK_FIXTURE = (
    REPO_ROOT / "protocol-28" / "xdr" / "campaign" / "p28-xdr-operation-clawback_claimable_balance.toml"
)

CLAIM_RECORD = (
    REPO_ROOT / "protocol-28" / "evidence" / "records" / "p28-xdr-operation-claim_claimable_balance.json"
)
CLAWBACK_RECORD = (
    REPO_ROOT / "protocol-28" / "evidence" / "records" / "p28-xdr-operation-clawback_claimable_balance.json"
)


def load_fixture(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationClaimableBalanceArmsTests(unittest.TestCase):
    def test_claim_claimable_balance_arm(self) -> None:
        data, raw = load_fixture(CLAIM_FIXTURE)
        self.assertEqual(data["id"], "p28-xdr-operation-claim_claimable_balance")
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

        # Assert OperationType 15
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_CLAIM_CLAIMABLE_BALANCE)
        self.assertEqual(op.body.op_type, 15)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.ClaimClaimableBalanceOp)

        # Assert ClaimableBalanceID V0 and exact hash
        balance_id = payload.balance_id
        self.assertEqual(balance_id.id_type, 0)
        self.assertEqual(balance_id.v0, bytes([0xAA]) * 32)

        # Byte-identical re-encoding with both encoders
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_clawback_claimable_balance_arm(self) -> None:
        data, raw = load_fixture(CLAWBACK_FIXTURE)
        self.assertEqual(data["id"], "p28-xdr-operation-clawback_claimable_balance")
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

        # Assert OperationType 20
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_CLAWBACK_CLAIMABLE_BALANCE)
        self.assertEqual(op.body.op_type, 20)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.ClawbackClaimableBalanceOp)

        # Assert ClaimableBalanceID V0 and exact hash
        balance_id = payload.balance_id
        self.assertEqual(balance_id.id_type, 0)
        self.assertEqual(balance_id.v0, bytes([0xBB]) * 32)

        # Byte-identical re-encoding with both encoders
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_evidence_records_exist(self) -> None:
        self.assertTrue(CLAIM_RECORD.is_file(), f"Missing record: {CLAIM_RECORD}")
        self.assertTrue(CLAWBACK_RECORD.is_file(), f"Missing record: {CLAWBACK_RECORD}")


if __name__ == "__main__":
    unittest.main()
