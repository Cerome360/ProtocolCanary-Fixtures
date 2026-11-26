"""Release workflow permissions and ref checks must stay narrowly scoped.

Issue #612 adds two further guarantees to the release workflow test suite:
every job states its own least-privilege ``permissions`` block (a job with
``id-token: write`` may not also hold a broad repository write), and every
action an artifact step uses is pinned to a full commit SHA. The artifact
hashes themselves are checked too, so the build, upload, download, re-verify
and publish path cannot lose a digest check unnoticed.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release-pack.yml"
RELEASING_DOC = ROOT / "docs" / "releasing.md"

SHA_PIN_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
USES_RE = re.compile(r"(?m)^\s*(?:- )?uses:\s*(\S+)\s*(?:#.*)?$")
JOB_NAME_RE = re.compile(r"(?m)^  ([A-Za-z0-9_-]+):\s*$")
STEP_RE = re.compile(r"(?ms)^      - .*?(?=^      - |\Z)")
# The repository permission scopes GitHub Actions defines. A job must name a
# scope from this set at read/write/none; `write-all` and `read-all` are not
# scoped at all, which is exactly what least privilege forbids.
PERMISSION_SCOPES = frozenset(
    {
        "actions",
        "attestations",
        "checks",
        "contents",
        "deployments",
        "discussions",
        "id-token",
        "issues",
        "packages",
        "pages",
        "pull-requests",
        "repository-projects",
        "security-events",
        "statuses",
    }
)
PERMISSION_LEVELS = frozenset({"read", "write", "none"})
# Repository-wide writes a job must not hold while it holds id-token: write.
BROAD_WRITE_SCOPES = frozenset(
    {
        "actions",
        "checks",
        "contents",
        "deployments",
        "discussions",
        "issues",
        "packages",
        "pages",
        "pull-requests",
        "repository-projects",
        "security-events",
        "statuses",
    }
)
EXPECTED_PERMISSIONS = {
    "build": {"contents": "read"},
    "attest": {"contents": "read", "id-token": "write", "attestations": "write"},
    "publish": {"contents": "write"},
}


def job_block(workflow: str, name: str) -> str:
    lines = workflow.splitlines()
    try:
        start = lines.index(f"  {name}:")
    except ValueError as error:
        raise AssertionError(f"workflow is missing job {name!r}") from error
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break
    return "\n".join(lines[start:end])


class ReleaseWorkflowSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.docs = RELEASING_DOC.read_text(encoding="utf-8")

    def test_workflow_defaults_to_no_permissions_and_scopes_write_access(self) -> None:
        self.assertRegex(self.workflow, r"(?m)^permissions: \{\}$")

        build = job_block(self.workflow, "build")
        self.assertRegex(build, r"(?m)^    permissions:\n      contents: read$")
        self.assertNotRegex(build, r"(?m)^      [a-z_-]+: write$")

        attest = job_block(self.workflow, "attest")
        self.assertIn("id-token: write", attest)
        self.assertIn("attestations: write", attest)
        self.assertNotIn("contents: write", attest)
        self.assertIn("github.event_name == 'push'", attest)

        publish = job_block(self.workflow, "publish")
        self.assertRegex(publish, r"(?m)^      contents: write$")
        self.assertNotIn("id-token: write", publish)
        self.assertNotIn("attestations: write", publish)
        self.assertIn("github.event_name == 'release' && github.event.action == 'published'", publish)

    def test_every_checkout_disables_credential_persistence(self) -> None:
        steps = re.findall(r"(?ms)^      - .*?(?=^      - |\Z)", self.workflow)
        checkout_steps = [step for step in steps if "uses: actions/checkout@" in step]
        self.assertEqual(len(checkout_steps), 2)
        for step in checkout_steps:
            self.assertIn("persist-credentials: false", step)

    def test_tag_and_release_jobs_validate_exact_ref_and_main_ancestry(self) -> None:
        self.assertGreaterEqual(self.workflow.count("--ref \"$EVENT_REF\""), 1)
        self.assertGreaterEqual(self.workflow.count("--sha \"$EVENT_SHA\""), 1)
        self.assertGreaterEqual(
            self.workflow.count("--main-ref refs/remotes/origin/main"), 2
        )
        self.assertIn("github.event.release.tag_name", self.workflow)
        selector = (ROOT / "tools/release/select_pack.py").read_text(encoding="utf-8")
        self.assertIn('"merge-base"', selector)
        self.assertIn('"--is-ancestor"', selector)

    def test_p29_verified_gate_and_tag_attestation_are_separate_from_upload(self) -> None:
        build = job_block(self.workflow, "build")
        attest = job_block(self.workflow, "attest")
        publish = job_block(self.workflow, "publish")
        self.assertIn("VERIFY_ARGS+=(--verified)", build)
        self.assertNotIn("--allow-empty", self.workflow)
        self.assertIn("actions/attest-build-provenance", attest)
        self.assertNotIn("gh release upload", attest)
        self.assertIn("gh release upload", publish)
        self.assertNotIn("--clobber", publish)

    def test_p30_tag_is_supported_without_broadening_publish_permissions(self) -> None:
        self.assertIn('"fixtures-p30-v*"', self.workflow)
        self.assertIn('          - "30"', self.workflow)
        self.assertIn("fixtures-p30-v*", self.docs)

    def test_release_docs_require_tag_rules_and_use_current_scoped_examples(self) -> None:
        docs = self.docs.lower()
        self.assertIn("tag ruleset", docs)
        self.assertIn("restrict tag creation", docs)
        self.assertIn("block tag updates and deletion", docs)
        self.assertIn("workflow check alone does not protect against untrusted tag content", docs)
        self.assertIn("tag-push automation", docs)
        self.assertIn("release.published", docs)
        self.assertIn("fixtures-p28-v0.1.0", docs)
        self.assertIn("fixtures-p29-v0.1.0", docs)
        self.assertIn("95 fixture file(s) valid across 4 root(s)", docs)
        self.assertIn("93 fixture(s), 93 file(s) valid", docs)
        self.assertNotIn("OK: 31 fixture file(s)", docs)
        self.assertNotIn("(e.g. `v0.1.1`)", docs)


def job_names(workflow: str) -> list[str]:
    """The job names under ``jobs:``, in declaration order."""
    jobs = workflow.split("\njobs:\n", 1)
    if len(jobs) != 2:
        raise AssertionError("workflow has no jobs: block")
    return JOB_NAME_RE.findall(jobs[1])


def permissions_of(job: str) -> dict[str, str] | None:
    """The job's ``permissions`` mapping, ``{}`` for none, or ``None`` if absent."""
    lines = job.splitlines()
    for index, line in enumerate(lines):
        if line == "    permissions: {}":
            return {}
        if line == "    permissions:":
            mapping: dict[str, str] = {}
            for sub in lines[index + 1 :]:
                if not sub.startswith("      "):
                    break
                key, _, value = sub.strip().partition(":")
                mapping[key.strip()] = value.strip()
            return mapping
    return None


def action_refs(workflow: str) -> list[str]:
    """Every action reference in the workflow, without the comment."""
    return USES_RE.findall(workflow)


class LeastPrivilegeAndActionPinningTests(unittest.TestCase):
    """Per-job permissions, pinned actions and artifact hashes (issue #612)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.names = job_names(cls.workflow)
        cls.jobs = {name: job_block(cls.workflow, name) for name in cls.names}
        cls.steps = STEP_RE.findall(cls.workflow)

    def test_the_workflow_declares_exactly_the_three_release_jobs(self) -> None:
        self.assertEqual(self.names, ["build", "attest", "publish"])

    def test_permissions_are_scoped_per_job_and_never_global(self) -> None:
        global_blocks = re.findall(r"(?m)^permissions:.*$", self.workflow)
        self.assertEqual(global_blocks, ["permissions: {}"])
        for name in self.names:
            with self.subTest(job=name):
                permissions = permissions_of(self.jobs[name])
                self.assertIsNotNone(permissions, f"job {name} has no permissions block")
                self.assertTrue(permissions, f"job {name} has an empty permissions block")

    def test_no_job_uses_write_all_or_read_all(self) -> None:
        self.assertNotIn("write-all", self.workflow)
        self.assertNotIn("read-all", self.workflow)
        for name in self.names:
            with self.subTest(job=name):
                permissions = permissions_of(self.jobs[name]) or {}
                for scope, level in permissions.items():
                    self.assertIn(scope, PERMISSION_SCOPES)
                    self.assertIn(level, PERMISSION_LEVELS)

    def test_each_job_has_exactly_its_documented_permissions(self) -> None:
        for name, expected in EXPECTED_PERMISSIONS.items():
            with self.subTest(job=name):
                self.assertEqual(permissions_of(self.jobs[name]), expected)

    def test_id_token_jobs_do_not_also_grant_repository_write(self) -> None:
        token_jobs = [
            name
            for name in self.names
            if (permissions_of(self.jobs[name]) or {}).get("id-token") == "write"
        ]
        self.assertEqual(token_jobs, ["attest"])
        for name in token_jobs:
            permissions = permissions_of(self.jobs[name]) or {}
            with self.subTest(job=name):
                for scope in BROAD_WRITE_SCOPES:
                    self.assertNotEqual(
                        permissions.get(scope),
                        "write",
                        f"job {name} holds id-token: write and {scope}: write",
                    )
                writes = {scope for scope, level in permissions.items() if level == "write"}
                self.assertEqual(writes, {"id-token", "attestations"})

    def test_the_publish_job_has_no_identity_or_attestation_permission(self) -> None:
        permissions = permissions_of(self.jobs["publish"]) or {}
        self.assertNotIn("id-token", permissions)
        self.assertNotIn("attestations", permissions)
        self.assertEqual(permissions.get("contents"), "write")

    def test_the_build_job_cannot_write_or_attest(self) -> None:
        permissions = permissions_of(self.jobs["build"]) or {}
        self.assertNotIn("id-token", permissions)
        self.assertNotIn("attestations", permissions)
        self.assertEqual({scope for scope, level in permissions.items() if level == "write"}, set())

    def test_the_repository_token_is_only_available_to_publish(self) -> None:
        users = [
            name for name in self.names if "secrets.GITHUB_TOKEN" in self.jobs[name]
        ]
        self.assertEqual(users, ["publish"])

    def test_every_action_is_pinned_to_a_full_commit_sha(self) -> None:
        refs = action_refs(self.workflow)
        self.assertEqual(len(refs), 8)
        for ref in refs:
            with self.subTest(action=ref):
                self.assertRegex(ref, SHA_PIN_RE)
                action, _, sha = ref.partition("@")
                self.assertRegex(action, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
                self.assertEqual(len(sha), 40)
                self.assertEqual(sha, sha.lower())

    def test_every_action_family_uses_a_full_sha_not_a_moving_tag(self) -> None:
        actions = {ref.partition("@")[0] for ref in action_refs(self.workflow)}
        self.assertEqual(
            actions,
            {
                "actions/checkout",
                "actions/setup-python",
                "actions/upload-artifact",
                "actions/download-artifact",
                "actions/attest-build-provenance",
            },
        )
        for ref in action_refs(self.workflow):
            with self.subTest(action=ref):
                self.assertNotRegex(ref, r"@v\d")
                self.assertNotRegex(ref, r"@(main|master)$")

    def test_the_artifact_upload_step_is_pinned_and_fails_loudly(self) -> None:
        uploads = [step for step in self.steps if "uses: actions/upload-artifact@" in step]
        self.assertEqual(len(uploads), 1)
        upload = uploads[0]
        self.assertIn("if-no-files-found: error", upload)
        self.assertIn("name: release-candidate", upload)
        for artifact in (".tar.gz", ".manifest.json", ".sha256", ".changelog.md"):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, upload)
        self.assertIn("retention-days: 1", upload)

    def test_every_artifact_download_step_is_pinned(self) -> None:
        downloads = [step for step in self.steps if "uses: actions/download-artifact@" in step]
        self.assertEqual(len(downloads), 2)
        for step in downloads:
            with self.subTest(step=step.splitlines()[0]):
                self.assertRegex(step, r"uses: actions/download-artifact@[0-9a-f]{40}\b")
                self.assertIn("path: dist", step)
                self.assertIn("name: release-candidate", step)

    def test_artifact_hashes_are_compared_across_two_clean_builds(self) -> None:
        self.assertIn('cmp "/tmp/build1/$ARCHIVE" "/tmp/build2/$ARCHIVE"', self.workflow)
        self.assertIn('HASH1=$(sha256sum "/tmp/build1/$ARCHIVE" | awk \'{print $1}\')', self.workflow)
        self.assertIn('HASH2=$(sha256sum "/tmp/build2/$ARCHIVE" | awk \'{print $1}\')', self.workflow)
        self.assertIn("Release build is not reproducible", self.workflow)
        self.assertIn('if [ "$HASH1" != "$HASH2" ]', self.workflow)
        self.assertIn("--sha256-file", self.workflow)
        self.assertIn('(cd /tmp/build1 && sha256sum -c', self.workflow)

    def test_the_published_artifact_is_reverified_before_upload(self) -> None:
        publish = self.jobs["publish"]
        self.assertIn('(cd dist && sha256sum -c', publish)
        self.assertIn('verify_archive.py "$ARCHIVE" --manifest "$MANIFEST"', publish)
        self.assertIn("cmp /tmp/release-changelog.md", publish)
        self.assertIn("gh release upload", publish)
        for artifact in (".tar.gz", ".manifest.json", ".sha256", ".changelog.md"):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, publish)

    def test_the_manifest_binds_the_artifact_to_the_release_revision(self) -> None:
        build = self.jobs["build"]
        self.assertIn("REVISION: ${{ github.sha }}", build)
        self.assertIn('--revision "$REVISION"', build)
        self.assertIn("--output \"$MANIFEST\"", build)


if __name__ == "__main__":
    unittest.main()
