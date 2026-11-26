"""Protocol 29 getVersionInfo identity fixture semantics."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "protocol-29" / "rpc" / "p29-rpc-version-info-protocol-29.toml"


class Protocol29VersionInfoFixtureTests(unittest.TestCase):
    def test_fixture_validates_as_a_protocol_29_identity_assertion(self) -> None:
        run = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "validate" / "validate.py"), "protocol-29", "--format", "json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
        report = json.loads(run.stdout)
        self.assertTrue(report["valid"], report["errors"])

        import tomllib

        fixture = tomllib.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["id"], "p29-rpc-version-info-protocol-29")
        self.assertEqual(fixture["protocol"], 29)
        self.assertEqual(fixture["surface"], "rpc")
        self.assertEqual(fixture["category"], "network")
        self.assertIn("reports protocol 29", fixture["description"])
        self.assertEqual(fixture["method"], "get-version-info")
        self.assertEqual(
            fixture["assert"],
            [{"kind": "field-equals", "field": "protocolVersion", "value": 29}],
        )

    def test_invalid_schema_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            invalid = root / "invalid.toml"
            invalid.write_text(
                FIXTURE.read_text(encoding="utf-8") + "\nunexpected_field = true\n",
                encoding="utf-8",
            )
            run = subprocess.run(
                [sys.executable, str(REPO_ROOT / "tools" / "validate" / "validate.py"), str(root)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(run.returncode, 1)
        self.assertIn("unexpected_field", run.stderr)


    def test_commit_hash_in_testnet_capture_is_valid_40_hex(self) -> None:
        capture = json.loads(
            (REPO_ROOT / "protocol-29" / "evidence" / "testnet" / "get-version-info.json").read_text(
                encoding="utf-8"
            )
        )
        sha = capture["response"]["result"]["commitHash"]
        self.assertRegex(sha, r"^[0-9a-f]{40}$")

    def test_malformed_commit_hashes_are_rejected(self) -> None:
        for bad in ("0" * 39, "0" * 41, "G" * 40, "055dc9c7a9a9e038c6807a555c09bd94b85c9e2", ""):
            with self.subTest(hash=bad):
                self.assertIsNone(re.fullmatch(r"[0-9a-f]{40}", bad))

    def test_valid_version_info_object_passes(self) -> None:
        valid = {
            "version": "29.0.1-055dc9c7a9a9e038c6807a555c09bd94b85c9e2c",
            "commitHash": "055dc9c7a9a9e038c6807a555c09bd94b85c9e2c",
            "buildTimestamp": "2026-10-13T09:48:37",
            "captiveCoreVersion": "stellar-core 29.0.0 (4eb83337380a29ad0907f4e32196ce97b8dc7649)",
            "protocolVersion": 29,
        }
        self.assertRegex(valid["commitHash"], r"^[0-9a-f]{40}$")
        self.assertIsInstance(valid["protocolVersion"], int)


if __name__ == "__main__":
    unittest.main()
