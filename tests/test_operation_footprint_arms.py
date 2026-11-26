"""Focused tests for Protocol 28 TransactionEnvelope embedding footprint operation arms (issue #548).

Covers:
- EXTEND_FOOTPRINT_TTL (OperationType 25): ExtensionPoint V0, maximum uint32 extendTo.
- RESTORE_FOOTPRINT (OperationType 26): ExtensionPoint V0, no additional field.

Asserts:
- Correct OperationType discriminant for each arm.
- ExtensionPoint V0 in each fixture.
- Maximum uint32 extendTo for the extend arm.
- Byte-identical re-encoding for both fixtures.
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

EXTEND_ID = "p28-xdr-operation-extend_footprint_ttl"
RESTORE_ID = "p28-xdr-operation-restore_footprint"

CAMPAIGN_DIR = REPO_ROOT / "protocol-28" / "xdr" / "campaign"
RECORD_DIR = REPO_ROOT / "protocol-28" / "evidence" / "records"


def load(fixture_id: str) -> tuple[dict, bytes]:
    path = CAMPAIGN_DIR / f"{fixture_id}.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class OperationExtendFootprintTTLTests(unittest.TestCase):
    def test_fixture_metadata(self) -> None:
        data, _ = load(EXTEND_ID)
        self.assertEqual(data["id"], EXTEND_ID)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "transaction-envelope")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

    def test_extend_footprint_decodes_and_roundtrips(self) -> None:
        data, raw = load(EXTEND_ID)

        envelope = xdr_codec.decode_transaction_envelope(raw)
        envelope_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(envelope, envelope_generic)

        self.assertEqual(envelope.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)
        self.assertIsNotNone(envelope.v1)
        v1 = envelope.v1
        self.assertEqual(len(v1.tx.operations), 1)

        op = v1.tx.operations[0]
        self.assertIsNone(op.source_account)
        self.assertEqual(
            op.body.op_type,
            operation_xdr.OPERATION_TYPE_EXTEND_FOOTPRINT_TTL,
        )
        self.assertEqual(op.body.op_type, 25)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.ExtendFootprintTTLOp)

        # ExtensionPoint must be V0
        self.assertEqual(payload.extension_type, operation_xdr.EXTENSION_POINT_V0)
        self.assertEqual(payload.extension_type, 0)

        # Maximum uint32 extendTo
        self.assertEqual(payload.extend_to, 4294967295)
        self.assertEqual(payload.extend_to, 2**32 - 1)

        # Byte-identical re-encoding
        reencoded = xdr_codec.encode_transaction_envelope(envelope)
        self.assertEqual(reencoded, raw)
        self.assertEqual(xdr_codec.encode_xdr("TransactionEnvelope", envelope), raw)

    def test_evidence_record_references_fixture(self) -> None:
        _, raw = load(EXTEND_ID)
        record = json.loads(
            (RECORD_DIR / f"{EXTEND_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], EXTEND_ID)
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256((CAMPAIGN_DIR / f"{EXTEND_ID}.toml").read_bytes()).hexdigest())


class OperationRestoreFootprintTests(unittest.TestCase):
    def test_fixture_metadata(self) -> None:
        data, _ = load(RESTORE_ID)
        self.assertEqual(data["id"], RESTORE_ID)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "transaction-envelope")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

    def test_restore_footprint_decodes_and_roundtrips(self) -> None:
        data, raw = load(RESTORE_ID)

        envelope = xdr_codec.decode_transaction_envelope(raw)
        envelope_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(envelope, envelope_generic)

        self.assertEqual(envelope.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)
        self.assertIsNotNone(envelope.v1)
        v1 = envelope.v1
        self.assertEqual(len(v1.tx.operations), 1)

        op = v1.tx.operations[0]
        self.assertIsNone(op.source_account)
        self.assertEqual(
            op.body.op_type,
            operation_xdr.OPERATION_TYPE_RESTORE_FOOTPRINT,
        )
        self.assertEqual(op.body.op_type, 26)

        payload = op.body.operation
        self.assertIsInstance(payload, operation_xdr.RestoreFootprintOp)

        # ExtensionPoint must be V0
        self.assertEqual(payload.extension_type, operation_xdr.EXTENSION_POINT_V0)
        self.assertEqual(payload.extension_type, 0)

        # Restore has no extendTo field
        self.assertFalse(hasattr(payload, "extend_to"))

        # Byte-identical re-encoding
        reencoded = xdr_codec.encode_transaction_envelope(envelope)
        self.assertEqual(reencoded, raw)
        self.assertEqual(xdr_codec.encode_xdr("TransactionEnvelope", envelope), raw)

    def test_evidence_record_references_fixture(self) -> None:
        _, raw = load(RESTORE_ID)
        record = json.loads(
            (RECORD_DIR / f"{RESTORE_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], RESTORE_ID)
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256((CAMPAIGN_DIR / f"{RESTORE_ID}.toml").read_bytes()).hexdigest())

    def test_restore_is_shorter_than_extend(self) -> None:
        _, raw_extend = load(EXTEND_ID)
        _, raw_restore = load(RESTORE_ID)
        # RESTORE_FOOTPRINT has no extendTo (uint32, 4 bytes) compared to EXTEND
        self.assertEqual(len(raw_extend) - len(raw_restore), 4)


if __name__ == "__main__":
    unittest.main()
