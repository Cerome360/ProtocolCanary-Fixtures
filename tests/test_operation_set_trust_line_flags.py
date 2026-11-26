"""Focused test for Protocol 28 TransactionEnvelope embedding SET_TRUST_LINE_FLAGS (issue #552).

Asserts:
- Decoded OperationBody::SET_TRUST_LINE_FLAGS arm (OperationType 21).
- Absent Operation.sourceAccount override.
- Synthetic Ed25519 trustor key.
- CreditAlphanum12 asset with code b"TWELVE_BYTES" and synthetic issuer key.
- Exact uint32 clearFlags (0x12345678) and setFlags (0xa5a5a5a5).
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

FIXTURE_ID = "p28-xdr-operation-set_trust_line_flags"
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


class OperationSetTrustLineFlagsTests(unittest.TestCase):
    def test_set_trust_line_flags_envelope_decodes_and_roundtrips(self) -> None:
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
        self.assertEqual(op.body.op_type, operation_xdr.OPERATION_TYPE_SET_TRUST_LINE_FLAGS)
        self.assertEqual(op.body.op_type, 21)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.SetTrustLineFlagsOp)

        # Trustor: synthetic Ed25519 key [0x44]*32
        self.assertEqual(payload.trustor.ed25519, b"\x44" * 32)

        # Asset assertions: CreditAlphanum12, code=TWELVE_BYTES, issuer=[0x55]*32
        asset = payload.asset
        self.assertEqual(asset.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM12)
        self.assertEqual(asset.asset_type, 2)
        self.assertIsNotNone(asset.alpha_num12)
        self.assertEqual(asset.alpha_num12.asset_code, b"TWELVE_BYTES")
        self.assertEqual(asset.alpha_num12.issuer.ed25519, b"\x55" * 32)

        # Flag assertions: exact uint32 values
        self.assertEqual(payload.clear_flags, 0x12345678)
        self.assertEqual(payload.set_flags, 0xA5A5A5A5)

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

        # Baseline carries PaymentOp (op_type 1); this fixture carries SET_TRUST_LINE_FLAGS (21).
        self.assertEqual(base.v1.tx.operations[0].body.op_type, 1)
        self.assertEqual(new.v1.tx.operations[0].body.op_type, 21)

        # SET_TRUST_LINE_FLAGS envelope: 176 bytes vs baseline 200 bytes
        self.assertEqual(len(base_raw), 200)
        self.assertEqual(len(raw), 176)

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
