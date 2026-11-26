"""docs/tools.md names only repository paths that exist (issue #451, F-132).

The document is the reference for the command-line tools. Every
repository-relative path written in backticks with one of the pack or tool
prefixes has to resolve to a file or directory, so a renamed schema cannot
leave a stale name behind.

Run with: python3 -m unittest tests.test_tools_doc_paths
"""
from __future__ import annotations

import os
import re
import stat
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DOC = REPO_ROOT / "docs" / "tools.md"
EXPECTED_SHEBANG = "#!/usr/bin/env python3"

# A repository path anywhere in a line, not only one that starts a backtick
# span. This covers the table of tools and prose references, and also paths
# embedded after an interpreter in a command such as
# `python3 tools/registry/check_all.py protocol-28` or in a fenced synopsis.
# `scripts/` is included because issue text and older documentation use it,
# even though the current tools live under `tools/`.
_PATH_PATTERN = re.compile(
    r"(?<![\w./-])((?:tools|scripts|tests|schemas|docs|protocol-\d+|\.github)/"
    r"[A-Za-z0-9_./<>*-]*)"
)
_PLACEHOLDER_CHARS = ("<", ">", "*")
_TRAILING_PUNCTUATION = ".,;:"


def documented_paths(text: str) -> list[tuple[int, str]]:
    """Return ``(line number, path)`` for every checkable path in ``text``."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _PATH_PATTERN.finditer(line):
            path = match.group(1).rstrip(_TRAILING_PUNCTUATION)
            if not path or any(char in path for char in _PLACEHOLDER_CHARS):
                continue
            found.append((number, path))
    return found


def documented_python_scripts(text: str) -> list[str]:
    """The distinct ``.py`` paths docs/tools.md references."""
    return sorted(
        {path for _, path in documented_paths(text) if path.endswith(".py")}
    )


class ToolsDocPathTests(unittest.TestCase):
    def test_every_documented_repository_path_exists(self) -> None:
        paths = documented_paths(TOOLS_DOC.read_text(encoding="utf-8"))
        self.assertGreater(len(paths), 0, "the scan found no paths; the pattern is broken")
        missing = [
            f"docs/tools.md:{number}: `{path}`"
            for number, path in paths
            if not (REPO_ROOT / path).exists()
        ]
        self.assertEqual(missing, [], "paths named in docs/tools.md that do not exist")


class DocumentedScriptTests(unittest.TestCase):
    """Every referenced Python tool exists and follows the script conventions."""

    def setUp(self) -> None:
        self.text = TOOLS_DOC.read_text(encoding="utf-8")
        self.scripts = documented_python_scripts(self.text)

    def test_the_document_references_python_tools(self) -> None:
        self.assertGreater(len(self.scripts), 0)

    def test_the_scan_covers_tool_paths_embedded_in_commands(self) -> None:
        # check_all.py is named only inside a command span, not in the table
        # of tools; the old start-of-span pattern missed it.
        self.assertIn("tools/registry/check_all.py", self.scripts)
        self.assertIn("tools/validate/validate_registry.py", self.scripts)

    def test_every_referenced_script_is_a_regular_readable_file(self) -> None:
        for script in self.scripts:
            with self.subTest(script=script):
                path = REPO_ROOT / script
                self.assertTrue(path.is_file(), path)
                self.assertTrue(os.access(path, os.R_OK), path)

    def test_every_referenced_script_declares_the_python_shebang(self) -> None:
        for script in self.scripts:
            with self.subTest(script=script):
                first_line = (REPO_ROOT / script).read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(first_line, EXPECTED_SHEBANG)

    @unittest.skipIf(
        os.name != "posix",
        "Windows does not expose meaningful POSIX write bits through stat()",
    )
    def test_referenced_scripts_are_not_world_writable(self) -> None:
        for script in self.scripts:
            with self.subTest(script=script):
                mode = (REPO_ROOT / script).stat().st_mode
                self.assertFalse(mode & stat.S_IWOTH, f"{script} is world-writable")

    def test_an_executable_script_has_a_usable_shebang(self) -> None:
        for script in self.scripts:
            path = REPO_ROOT / script
            if not os.access(path, os.X_OK):
                continue
            with self.subTest(script=script):
                first_line = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(first_line, EXPECTED_SHEBANG)


class DocumentedPathsHelperTests(unittest.TestCase):
    def test_reports_the_line_of_every_path(self) -> None:
        text = "intro\nsee `tools/a.py` and `schemas/b.json`\n\n`tests/c.py`\n"
        self.assertEqual(
            documented_paths(text),
            [(2, "tools/a.py"), (2, "schemas/b.json"), (4, "tests/c.py")],
        )

    def test_skips_placeholders_and_globs(self) -> None:
        text = "`tools/<name>.py` `schemas/*.json` `docs/x>y` `tools/ok.py`"
        self.assertEqual(documented_paths(text), [(1, "tools/ok.py")])

    def test_finds_paths_embedded_in_a_command(self) -> None:
        text = "Run `python3 tools/registry/check_all.py protocol-28 task`; `scripts/old.py`"
        self.assertEqual(
            documented_paths(text),
            [
                (1, "tools/registry/check_all.py"),
                (1, "scripts/old.py"),
            ],
        )

    def test_finds_paths_in_a_fenced_synopsis(self) -> None:
        text = "```bash\npython3 tools/pack/pack.py PACK --version 1.0.0\n```"
        self.assertEqual(documented_paths(text), [(2, "tools/pack/pack.py")])

    def test_strips_sentence_punctuation_from_a_path(self) -> None:
        text = "See `tools/pack/pack.py`."
        self.assertEqual(documented_paths(text), [(1, "tools/pack/pack.py")])

    def test_ignores_tokens_outside_the_known_prefixes(self) -> None:
        text = "`README.md` `protocol-NN/` `src/x.py` `--flag` `toolsx/y`"
        self.assertEqual(documented_paths(text), [])

    def test_a_missing_path_is_named_with_its_line(self) -> None:
        text = "a\n`schemas/manifest-v1.schema.json`\n"
        self.assertEqual(
            [(n, p) for n, p in documented_paths(text) if not (REPO_ROOT / p).exists()],
            [(2, "schemas/manifest-v1.schema.json")],
        )


if __name__ == "__main__":
    unittest.main()
