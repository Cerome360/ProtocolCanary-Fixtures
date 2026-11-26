"""Focused offline checks for the MANAGE_BUY_OFFER envelope fixture (issue #557).

The Protocol 28 pack had no envelope fixture selecting OperationType 12. This
fixture uses boundary values (i64::MIN for buyAmount and offerID, Price {-1, 1})
to confirm that the full payload field order and integer widths are correct end
to end. It must decode to the documented synthetic values and re-encode
byte-for-byte.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import operation_xdr, price_xdr, xdr_codec  # noqa: E402

PACK = REPO_ROOT / "protocol-28"
FIXTURE_ID = "p28-xdr-operation-manage_buy_offer"
PATH = PACK / "xdr" / "campaign" / f"{FIXTURE_ID}.toml"

INT64_MIN = -(1 << 63)

OPERATION_TYPE_MANAGE_BUY_OFFER = 12


class ManageBuyOfferFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PATH.read_text(encoding="utf-8")
        cls.data = tomllib.loads(cls.text)
        cls.raw = base64.b64decode(cls.data["value_base64"], validate=True)
        cls.envelope = xdr_codec.decode_xdr("TransactionEnvelope", cls.raw)

    def test_metadata_is_pinned_and_explained(self) -> None:
        self.assertEqual(self.data["id"], FIXTURE_ID)
        self.assertEqual(self.data["type"], "TransactionEnvelope")
        self.assertEqual(self.data["kind"], "roundtrip")
        self.assertIn("/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/", self.data["source_reference"])
        self.assertIn("stellar-xdr 28.0.1", self.text)
        self.assertIn("synthetic", self.text)

    def test_operation_tag_is_manage_buy_offer(self) -> None:
        ops = self.envelope.v1.tx.operations
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertIsNone(op.source_account)
        self.assertEqual(op.body.op_type, OPERATION_TYPE_MANAGE_BUY_OFFER)
        self.assertEqual(op.body.op_type, 12)

    def test_selling_asset_fields(self) -> None:
        payload = self.envelope.v1.tx.operations[0].body.operation
        self.assertIsInstance(payload, operation_xdr.ManageBuyOfferOp)
        self.assertEqual(payload.selling.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM12)
        self.assertEqual(payload.selling.alpha_num12.asset_code, b"TWELVE_BYTES")
        self.assertEqual(payload.selling.alpha_num12.issuer.ed25519, b"\x66" * 32)

    def test_buying_asset_fields(self) -> None:
        payload = self.envelope.v1.tx.operations[0].body.operation
        self.assertEqual(payload.buying.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
        self.assertEqual(payload.buying.alpha_num4.asset_code, b"BUY!")
        self.assertEqual(payload.buying.alpha_num4.issuer.ed25519, b"\x77" * 32)

    def test_buy_amount_price_and_offer_id_boundary_values(self) -> None:
        payload = self.envelope.v1.tx.operations[0].body.operation
        self.assertEqual(payload.buy_amount, INT64_MIN)
        self.assertEqual(payload.price.n, -1)
        self.assertEqual(payload.price.d, 1)
        self.assertEqual(payload.offer_id, INT64_MIN)

    def test_price_bytes_are_at_expected_offset(self) -> None:
        raw = self.raw
        reader = xdr_codec.XdrReader(raw)
        reader.read_int32()  # envelope type (2)
        reader.read_int32()  # source account key type (0 = Ed25519)
        reader.read_fixed_opaque(32)
        reader.read_uint32()  # fee
        reader.read_int64()  # seq_num
        reader.read_int32()  # preconditions type
        reader.read_int32()  # memo type
        reader.read_uint32()  # operations count
        reader.read_int32()  # op source account present flag
        reader.read_int32()  # op type (12)
        xdr_codec._decode_asset(reader)  # selling
        xdr_codec._decode_asset(reader)  # buying
        reader.read_int64()  # buy_amount
        price_offset = reader.pos
        price = price_xdr.decode_price(reader)
        self.assertEqual(price.n, -1)
        self.assertEqual(price.d, 1)
        self.assertEqual(
            raw[price_offset : price_offset + 8],
            struct.pack(">ii", -1, 1),
        )
        self.assertEqual(reader.read_int64(), INT64_MIN)  # offer_id

    def test_round_trips_byte_for_byte(self) -> None:
        self.assertEqual(xdr_codec.encode_xdr("TransactionEnvelope", self.envelope), self.raw)

    def test_evidence_record_binds_the_fixture_bytes(self) -> None:
        record = json.loads(
            (PACK / "evidence" / "records" / f"{FIXTURE_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], FIXTURE_ID)
        self.assertEqual(record["method"], "structural")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256(PATH.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
