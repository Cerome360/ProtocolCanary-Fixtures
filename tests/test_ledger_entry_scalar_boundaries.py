"""Focused offline checks for LedgerEntry integer-boundary fixtures (issue #561).

Existing fixtures use ordinary mid-range values for `lastModifiedLedgerSeq`,
TrustLineEntry `balance`, and `limit`. These two fixtures push those scalars
to their structural limits: uint32 maximum for the ledger sequence, and i64
minimum / maximum for the trustline int64 fields. Each must decode to the
documented values and re-encode byte-for-byte.
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
DIRECTORY = PACK / "xdr" / "ledger-entry"

UINT32_MAX = (1 << 32) - 1
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

FIXTURE_U32MAX = "p28-xdr-ledger-entry-last-modified-u32-max"
FIXTURE_I64 = "p28-xdr-ledger-entry-trustline-i64-boundaries"


def _load(fixture_id: str) -> tuple[dict, str, bytes]:
    text = (DIRECTORY / f"{fixture_id}.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return data, text, base64.b64decode(data["value_base64"], validate=True)


class LedgerEntryScalarBoundaryTests(unittest.TestCase):
    def test_metadata_is_pinned_and_explained(self) -> None:
        for fixture_id in (FIXTURE_U32MAX, FIXTURE_I64):
            with self.subTest(fixture_id=fixture_id):
                data, text, _ = _load(fixture_id)
                self.assertEqual(data["id"], fixture_id)
                self.assertEqual(data["type"], "LedgerEntry")
                self.assertEqual(data["kind"], "roundtrip")
                self.assertIn(
                    "/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-ledger-entries.x",
                    data["source_reference"],
                )
                self.assertIn("stellar-xdr 28.0.1", text)
                self.assertIn("synthetic", text)

    def test_last_modified_u32_max_round_trips(self) -> None:
        _, _, raw = _load(FIXTURE_U32MAX)
        entry = xdr_codec.decode_xdr("LedgerEntry", raw)
        self.assertEqual(entry.entry_type, xdr_codec.LEDGER_ENTRY_TYPE_TRUSTLINE)
        self.assertEqual(entry.last_modified_ledger_seq, UINT32_MAX)
        tl = entry.trustline
        self.assertIsNotNone(tl)
        self.assertEqual(tl.account_id.ed25519, b"\x33" * 32)
        self.assertEqual(tl.asset.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM4)
        self.assertEqual(tl.asset.alpha_num4.asset_code, b"USD\x00")
        self.assertEqual(tl.asset.alpha_num4.issuer.ed25519, b"\x44" * 32)
        self.assertEqual(tl.balance, 1_000_000)
        self.assertEqual(tl.limit, INT64_MAX)
        self.assertEqual(xdr_codec.encode_xdr("LedgerEntry", entry), raw)

    def test_trustline_i64_boundaries_round_trips(self) -> None:
        _, _, raw = _load(FIXTURE_I64)
        entry = xdr_codec.decode_xdr("LedgerEntry", raw)
        self.assertEqual(entry.entry_type, xdr_codec.LEDGER_ENTRY_TYPE_TRUSTLINE)
        self.assertEqual(entry.last_modified_ledger_seq, 1_000)
        tl = entry.trustline
        self.assertIsNotNone(tl)
        self.assertEqual(tl.account_id.ed25519, b"\x33" * 32)
        self.assertEqual(tl.asset.asset_type, xdr_codec.ASSET_TYPE_CREDIT_ALPHANUM12)
        self.assertEqual(tl.asset.alpha_num12.asset_code, b"TWELVE_BYTES")
        self.assertEqual(tl.asset.alpha_num12.issuer.ed25519, b"\x55" * 32)
        self.assertEqual(tl.balance, INT64_MIN)
        self.assertEqual(tl.limit, INT64_MAX)
        self.assertEqual(xdr_codec.encode_xdr("LedgerEntry", entry), raw)

    def test_u32_max_first_four_bytes(self) -> None:
        _, _, raw = _load(FIXTURE_U32MAX)
        import struct
        self.assertEqual(struct.unpack(">I", raw[:4])[0], UINT32_MAX)

    def test_evidence_records_bind_the_fixture_bytes(self) -> None:
        for fixture_id in (FIXTURE_U32MAX, FIXTURE_I64):
            with self.subTest(fixture_id=fixture_id):
                record = json.loads(
                    (PACK / "evidence" / "records" / f"{fixture_id}.json").read_text(encoding="utf-8")
                )
                fixture_bytes = (DIRECTORY / f"{fixture_id}.toml").read_bytes()
                self.assertEqual(record["fixtureId"], fixture_id)
                self.assertEqual(record["method"], "structural")
                self.assertEqual(record["fixtureSha256"], hashlib.sha256(fixture_bytes).hexdigest())


if __name__ == "__main__":
    unittest.main()
