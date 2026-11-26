"""Focused offline checks for the muxed transaction-source Payment envelope (issue #558).

Every other Protocol 28 envelope fixture uses a classic Ed25519 account as the
transaction-level source. This one sets `Transaction.sourceAccount` to a
KEY_TYPE_MUXED_ED25519 account; it must decode with the muxed arm present,
stay unsigned, and round-trip byte for byte.
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

PACK = REPO_ROOT / "protocol-28"
FIXTURE_ID = "p28-xdr-transaction-envelope-muxed-transaction-source"
PATH = PACK / "xdr" / "transaction-envelope" / f"{FIXTURE_ID}.toml"
KEY_TYPE_MUXED_ED25519 = 0x100


class MuxedTransactionSourceFixtureTests(unittest.TestCase):
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
        self.assertIn("unsigned", self.text)

    def test_transaction_source_is_a_muxed_account(self) -> None:
        tx = self.envelope.v1.tx
        source = tx.source_account
        self.assertEqual(source.key_type, KEY_TYPE_MUXED_ED25519)
        self.assertEqual(source.muxed.id, 0x0102030405060708)
        self.assertEqual(source.muxed.ed25519, b"\x11" * 32)

    def test_operation_source_stays_absent_and_envelope_unsigned(self) -> None:
        tx = self.envelope.v1.tx
        self.assertEqual(len(tx.operations), 1)
        self.assertIsNone(tx.operations[0].source_account)
        self.assertEqual(len(self.envelope.v1.signatures), 0)

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
