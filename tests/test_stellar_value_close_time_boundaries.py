"""Focused tests for StellarValue closeTime uint64 endpoint fixtures (issue #559).

Asserts:
- closeTime = 0 decodes as the unsigned uint64 minimum.
- closeTime = 18446744073709551615 (u64::MAX) decodes as the unsigned uint64 maximum.
- Both fixtures identify the pinned XDR source and official typed oracle output.
- Each fixture produces a byte-identical re-encoding.
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

ZERO_ID = "p28-xdr-stellar-value-close-time-zero"
MAX_ID = "p28-xdr-stellar-value-close-time-u64-max"

FIXTURE_DIR = REPO_ROOT / "protocol-28" / "xdr" / "stellar-value"
RECORD_DIR = REPO_ROOT / "protocol-28" / "evidence" / "records"


def load(fixture_id: str) -> tuple[dict, bytes]:
    path = FIXTURE_DIR / f"{fixture_id}.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class StellarValueCloseTimeBoundaryTests(unittest.TestCase):
    def _roundtrip(self, fixture_id: str) -> xdr_codec.StellarValue:
        data, raw = load(fixture_id)
        self.assertEqual(data["id"], fixture_id)
        self.assertEqual(data["protocol"], 28)
        self.assertEqual(data["surface"], "xdr")
        self.assertEqual(data["category"], "stellar-value")
        self.assertEqual(data["type"], "StellarValue")
        self.assertEqual(data["kind"], "roundtrip")
        self.assertIn("source_reference", data)

        decoded = xdr_codec.decode_stellar_value(raw)
        decoded_generic = xdr_codec.decode_xdr("StellarValue", raw)
        self.assertEqual(decoded, decoded_generic)

        # tx_set_hash is the synthetic 0x11-filled hash used across StellarValue fixtures
        self.assertEqual(decoded.tx_set_hash, bytes([0x11]) * 32)

        # STELLAR_VALUE_BASIC ext
        self.assertEqual(decoded.ext.ext_type, xdr_codec.STELLAR_VALUE_BASIC)
        self.assertEqual(decoded.ext.ext_type, 0)

        # Empty upgrades vector
        self.assertEqual(decoded.upgrades, [])

        # Byte-identical re-encoding
        reencoded = xdr_codec.encode_stellar_value(decoded)
        self.assertEqual(reencoded, raw)
        self.assertEqual(xdr_codec.encode_xdr("StellarValue", decoded), raw)

        return decoded

    def test_close_time_zero(self) -> None:
        decoded = self._roundtrip(ZERO_ID)
        self.assertEqual(decoded.close_time, 0)

    def test_close_time_u64_max(self) -> None:
        decoded = self._roundtrip(MAX_ID)
        self.assertEqual(decoded.close_time, 18446744073709551615)
        self.assertEqual(decoded.close_time, 2**64 - 1)

    def test_close_time_zero_evidence_record(self) -> None:
        _, raw = load(ZERO_ID)
        record = json.loads(
            (RECORD_DIR / f"{ZERO_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], ZERO_ID)
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256((FIXTURE_DIR / f"{ZERO_ID}.toml").read_bytes()).hexdigest())

    def test_close_time_u64_max_evidence_record(self) -> None:
        _, raw = load(MAX_ID)
        record = json.loads(
            (RECORD_DIR / f"{MAX_ID}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["fixtureId"], MAX_ID)
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(record["fixtureSha256"], hashlib.sha256((FIXTURE_DIR / f"{MAX_ID}.toml").read_bytes()).hexdigest())

    def test_endpoints_differ_only_in_close_time_bytes(self) -> None:
        """The two fixtures are identical except for the 8 closeTime bytes."""
        _, raw_zero = load(ZERO_ID)
        _, raw_max = load(MAX_ID)
        # Both are 48 bytes: 32 (hash) + 8 (closeTime) + 4 (upgrades count) + 4 (ext)
        self.assertEqual(len(raw_zero), 48)
        self.assertEqual(len(raw_max), 48)
        # Identical prefix (tx_set_hash) and suffix (upgrades, ext)
        self.assertEqual(raw_zero[:32], raw_max[:32])
        self.assertEqual(raw_zero[40:], raw_max[40:])
        # closeTime bytes at offset 32..40
        self.assertEqual(raw_zero[32:40], b"\x00" * 8)
        self.assertEqual(raw_max[32:40], b"\xff" * 8)


if __name__ == "__main__":
    unittest.main()
