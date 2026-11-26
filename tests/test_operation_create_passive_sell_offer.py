"""Focused offline checks for the CREATE_PASSIVE_SELL_OFFER envelope fixture (issue #556).

The Protocol 28 pack had no envelope fixture selecting OperationType 4. This
fixture uses boundary values (i64::MAX amount, i32::MAX/i32::MIN price) to
confirm that the full payload field order and integer widths are correct end
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
FIXTURE_ID = "p28-xdr-operation-create_passive_sell_offer"
PATH = PACK / "xdr" / "campaign" / f"{FIXTURE_ID}.toml"

INT64_MAX = (1 << 63) - 1
INT32_MAX = (1 << 31) - 1
INT32_MIN = -(1 << 31)

OPERATION_TYPE_CREATE_PASSIVE_SELL_OFFER = 4


class CreatePassiveSellOfferFixtureTests(unittest.TestCase):
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

    def test_operation_tag_is_create_passive_sell_offer(self) -> None:
        ops = self.envelope.v1.tx.operations
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertIsNone(op.source_account)
        self.assertEqual(op.body.op_type, OPERATION_TYPE_CREATE_PASSIVE_SELL_OFFER)
        self.assertEqual(op.body.op_type, 4)

    def test_selling_asset_fields(self) -> None:
        payload = self.envelope.v1.tx.operations[0].body.operation
        self.assertIsInstance(payload, operation_xdr.CreatePassiveSellOfferOp)
        self.assertEqual(payload.selling.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
        self.assertEqual(payload.selling.alpha_num4.asset_code, b"SELL")
        self.assertEqual(payload.selling.alpha_num4.issuer.ed25519, b"\x33" * 32)

    def test_buying_asset_fields(self) -> None:
        payload = self.envelope.v1.tx.operations[0].body.operation
        self.assertEqual(payload.buying.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM12)
        self.assertEqual(payload.buying.alpha_num12.asset_code, b"TWELVE_BYTES")
        self.assertEqual(payload.buying.alpha_num12.issuer.ed25519, b"\x44" * 32)

    def test_amount_and_price_boundary_values(self) -> None:
        payload = self.envelope.v1.tx.operations[0].body.operation
        self.assertEqual(payload.amount, INT64_MAX)
        self.assertEqual(payload.price.n, INT32_MAX)
        self.assertEqual(payload.price.d, INT32_MIN)

    def test_price_bytes_are_at_expected_offset(self) -> None:
        raw = self.raw
        reader = xdr_codec.XdrReader(raw)
        # Skip envelope type, source_account, fee, seq, cond, memo, op count, op source flag
        reader.read_int32()  # envelope type (2)
        reader.read_int32()  # source account key type (0 = Ed25519)
        reader.read_fixed_opaque(32)  # source key bytes
        reader.read_uint32()  # fee
        reader.read_int64()  # seq_num
        reader.read_int32()  # preconditions type (0 = None)
        reader.read_int32()  # memo type (0 = None)
        reader.read_uint32()  # operations count (1)
        reader.read_int32()  # op source account present flag (0 = absent)
        reader.read_int32()  # op type (4)
        xdr_codec._decode_asset(reader)  # selling
        xdr_codec._decode_asset(reader)  # buying
        reader.read_int64()  # amount
        price_offset = reader.pos
        price = price_xdr.decode_price(reader)
        self.assertEqual(price.n, INT32_MAX)
        self.assertEqual(price.d, INT32_MIN)
        self.assertEqual(
            raw[price_offset : price_offset + 8],
            struct.pack(">ii", INT32_MAX, INT32_MIN),
        )

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
