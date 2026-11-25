"""Release events must select one explicit protocol pack and version."""
from __future__ import annotations

import io
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_support as support  # noqa: E402

selector = support.load_tool("canary_select_pack", "tools/release/select_pack.py")
SELECTOR_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "release" / "select_pack.py"


class PackSelectionTests(unittest.TestCase):
    def test_versioned_tags_select_exact_protocol_and_version(self) -> None:
        for protocol in ("28", "29", "30"):
            with self.subTest(protocol=protocol):
                self.assertEqual(
                    selector.select(
                        event="push", tag=f"fixtures-p{protocol}-v1.2.3"
                    ),
                    {
                        "pack": f"protocol-{protocol}",
                        "protocol": protocol,
                        "version": "1.2.3",
                        "verified": "true" if protocol in ("29", "30") else "false",
                    },
                )

    def test_manual_dispatch_requires_an_explicit_supported_protocol(self) -> None:
        selected = selector.select(
            event="workflow_dispatch", protocol="29", version="2.0.1"
        )
        self.assertEqual(selected["pack"], "protocol-29")
        self.assertEqual(selected["version"], "2.0.1")
        self.assertEqual(selected["verified"], "true")

    def test_protocol30_manual_dispatch_requires_verified_pack(self) -> None:
        selected = selector.select(event="workflow_dispatch", protocol="30", version="0.1.0")
        self.assertEqual(selected["pack"], "protocol-30")
        self.assertEqual(selected["verified"], "true")

    def test_unscoped_or_legacy_tags_are_rejected(self) -> None:
        for tag in ("v1.2.3", "fixtures-v1.2.3", "protocol-29", "fixtures-p31-v1.2.3"):
            with self.subTest(tag=tag), self.assertRaises(selector.SelectionError):
                selector.select(event="release", tag=tag)

    def test_malformed_versions_and_ambiguous_inputs_are_rejected(self) -> None:
        for version in ("1.2", "01.2.3", "1.2.3-rc.1", "1.2.3\n"):
            with self.subTest(version=version), self.assertRaises(selector.SelectionError):
                selector.select(
                    event="workflow_dispatch", protocol="29", version=version
                )
        with self.assertRaises(selector.SelectionError):
            selector.select(event="push", tag="fixtures-p28-v1.2.3", protocol="28")
        with self.assertRaises(selector.SelectionError):
            selector.select(event="workflow_dispatch", protocol="31", version="1.2.3")
        with self.assertRaises(selector.SelectionError):
            selector.select(event="workflow_dispatch", tag="fixtures-p29-v1.2.3", protocol="29", version="1.2.3")
        with self.assertRaises(selector.SelectionError):
            selector.select(event="unsupported")


class ReleaseRefValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git("init")
        self.git("checkout", "-b", "main")
        self.git("config", "user.name", "Fixture Test")
        self.git("config", "user.email", "fixture-test@example.invalid")
        (self.repo / "README.md").write_text("trusted main commit\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "trusted main commit")
        self.main_sha = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.main_sha)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def run_selector(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SELECTOR_SCRIPT), *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def test_tag_cli_requires_and_validates_ref_context(self) -> None:
        tag = "fixtures-p29-v1.2.3"
        ref = f"refs/tags/{tag}"
        self.git("tag", tag)

        missing_context = self.run_selector("--event", "push", "--tag", tag)
        self.assertEqual(missing_context.returncode, 2)
        self.assertIn("require release-ref validation", missing_context.stderr)

        valid_context = self.run_selector(
            "--event",
            "push",
            "--tag",
            tag,
            "--ref",
            ref,
            "--sha",
            self.main_sha,
            "--main-ref",
            "refs/remotes/origin/main",
        )
        self.assertEqual(valid_context.returncode, 0, valid_context.stderr)
        self.assertIn("pack=protocol-29", valid_context.stdout)
        self.assertIn(f"commit={self.main_sha}", valid_context.stdout)

    def test_in_process_cli_covers_tag_and_manual_dispatch_paths(self) -> None:
        tag = "fixtures-p29-v1.2.3"
        ref = f"refs/tags/{tag}"
        self.git("tag", tag)

        def call_main(args: list[str]) -> tuple[int, str, str]:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = selector.main(args)
            return result, stdout.getvalue(), stderr.getvalue()

        with chdir(self.repo):
            missing_ref = call_main(["--event", "push", "--tag", tag])
            self.assertEqual(missing_ref[0], 2)
            self.assertIn("require release-ref validation", missing_ref[2])

            extra_protocol = call_main(
                ["--event", "push", "--tag", tag, "--ref", ref, "--sha", self.main_sha,
                 "--protocol", "29"]
            )
            self.assertEqual(extra_protocol[0], 2)
            self.assertIn("select both protocol and version", extra_protocol[2])

            valid_tag = call_main(
                ["--event", "push", "--tag", tag, "--ref", ref, "--sha", self.main_sha]
            )
            self.assertEqual(valid_tag[0], 0, valid_tag[2])
            self.assertIn("pack=protocol-29", valid_tag[1])

            manual_with_ref = call_main(
                ["--event", "workflow_dispatch", "--protocol", "29", "--version", "1.2.3",
                 "--ref", ref]
            )
            self.assertEqual(manual_with_ref[0], 2)
            self.assertIn("does not accept a release ref", manual_with_ref[2])

            manual = call_main(
                ["--event", "workflow_dispatch", "--protocol", "29", "--version", "1.2.3"]
            )
            self.assertEqual(manual[0], 0, manual[2])
            self.assertIn("verified=true", manual[1])

    def test_script_entrypoint_calls_main(self) -> None:
        tag = "fixtures-p28-v1.2.3"
        self.git("tag", tag)
        argv = [
            str(SELECTOR_SCRIPT),
            "--event", "push",
            "--tag", tag,
            "--ref", f"refs/tags/{tag}",
            "--sha", self.main_sha,
            "--main-ref", "refs/remotes/origin/main",
        ]
        stdout = io.StringIO()
        with chdir(self.repo), mock.patch.object(sys, "argv", argv), redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(SELECTOR_SCRIPT), run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("pack=protocol-28", stdout.getvalue())

    def test_push_and_published_release_accept_only_exact_main_tag_commit(self) -> None:
        tag = "fixtures-p29-v1.2.3"
        ref = f"refs/tags/{tag}"
        self.git("tag", tag)

        for event in ("push", "release"):
            with self.subTest(event=event):
                selection = selector.validate_release_ref(
                    event=event,
                    tag=tag,
                    ref=ref,
                    sha=self.main_sha,
                    repo=self.repo,
                )
                self.assertEqual(selection["pack"], "protocol-29")
                self.assertEqual(selection["verified"], "true")
                self.assertEqual(selection["commit"], self.main_sha)

    def test_protocol30_ref_validation_keeps_main_ancestry(self) -> None:
        tag = "fixtures-p30-v0.1.0"
        self.git("tag", tag)
        for event in ("push", "release"):
            selected = selector.validate_release_ref(
                event=event, tag=tag, ref=f"refs/tags/{tag}",
                sha=self.main_sha, repo=self.repo,
            )
            self.assertEqual(selected["pack"], "protocol-30")
            self.assertEqual(selected["verified"], "true")

    def test_release_ref_must_match_event_tag_and_commit(self) -> None:
        tag = "fixtures-p28-v1.2.3"
        self.git("tag", tag)

        with self.assertRaisesRegex(selector.SelectionError, "does not exactly match"):
            selector.validate_release_ref(
                event="release",
                tag="fixtures-p29-v1.2.3",
                ref=f"refs/tags/{tag}",
                sha=self.main_sha,
                repo=self.repo,
            )

        with self.assertRaisesRegex(selector.SelectionError, "not event commit"):
            selector.validate_release_ref(
                event="push",
                tag=tag,
                ref=f"refs/tags/{tag}",
                sha="0" * 40,
                repo=self.repo,
            )

        with self.assertRaisesRegex(selector.SelectionError, "full hexadecimal commit ID"):
            selector.validate_release_ref(
                event="push",
                tag=tag,
                ref=f"refs/tags/{tag}",
                sha="not-a-commit",
                repo=self.repo,
            )

    def test_git_lookup_and_ancestry_errors_fail_closed(self) -> None:
        tag = "fixtures-p28-v1.2.3"
        ref = f"refs/tags/{tag}"
        self.git("tag", tag)
        args = {
            "event": "push",
            "tag": tag,
            "ref": ref,
            "sha": self.main_sha,
            "repo": self.repo,
        }

        with mock.patch.object(selector.subprocess, "run", side_effect=OSError("git missing")):
            with self.assertRaisesRegex(selector.SelectionError, "cannot resolve release tag"):
                selector.validate_release_ref(**args)

        failed_git = subprocess.CalledProcessError(128, ["git", "rev-parse"])
        with mock.patch.object(selector.subprocess, "run", side_effect=failed_git):
            with self.assertRaisesRegex(selector.SelectionError, "cannot resolve release tag"):
                selector.validate_release_ref(**args)

        resolved = subprocess.CompletedProcess([], 0, stdout=f"{self.main_sha}\n")
        with mock.patch.object(selector.subprocess, "run", side_effect=[resolved, OSError("git missing")]):
            with self.assertRaisesRegex(selector.SelectionError, "verify release commit ancestry"):
                selector.validate_release_ref(**args)

    def test_release_tag_on_commit_outside_main_history_is_rejected(self) -> None:
        tag = "fixtures-p28-v1.2.4"
        self.git("checkout", "-b", "untrusted")
        (self.repo / "untrusted.txt").write_text("not on main\n", encoding="utf-8")
        self.git("add", "untrusted.txt")
        self.git("commit", "-m", "untrusted side commit")
        side_sha = self.git("rev-parse", "HEAD")
        self.git("tag", tag)

        with self.assertRaisesRegex(selector.SelectionError, "not in protected main history"):
            selector.validate_release_ref(
                event="push",
                tag=tag,
                ref=f"refs/tags/{tag}",
                sha=side_sha,
                repo=self.repo,
            )


class MissingPackDirectoryTests(unittest.TestCase):
    """A protocol with no pack on disk must never be selected silently.

    ``select_pack.py`` chooses a pack from the release tag or dispatch inputs
    and never touches the filesystem, so the only place a missing protocol can
    be caught is the selection itself. These tests pin both halves of that
    contract: an unsupported protocol is rejected with an actionable message
    naming the packs that exist, and every pack the selector can return is a
    real directory holding at least one JSON fixture.
    """

    def test_unsupported_protocol_is_rejected_with_the_supported_packs(self) -> None:
        # 27 has no pack directory, 31 never shipped, and the blank/None values
        # a workflow input can carry must not fall through to a default pack.
        for protocol in ("27", "31", "", "3 0", "28\n"):
            with self.subTest(protocol=protocol):
                with self.assertRaises(selector.SelectionError) as raised:
                    selector.select(
                        event="workflow_dispatch",
                        protocol=protocol,
                        version="1.0.0",
                    )
                self.assertIn(
                    "manual dispatch protocol must be 28, 29 or 30",
                    str(raised.exception),
                )

    def test_unsupported_protocol_exits_nonzero_with_a_clear_diagnostic(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SELECTOR_SCRIPT),
                "--event",
                "workflow_dispatch",
                "--protocol",
                "31",
                "--version",
                "1.0.0",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("error:", result.stderr)
        self.assertIn("protocol must be 28, 29 or 30", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_every_selectable_pack_is_a_directory_with_json_fixtures(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        for protocol in ("28", "29", "30"):
            with self.subTest(protocol=protocol):
                selected = selector.select(
                    event="workflow_dispatch",
                    protocol=protocol,
                    version="1.0.0",
                )
                pack = repository / selected["pack"]
                self.assertTrue(
                    pack.is_dir(),
                    f"selector returned {selected['pack']!r} but {pack} is not a directory",
                )
                fixtures = sorted(pack.rglob("*.json"))
                self.assertTrue(
                    fixtures,
                    f"{pack} contains no JSON fixture files; an empty pack directory "
                    "would publish a release with nothing in it",
                )

    def test_protocol_27_pack_stays_unselectable_despite_its_directory(self) -> None:
        # Directory presence is not the selector's signal: protocol-27 ships in
        # the repository but has no release support, so it must stay refused,
        # while protocol-31 has neither a directory nor a selection path.
        repository = Path(__file__).resolve().parents[1]
        self.assertTrue((repository / "protocol-27").is_dir())
        self.assertFalse((repository / "protocol-31").is_dir())

        with self.assertRaises(selector.SelectionError):
            selector.select(event="workflow_dispatch", protocol="27", version="1.0.0")
        with self.assertRaises(selector.SelectionError):
            selector.select(event="push", tag="fixtures-p27-v1.0.0")


if __name__ == "__main__":
    unittest.main()
