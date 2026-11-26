"""Focused tests for the MANAGE_DATA Operation TransactionEnvelope fixture (issue #544)."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import operation_xdr, xdr_codec  # noqa: E402

FIXTURE_ID = "p28-xdr-operation-manage_data"
FIXTURE = REPO_ROOT / "protocol-28" / "xdr" / "campaign" / f"{FIXTURE_ID}.toml"
BASELINE = (
    REPO_ROOT
    / "protocol-28"
    / "xdr"
    / "transaction-envelope"
    / "p28-xdr-transaction-envelope-v1-roundtrip.toml"
)
RECORD = REPO_ROOT / "protocol-28" / "evidence" / "records" / f"{FIXTURE_ID}.json"


def load(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationManageDataFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = FIXTURE.read_text(encoding="utf-8")
        cls.data, cls.raw = load(FIXTURE)
        cls.decoded = xdr_codec.decode_transaction_envelope(cls.raw)

    def test_metadata_and_provenance(self) -> None:
        self.assertEqual(self.data["id"], FIXTURE_ID)
        self.assertEqual(self.data["type"], "TransactionEnvelope")
        self.assertEqual(self.data["kind"], "roundtrip")
        self.assertEqual(self.data["protocol"], 28)
        self.assertEqual(self.data["surface"], "xdr")
        self.assertEqual(self.data["category"], "transaction-envelope")
        self.assertIn("`stellar-xdr` 28.0.1", self.text)
        self.assertIn("OperationBody::ManageData", self.text)
        self.assertIn("/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/", self.data["source_reference"])

    def test_manage_data_operation_discriminant_and_fields(self) -> None:
        self.assertEqual(self.decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)
        self.assertEqual(self.decoded, xdr_codec.decode_xdr("TransactionEnvelope", self.raw))

        tx = self.decoded.v1.tx
        self.assertEqual(len(tx.operations), 1)
        op = tx.operations[0]
        self.assertIsNone(op.source_account)
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_MANAGE_DATA)
        self.assertEqual(op.body.op_type, 10)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.ManageDataOp)
        self.assertEqual(payload.data_name, "n" * 64)
        self.assertEqual(len(payload.data_name), 64)
        self.assertIsNotNone(payload.data_value)
        self.assertEqual(payload.data_value, bytes(range(64)))
        self.assertEqual(len(payload.data_value), 64)

    def test_roundtrip_byte_for_byte(self) -> None:
        self.assertEqual(xdr_codec.encode_transaction_envelope(self.decoded), self.raw)
        self.assertEqual(xdr_codec.encode_xdr("TransactionEnvelope", self.decoded), self.raw)

    def test_only_operation_body_differs_from_baseline(self) -> None:
        _, base_raw = load(BASELINE)
        base = xdr_codec.decode_transaction_envelope(base_raw)

        self.assertEqual(self.decoded.v1.tx.source_account, base.v1.tx.source_account)
        self.assertEqual(self.decoded.v1.tx.fee, base.v1.tx.fee)
        self.assertEqual(self.decoded.v1.tx.seq_num, base.v1.tx.seq_num)
        self.assertEqual(self.decoded.v1.tx.cond, base.v1.tx.cond)
        self.assertEqual(self.decoded.v1.tx.memo, base.v1.tx.memo)
        self.assertEqual(self.decoded.v1.tx.ext, base.v1.tx.ext)
        self.assertEqual(self.decoded.v1.signatures, base.v1.signatures)

        self.assertIsNone(self.decoded.v1.tx.operations[0].source_account)
        self.assertIsNone(base.v1.tx.operations[0].source_account)

        self.assertEqual(base.v1.tx.operations[0].body.op_type, xdr_codec.OPERATION_TYPE_PAYMENT)
        self.assertEqual(
            self.decoded.v1.tx.operations[0].body.op_type,
            operation_xdr.OPERATION_TYPE_MANAGE_DATA,
        )

    def test_structural_record_exists_and_binds_fixture(self) -> None:
        self.assertTrue(RECORD.is_file(), f"evidence record {RECORD} must exist")
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        self.assertEqual(record["fixtureId"], FIXTURE_ID)
        self.assertEqual(record["method"], "structural")
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(
            record["fixtureSha256"],
            hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
