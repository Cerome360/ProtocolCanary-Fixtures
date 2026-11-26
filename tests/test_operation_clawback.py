"""Focused test for Protocol 28 TransactionEnvelope embedding CLAWBACK (issue #551).

Asserts:
- Decoded OperationBody::CLAWBACK arm (OperationType 19).
- Absent Operation.sourceAccount override.
- CreditAlphanum4 asset with code b"CLAW" and synthetic issuer key.
- Classic Ed25519 MuxedAccount ``from`` field.
- Signed int64 amount of 17.
- Exact byte-for-byte roundtrip through independent Python TransactionEnvelope codec.
- Structural evidence record present and bound to the fixture SHA-256.
"""
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

FIXTURE_ID = "p28-xdr-operation-clawback"
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


class OperationClawbackTests(unittest.TestCase):
    def test_clawback_envelope_decodes_and_roundtrips(self) -> None:
        data, raw = load(FIXTURE)
        self.assertEqual(data["id"], FIXTURE_ID)
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "transaction-envelope")

        decoded = xdr_codec.decode_transaction_envelope(raw)
        self.assertEqual(decoded, xdr_codec.decode_xdr("TransactionEnvelope", raw))
        self.assertEqual(decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        tx = decoded.v1.tx
        self.assertEqual(len(tx.operations), 1)

        op = tx.operations[0]
        # Absent operation sourceAccount override
        self.assertIsNone(op.source_account)
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_CLAWBACK)
        self.assertEqual(op.body.op_type, 19)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.ClawbackOp)

        # Asset assertions: CreditAlphanum4, code=CLAW, issuer=[0x33]*32
        asset = payload.asset
        self.assertEqual(asset.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
        self.assertEqual(asset.asset_type, 1)
        self.assertIsNotNone(asset.alpha_num4)
        self.assertEqual(asset.alpha_num4.asset_code, b"CLAW")
        self.assertEqual(asset.alpha_num4.issuer.ed25519, b"\x33" * 32)

        # from_account assertions: classic Ed25519, key=[0x44]*32
        from_account = payload.from_account
        self.assertIsInstance(from_account, xdr_codec.MuxedAccount)
        self.assertEqual(from_account.key_type, xdr_codec.KEY_TYPE_ED25519)
        self.assertEqual(from_account.key_type, 0)
        self.assertEqual(from_account.ed25519, b"\x44" * 32)
        self.assertIsNone(from_account.muxed)

        # Amount: signed int64, value 17
        self.assertEqual(payload.amount, 17)

        # Independent Python codec re-encodes byte-for-byte
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_only_operation_payload_differs_from_baseline(self) -> None:
        _, raw = load(FIXTURE)
        _, base_raw = load(BASELINE)
        base = xdr_codec.decode_transaction_envelope(base_raw)
        new = xdr_codec.decode_transaction_envelope(raw)

        # Both are ENVELOPE_TYPE_TX; the operation arm is what distinguishes them.
        self.assertEqual(new.envelope_type, base.envelope_type)

        # Baseline carries PaymentOp (op_type 1); this fixture carries CLAWBACK (op_type 19).
        self.assertEqual(base.v1.tx.operations[0].body.op_type, 1)
        self.assertEqual(new.v1.tx.operations[0].body.op_type, 19)

        # Clawback envelope: 168 bytes vs baseline 200 bytes
        self.assertEqual(len(base_raw), 200)
        self.assertEqual(len(raw), 168)

    def test_structural_record_exists_and_binds_fixture(self) -> None:
        self.assertTrue(RECORD.is_file(), f"Missing structural record: {RECORD}")
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
