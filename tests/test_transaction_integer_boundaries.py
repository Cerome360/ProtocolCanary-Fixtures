"""Focused tests for Protocol 28 V1 transaction integer boundary fixtures (issue #560).

Covers:
- V1 envelope with seqNum = i64::MIN (-9223372036854775808) and fee = 0 (minimum).
- V1 envelope with seqNum = i64::MAX (9223372036854775807) and fee = u32::MAX (4294967295) (maximum).
- Fee-bump envelope with fee = i64::MAX (9223372036854775807).

Asserts:
- Exact decoded field values for each integer endpoint.
- Byte-identical re-encoding for all three fixtures.
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

from tests import xdr_codec  # noqa: E402

V1_MIN_ID = "p28-xdr-transaction-envelope-v1-integer-boundaries-minimum"
V1_MAX_ID = "p28-xdr-transaction-envelope-v1-integer-boundaries-maximum"
FEE_BUMP_ID = "p28-xdr-transaction-envelope-fee-bump-int64-maximum"

TX_ENV_DIR = REPO_ROOT / "protocol-28" / "xdr" / "transaction-envelope"
RECORD_DIR = REPO_ROOT / "protocol-28" / "evidence" / "records"


def load(fixture_id: str) -> tuple[dict, bytes]:
    path = TX_ENV_DIR / f"{fixture_id}.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class TransactionV1IntegerBoundaryTests(unittest.TestCase):
    def _check_v1_metadata(self, fixture_id: str) -> tuple[dict, bytes]:
        data, raw = load(fixture_id)
        self.assertEqual(data["id"], fixture_id)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "transaction-envelope")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")
        return data, raw

    def test_v1_minimum_metadata(self) -> None:
        self._check_v1_metadata(V1_MIN_ID)

    def test_v1_maximum_metadata(self) -> None:
        self._check_v1_metadata(V1_MAX_ID)

    def test_fee_bump_maximum_metadata(self) -> None:
        data, raw = load(FEE_BUMP_ID)
        self.assertEqual(data["id"], FEE_BUMP_ID)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "transaction-envelope")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

    def test_v1_minimum_decoded_fields(self) -> None:
        data, raw = load(V1_MIN_ID)

        envelope = xdr_codec.decode_transaction_envelope(raw)
        self.assertEqual(envelope, xdr_codec.decode_xdr("TransactionEnvelope", raw))
        self.assertEqual(envelope.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        tx = envelope.v1.tx
        self.assertEqual(tx.fee, 0)
        self.assertEqual(tx.seq_num, -9223372036854775808)
        self.assertEqual(tx.seq_num, -(2**63))

        # Byte-identical re-encoding
        self.assertEqual(xdr_codec.encode_transaction_envelope(envelope), raw)
        self.assertEqual(xdr_codec.encode_xdr("TransactionEnvelope", envelope), raw)

    def test_v1_maximum_decoded_fields(self) -> None:
        data, raw = load(V1_MAX_ID)

        envelope = xdr_codec.decode_transaction_envelope(raw)
        self.assertEqual(envelope, xdr_codec.decode_xdr("TransactionEnvelope", raw))
        self.assertEqual(envelope.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        tx = envelope.v1.tx
        self.assertEqual(tx.fee, 4294967295)
        self.assertEqual(tx.fee, 2**32 - 1)
        self.assertEqual(tx.seq_num, 9223372036854775807)
        self.assertEqual(tx.seq_num, 2**63 - 1)

        # Byte-identical re-encoding
        self.assertEqual(xdr_codec.encode_transaction_envelope(envelope), raw)
        self.assertEqual(xdr_codec.encode_xdr("TransactionEnvelope", envelope), raw)

    def test_fee_bump_int64_maximum_decoded_fields(self) -> None:
        data, raw = load(FEE_BUMP_ID)

        envelope = xdr_codec.decode_transaction_envelope(raw)
        self.assertEqual(envelope, xdr_codec.decode_xdr("TransactionEnvelope", raw))
        self.assertEqual(envelope.envelope_type, xdr_codec.ENVELOPE_TYPE_TX_FEE_BUMP)

        fee_bump = envelope.fee_bump
        self.assertEqual(fee_bump.tx.fee, 9223372036854775807)
        self.assertEqual(fee_bump.tx.fee, 2**63 - 1)

        # Byte-identical re-encoding
        self.assertEqual(xdr_codec.encode_transaction_envelope(envelope), raw)
        self.assertEqual(xdr_codec.encode_xdr("TransactionEnvelope", envelope), raw)

    def test_v1_minimum_evidence_record(self) -> None:
        _, raw = load(V1_MIN_ID)
        record = json.loads(
            (RECORD_DIR / f"{V1_MIN_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], V1_MIN_ID)
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256((TX_ENV_DIR / f"{V1_MIN_ID}.toml").read_bytes()).hexdigest())

    def test_v1_maximum_evidence_record(self) -> None:
        _, raw = load(V1_MAX_ID)
        record = json.loads(
            (RECORD_DIR / f"{V1_MAX_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], V1_MAX_ID)
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256((TX_ENV_DIR / f"{V1_MAX_ID}.toml").read_bytes()).hexdigest())

    def test_fee_bump_evidence_record(self) -> None:
        _, raw = load(FEE_BUMP_ID)
        record = json.loads(
            (RECORD_DIR / f"{FEE_BUMP_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], FEE_BUMP_ID)
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256((TX_ENV_DIR / f"{FEE_BUMP_ID}.toml").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
