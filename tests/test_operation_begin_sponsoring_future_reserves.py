"""Focused test for Protocol 28 TransactionEnvelope embedding BEGIN_SPONSORING_FUTURE_RESERVES (issue #547).

Asserts:
- Decoded OperationBody::BEGIN_SPONSORING_FUTURE_RESERVES arm (OperationType 16).
- Absent Operation.sourceAccount override.
- Decoded Ed25519 AccountID sponsored_id.
- Exact byte-for-byte roundtrip through independent Python TransactionEnvelope codec.
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

FIXTURE_ID = "p28-xdr-operation-begin_sponsoring_future_reserves"
FIXTURE = REPO_ROOT / "protocol-28" / "xdr" / "campaign" / f"{FIXTURE_ID}.toml"
RECORD = REPO_ROOT / "protocol-28" / "evidence" / "records" / f"{FIXTURE_ID}.json"


def load(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationBeginSponsoringFutureReservesTests(unittest.TestCase):
    def test_fixture_metadata(self) -> None:
        data, _ = load(FIXTURE)
        self.assertEqual(data["id"], FIXTURE_ID)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "transaction-envelope")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

    def test_begin_sponsoring_envelope_decodes_and_roundtrips(self) -> None:
        data, raw = load(FIXTURE)

        # Decode through the independent Python TransactionEnvelope codec
        envelope = xdr_codec.decode_transaction_envelope(raw)
        envelope_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(envelope, envelope_generic)

        # Must use the ENVELOPE_TYPE_TX arm
        self.assertEqual(envelope.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)
        self.assertIsNotNone(envelope.v1)
        v1 = envelope.v1
        self.assertEqual(len(v1.tx.operations), 1)

        op = v1.tx.operations[0]
        # No optional source account override
        self.assertIsNone(op.source_account)

        # Discriminant assertions
        self.assertEqual(
            op.body.op_type,
            operation_xdr.OPERATION_TYPE_BEGIN_SPONSORING_FUTURE_RESERVES,
        )
        self.assertEqual(op.body.op_type, 16)

        # Payload assertions
        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.BeginSponsoringFutureReservesOp)

        # sponsored_id is a PublicKey (AccountID) with Ed25519 key type
        sponsored_id = payload.sponsored_id
        self.assertIsInstance(sponsored_id, xdr_codec.PublicKey)
        self.assertEqual(sponsored_id.key_type, xdr_codec.PUBLIC_KEY_TYPE_ED25519)
        self.assertEqual(sponsored_id.key_type, 0)
        self.assertEqual(sponsored_id.ed25519, bytes([0x55]) * 32)

        # Byte-identical re-encoding
        reencoded = xdr_codec.encode_transaction_envelope(envelope)
        self.assertEqual(reencoded, raw)
        generic_reencoded = xdr_codec.encode_xdr("TransactionEnvelope", envelope)
        self.assertEqual(generic_reencoded, raw)

    def test_evidence_record_references_fixture(self) -> None:
        data, raw = load(FIXTURE)
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        self.assertEqual(record["fixtureId"], FIXTURE_ID)
        self.assertEqual(record["outcome"], "matched")
        expected_sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.assertEqual(record["fixtureSha256"], expected_sha)


if __name__ == "__main__":
    unittest.main()
