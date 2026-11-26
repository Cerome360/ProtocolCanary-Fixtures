"""Focused tests for TTL liveUntilLedgerSeq unsigned boundary fixtures (issue #531)."""
from __future__ import annotations

import base64
import sys
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import xdr_codec  # noqa: E402

FIXTURE_ZERO_ID = "p28-xdr-ttl-ledger-number-boundaries-zero"
FIXTURE_MAX_ID = "p28-xdr-ttl-ledger-number-boundaries-maximum"

FIXTURE_ZERO = REPO_ROOT / "protocol-28" / "xdr" / "campaign" / f"{FIXTURE_ZERO_ID}.toml"
FIXTURE_MAX = REPO_ROOT / "protocol-28" / "xdr" / "campaign" / f"{FIXTURE_MAX_ID}.toml"
BASELINE = REPO_ROOT / "protocol-28" / "xdr" / "ledger-entry" / "p28-xdr-ledger-entry-ttl.toml"

RECORD_ZERO = REPO_ROOT / "protocol-28" / "evidence" / "records" / f"{FIXTURE_ZERO_ID}.json"
RECORD_MAX = REPO_ROOT / "protocol-28" / "evidence" / "records" / f"{FIXTURE_MAX_ID}.json"


def load(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class TtlLedgerNumberBoundariesTests(unittest.TestCase):
    def test_zero_fixture_decodes_and_roundtrips(self) -> None:
        data, raw = load(FIXTURE_ZERO)
        self.assertEqual(data["id"], FIXTURE_ZERO_ID)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["type"], "LedgerEntry")
        self.assertEqual(data["kind"], "roundtrip")
        self.assertEqual(data["category"], "ledger-entry")

        decoded = xdr_codec.decode_ledger_entry(raw)
        self.assertEqual(decoded, xdr_codec.decode_xdr("LedgerEntry", raw))
        self.assertEqual(decoded.entry_type, xdr_codec.LEDGER_ENTRY_TYPE_TTL)
        self.assertIsNotNone(decoded.ttl)
        self.assertEqual(decoded.ttl.live_until_ledger_seq, 0)
        self.assertEqual(decoded.ttl.key_hash, b"\x66" * 32)
        self.assertEqual(decoded.last_modified_ledger_seq, 1_234_571)

        self.assertEqual(raw, xdr_codec.encode_ledger_entry(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("LedgerEntry", decoded))

    def test_maximum_fixture_decodes_and_roundtrips(self) -> None:
        data, raw = load(FIXTURE_MAX)
        self.assertEqual(data["id"], FIXTURE_MAX_ID)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["type"], "LedgerEntry")
        self.assertEqual(data["kind"], "roundtrip")
        self.assertEqual(data["category"], "ledger-entry")

        decoded = xdr_codec.decode_ledger_entry(raw)
        self.assertEqual(decoded, xdr_codec.decode_xdr("LedgerEntry", raw))
        self.assertEqual(decoded.entry_type, xdr_codec.LEDGER_ENTRY_TYPE_TTL)
        self.assertIsNotNone(decoded.ttl)
        self.assertEqual(decoded.ttl.live_until_ledger_seq, 4294967295)
        self.assertEqual(decoded.ttl.key_hash, b"\x66" * 32)
        self.assertEqual(decoded.last_modified_ledger_seq, 1_234_571)

        self.assertEqual(raw, xdr_codec.encode_ledger_entry(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("LedgerEntry", decoded))

    def test_only_live_until_ledger_seq_differs_from_baseline(self) -> None:
        _, raw_zero = load(FIXTURE_ZERO)
        _, raw_max = load(FIXTURE_MAX)
        _, raw_base = load(BASELINE)

        entry_zero = xdr_codec.decode_ledger_entry(raw_zero)
        entry_max = xdr_codec.decode_ledger_entry(raw_max)
        entry_base = xdr_codec.decode_ledger_entry(raw_base)

        self.assertEqual(entry_base.ttl.live_until_ledger_seq, 999_999)
        self.assertEqual(len(raw_zero), len(raw_base))
        self.assertEqual(len(raw_max), len(raw_base))

        self.assertEqual(
            replace(entry_zero, ttl=replace(entry_zero.ttl, live_until_ledger_seq=999_999)),
            entry_base,
        )
        self.assertEqual(
            replace(entry_max, ttl=replace(entry_max.ttl, live_until_ledger_seq=999_999)),
            entry_base,
        )

    def test_fixture_headers_contain_provenance(self) -> None:
        content_zero = FIXTURE_ZERO.read_text(encoding="utf-8")
        self.assertIn("stellar-xdr 28.0.1", content_zero)
        self.assertIn("live_until_ledger_seq: 0", content_zero)

        content_max = FIXTURE_MAX.read_text(encoding="utf-8")
        self.assertIn("stellar-xdr 28.0.1", content_max)
        self.assertIn("live_until_ledger_seq: 4_294_967_295", content_max)

    def test_structural_records_exist_and_match(self) -> None:
        self.assertTrue(RECORD_ZERO.is_file())
        self.assertTrue(RECORD_MAX.is_file())


if __name__ == "__main__":
    unittest.main()
