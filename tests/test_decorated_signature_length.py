"""Focused test for DecoratedSignature opaque byte length limits (issue #534)."""
from __future__ import annotations

import base64
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import xdr_codec

EMPTY_FIXTURE = REPO_ROOT / "protocol-28" / "xdr" / "campaign" / "p28-xdr-decorated-signature-length-empty.toml"
ONE_BYTE_FIXTURE = REPO_ROOT / "protocol-28" / "xdr" / "campaign" / "p28-xdr-decorated-signature-length-one-byte.toml"
OVER_LIMIT_FIXTURE = REPO_ROOT / "protocol-28" / "xdr" / "campaign" / "p28-xdr-decorated-signature-length-over-limit.toml"
BASELINE_MAXIMUM = (
    REPO_ROOT / "protocol-28" / "xdr" / "transaction-envelope" / "p28-xdr-transaction-envelope-v1-roundtrip.toml"
)

EMPTY_RECORD = REPO_ROOT / "protocol-28" / "evidence" / "records" / "p28-xdr-decorated-signature-length-empty.json"
ONE_BYTE_RECORD = REPO_ROOT / "protocol-28" / "evidence" / "records" / "p28-xdr-decorated-signature-length-one-byte.json"
OVER_LIMIT_RECORD = REPO_ROOT / "protocol-28" / "evidence" / "records" / "p28-xdr-decorated-signature-length-over-limit.json"


def load_fixture(path: Path) -> tuple[dict, bytes]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data, base64.b64decode(data["value_base64"], validate=True)


class DecoratedSignatureLengthTests(unittest.TestCase):
    def test_empty_signature_decodes_and_roundtrips(self) -> None:
        data, raw = load_fixture(EMPTY_FIXTURE)
        self.assertEqual(data["id"], "p28-xdr-decorated-signature-length-empty")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

        decoded = xdr_codec.decode_transaction_envelope(raw)
        decoded_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(decoded, decoded_generic)
        self.assertEqual(decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        sigs = decoded.v1.signatures
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].hint, bytes([0x66]) * 4)
        self.assertEqual(sigs[0].signature, b"")
        self.assertEqual(len(sigs[0].signature), 0)

        # Exact byte roundtrip with both encoders
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_one_byte_signature_decodes_and_roundtrips(self) -> None:
        data, raw = load_fixture(ONE_BYTE_FIXTURE)
        self.assertEqual(data["id"], "p28-xdr-decorated-signature-length-one-byte")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "roundtrip")

        decoded = xdr_codec.decode_transaction_envelope(raw)
        decoded_generic = xdr_codec.decode_xdr("TransactionEnvelope", raw)
        self.assertEqual(decoded, decoded_generic)
        self.assertEqual(decoded.envelope_type, xdr_codec.ENVELOPE_TYPE_TX)

        sigs = decoded.v1.signatures
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].hint, bytes([0x66]) * 4)
        self.assertEqual(sigs[0].signature, bytes([0x11]))
        self.assertEqual(len(sigs[0].signature), 1)

        # Exact byte roundtrip with both encoders
        self.assertEqual(raw, xdr_codec.encode_transaction_envelope(decoded))
        self.assertEqual(raw, xdr_codec.encode_xdr("TransactionEnvelope", decoded))

    def test_baseline_maximum_has_64_byte_signature(self) -> None:
        _, base_raw = load_fixture(BASELINE_MAXIMUM)
        decoded = xdr_codec.decode_transaction_envelope(base_raw)
        sigs = decoded.v1.signatures
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].hint, bytes([0x66]) * 4)
        self.assertEqual(sigs[0].signature, bytes([0x66]) * 64)
        self.assertEqual(len(sigs[0].signature), 64)

    def test_over_limit_fixture_mutation_and_rejection_with_both_decoders(self) -> None:
        data, raw = load_fixture(OVER_LIMIT_FIXTURE)
        self.assertEqual(data["id"], "p28-xdr-decorated-signature-length-over-limit")
        self.assertEqual(data["type"], "TransactionEnvelope")
        self.assertEqual(data["kind"], "decode-failure")

        # Verify mutation from maximum baseline: word at offset 132 replaced 64 -> 65
        _, base_raw = load_fixture(BASELINE_MAXIMUM)
        expected_raw = bytearray(base_raw)
        self.assertEqual(int.from_bytes(expected_raw[132:136], "big"), 64)
        expected_raw[132:136] = (65).to_bytes(4, "big")
        self.assertEqual(raw, bytes(expected_raw))

        decoders = [
            ("decode_transaction_envelope", xdr_codec.decode_transaction_envelope),
            ("decode_xdr", lambda b: xdr_codec.decode_xdr("TransactionEnvelope", b)),
        ]
        for name, decoder in decoders:
            with self.subTest(decoder=name):
                with self.assertRaises(xdr_codec.XdrCodecError) as cm:
                    decoder(raw)
                err_msg = str(cm.exception).lower()
                self.assertTrue(
                    any(term in err_msg for term in ("length", "limit", "exceed")),
                    f"Error message does not identify length/count limit: {cm.exception}",
                )

    def test_structural_records_exist(self) -> None:
        self.assertTrue(EMPTY_RECORD.is_file(), f"Missing record: {EMPTY_RECORD}")
        self.assertTrue(ONE_BYTE_RECORD.is_file(), f"Missing record: {ONE_BYTE_RECORD}")
        self.assertTrue(OVER_LIMIT_RECORD.is_file(), f"Missing record: {OVER_LIMIT_RECORD}")


if __name__ == "__main__":
    unittest.main()
