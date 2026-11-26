"""Focused test for the Protocol 28 MANAGE_SELL_OFFER envelope fixture (issue #555)."""

from __future__ import annotations

import base64
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import operation_xdr, price_xdr, xdr_codec

FIXTURE = (
    REPO_ROOT
    / "protocol-28"
    / "xdr"
    / "campaign"
    / "p28-xdr-operation-manage_sell_offer.toml"
)
RECORD = (
    REPO_ROOT
    / "protocol-28"
    / "evidence"
    / "records"
    / "p28-xdr-operation-manage_sell_offer.json"
)

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1

# The official typed envelope oracle recorded as `sell_boundary` in
# tests/test_operation_codec_offers.py (stellar-xdr 28.0.1).
OFFICIAL_ENVELOPE_BASE64 = (
    "AAAAAgAAAACqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqgAAAGQAAAAAAAAAAQAAAAAAAAAAAAAAAQAAAAAAAAAD"
    "AAAAAAAAAAFCVVkhAAAAABERERERERERERERERERERERERERERERERERERERERERgAAAAAAAAACAAAAAf////3//////"
    "////AAAAAAAAAAA="
)


def load_fixture() -> tuple[dict, bytes]:
    data = tomllib.loads(FIXTURE.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationManageSellOfferTests(unittest.TestCase):
    def test_declared_fixture_metadata(self) -> None:
        data, _ = load_fixture()
        self.assertEqual(data["id"], "p28-xdr-operation-manage_sell_offer")
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

    def test_official_oracle_bytes_are_pinned(self) -> None:
        _, raw = load_fixture()
        self.assertEqual(
            base64.b64encode(raw).decode("ascii"), OFFICIAL_ENVELOPE_BASE64
        )

    def test_manage_sell_offer_arm_and_payload_order(self) -> None:
        _, raw = load_fixture()
        decoded = xdr_codec.decode_transaction_envelope(raw)
        decoded_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(decoded, decoded_generic)
        self.assertEqual(decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        tx = decoded.v1.tx
        self.assertEqual(tx.source_account.key_type, xdr_codec.KEY_TYPE_ED25519)
        self.assertEqual(tx.source_account.ed25519, bytes([0xAA]) * 32)
        self.assertEqual(tx.fee, 100)
        self.assertEqual(tx.seq_num, 1)
        self.assertEqual(tx.cond.precond_type, xdr_codec.PRECOND_NONE)
        self.assertEqual(tx.memo.memo_type, xdr_codec.MEMO_NONE)
        self.assertEqual(tx.ext.ext_type, 0)
        self.assertEqual(decoded.v1.signatures, [])
        self.assertEqual(len(tx.operations), 1)

        op = tx.operations[0]
        self.assertIsNone(op.source_account)
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_MANAGE_SELL_OFFER)
        self.assertEqual(op.body.op_type, 3)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.ManageSellOfferOp)

        # Field order: selling, buying, amount, price, offerID.
        self.assertEqual(payload.selling.asset_type, xdr_codec.ASSET_TYPE_NATIVE)
        self.assertEqual(payload.buying.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
        self.assertEqual(payload.buying.alpha_num4.asset_code, b"BUY!")
        self.assertEqual(
            payload.buying.alpha_num4.issuer.ed25519, bytes([0x11]) * 32
        )
        self.assertEqual(payload.amount, INT64_MIN)
        self.assertEqual(payload.price, price_xdr.Price(INT32_MIN, INT32_MAX))
        self.assertEqual(payload.offer_id, INT64_MAX)

        # Re-encoding the complete decoded envelope is byte-identical.
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_evidence_record_exists(self) -> None:
        self.assertTrue(RECORD.is_file(), f"Missing record: {RECORD}")


if __name__ == "__main__":
    unittest.main()
