"""Run a deterministic fixture-pack archive against a pinned engine binary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.pack.verify_archive import extract_safely

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_BIN = os.environ.get("STELLAR_CANARY_BIN")
ENGINE_VERSION = "0.2.0"


class EngineCommandError(AssertionError):
    """A command failed, with its exit code and captured output preserved."""


def run_checked(
    command: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise EngineCommandError(
            f"command exited with code {result.returncode}: {' '.join(command)}\n"
            f"stdout:\n{result.stdout or '<empty>'}\n"
            f"stderr:\n{result.stderr or '<empty>'}"
        )
    return result


class EngineCompatibilityTests(unittest.TestCase):
    @unittest.skipUnless(
        ENGINE_BIN or os.environ.get("STELLAR_CANARY_REQUIRED") == "1",
        "set STELLAR_CANARY_BIN to run pinned-engine integration",
    )
    def test_built_archive_passes_pinned_engine(self) -> None:
        engine = Path(ENGINE_BIN or "")
        self.assertTrue(engine.is_file(), f"engine binary does not exist: {engine}")
        self.assertTrue(
            os.access(engine, os.X_OK), f"engine binary is not executable: {engine}"
        )

        with tempfile.TemporaryDirectory(prefix="canary-engine-compat-") as directory:
            work = Path(directory)
            archive_dir = work / "archive"
            archive = archive_dir / "protocolcanary-fixtures-1.0.0.tar.gz"
            extracted_pack = work / "extracted-pack"
            extracted_pack.mkdir()

            run_checked(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools/pack/pack.py"),
                    str(REPO_ROOT / "protocol-28"),
                    "--version",
                    "1.0.0",
                    "--output-dir",
                    str(archive_dir),
                ]
            )
            run_checked(
                [sys.executable, str(REPO_ROOT / "tools/pack/verify_archive.py"), str(archive)]
            )
            extract_safely(archive, extracted_pack)

            version = run_checked([str(engine), "--version"])
            self.assertIn(ENGINE_VERSION, version.stdout, version.stdout)

            config = work / ".stellar-canary.toml"
            config.write_text(
                "version = 1\nprotocol = 28\n\n"
                "[tests]\nxdr = true\nrpc = false\nsoroban = false\n",
                encoding="utf-8",
            )
            result = run_checked(
                [
                    str(engine),
                    "check",
                    "--fixtures-dir",
                    str(extracted_pack),
                    "--protocol",
                    "28",
                    "--json",
                    "--no-cache",
                ],
                cwd=work,
            )

            try:
                report = json.loads(result.stdout)
            except json.JSONDecodeError as error:
                self.fail(
                    f"engine output was not valid JSON: {error}\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            self.assertIsInstance(report, dict, result.stdout)
            self.assertEqual(report.get("status"), "pass", report)
            counts = report.get("counts")
            self.assertIsInstance(counts, dict, report)
            for field in ("total", "failed", "errors"):
                self.assertIsInstance(counts.get(field), int, counts)
            self.assertGreater(counts["total"], 0, counts)
            self.assertEqual(counts["failed"], 0, counts)
            self.assertEqual(counts["errors"], 0, counts)
            results = report.get("results")
            self.assertIsInstance(results, list, report)
            self.assertTrue(results, report)
            self.assertTrue(
                all(isinstance(item, dict) and item.get("surface") == "xdr" for item in results),
                results,
            )
            print(f"Engine {ENGINE_VERSION} passed the extracted archive: {counts}")

    def test_nonzero_exit_contains_command_and_output(self) -> None:
        failed = subprocess.CompletedProcess(
            args=["stellar-canary", "check"],
            returncode=7,
            stdout="report was incomplete",
            stderr="engine rejected fixture",
        )
        with mock.patch("tests.test_engine_compat.subprocess.run", return_value=failed):
            with self.assertRaises(EngineCommandError) as raised:
                run_checked(["stellar-canary", "check"])

        message = str(raised.exception)
        self.assertIn("exited with code 7", message)
        self.assertIn("stellar-canary check", message)
        self.assertIn("report was incomplete", message)
        self.assertIn("engine rejected fixture", message)


class MissingEngineBinaryTests(unittest.TestCase):
    """An engine that cannot be launched must fail loudly, naming the path.

    ``test_engine_compat.py`` has no wrapper module of its own: the pinned-engine
    test simply runs the configured binary through ``run_checked``. That means
    the failure mode for a missing or non-executable engine is whatever
    ``subprocess`` raises, so these tests pin that a missing engine surfaces as
    ``FileNotFoundError`` with ``errno`` 2 instead of degrading into an opaque
    exit code, and that the diagnostic names the unresolved executable.

    Where the path is named depends on the platform: POSIX ``exec`` attaches it
    to ``FileNotFoundError.filename`` (and therefore to ``str(error)``), while
    Windows raises ``[WinError 2] The system cannot find the file specified``
    with no path attached. On Windows the path is named by the module's own
    ``is_file()`` / ``os.access`` guard in the pinned-engine test, so these
    tests assert the attached path only where the platform provides it.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="canary-missing-engine-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def assert_names_path(self, error: FileNotFoundError, path: str) -> None:
        """Assert the diagnostic names ``path`` where the platform attaches it."""
        if os.name == "posix":
            self.assertEqual(error.filename, path)
            self.assertIn(path, str(error))
        else:
            # WinError 2 carries no filename; the pinned-engine guard, which
            # formats the configured path into its own message, covers naming.
            self.assertIsNone(error.filename)
            self.assertEqual(getattr(error, "winerror", None), 2)

    def test_missing_engine_binary_raises_filenotfound_with_its_path(self) -> None:
        missing = self.work / "does-not-exist" / "stellar-canary"
        with self.assertRaises(FileNotFoundError) as raised:
            run_checked([str(missing), "--version"])

        error = raised.exception
        self.assertEqual(error.errno, 2)
        self.assert_names_path(error, str(missing))

    def test_missing_engine_binary_is_reported_before_archive_work(self) -> None:
        # The pinned-engine test resolves the executable first: a missing path
        # fails without packing or unpacking an archive, so no build output is
        # left behind for the diagnostic to be buried under.
        engine = self.work / "absent-engine"
        with self.assertRaises(FileNotFoundError) as raised:
            run_checked([str(engine), "check", "--fixtures-dir", str(self.work)])
        self.assertEqual(raised.exception.errno, 2)
        self.assert_names_path(raised.exception, str(engine))
        self.assertEqual(list(self.work.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "executable bit is a POSIX concept")
    def test_non_executable_engine_binary_raises_permission_error(self) -> None:
        engine = self.work / "stellar-canary"
        engine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        engine.chmod(0o644)

        with self.assertRaises(PermissionError) as raised:
            run_checked([str(engine), "--version"])
        self.assertEqual(raised.exception.errno, 13)
        self.assertIn(str(engine), str(raised.exception))

    def test_pinned_engine_test_is_skipped_rather_than_silently_green(self) -> None:
        # Without STELLAR_CANARY_BIN (or STELLAR_CANARY_REQUIRED=1) the pinned
        # integration cannot run; unittest must report it as skipped so a
        # missing engine is visible instead of looking like a pass.
        configured = bool(ENGINE_BIN) or os.environ.get("STELLAR_CANARY_REQUIRED") == "1"
        pinned = EngineCompatibilityTests.test_built_archive_passes_pinned_engine
        self.assertEqual(getattr(pinned, "__unittest_skip__", False), not configured)


if __name__ == "__main__":
    unittest.main()
