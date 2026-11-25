"""Documentation must name exactly the vocabulary the validator accepts.

Issue #162 was a real three-way drift: README.md documented the `field-absent`
RPC assert kind while `schemas/fixture-v1.schema.json`'s enum and
`validate.py`'s `RPC_ASSERT_KINDS` both omitted it. The schema/validator leg is
now checked by `tools/validate/schema_sync.py` (run from
`tests/test_validate.py`'s `SchemaSyncTests`), but nothing compared the human
documentation -- README.md's assertion-vocabulary table and CONTRIBUTING.md's
per-surface field table -- against those same lists. These tests close that
last leg; with both checks in place the three artifacts are pinned together.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"
README_PATH = REPO_ROOT / "README.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"

_spec = importlib.util.spec_from_file_location("validate_vocabulary", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate_vocabulary"] = validate
_spec.loader.exec_module(validate)


def markdown_rows(path: Path, anchor: str, columns: int) -> list[list[str]]:
    """Rows of the markdown table following `anchor`, which must have `columns` cells.

    Parsing stops at the next heading so a table elsewhere in the same file,
    with a different shape, cannot be picked up by mistake.
    """
    text = path.read_text(encoding="utf-8")
    body = text[text.index(anchor) + len(anchor) :]
    next_heading = re.search(r"^#{1,4} ", body, re.MULTILINE)
    if next_heading:
        body = body[: next_heading.start()]
    rows = []
    fenced = False
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            # Fenced examples may document a table shape, or show a vocabulary
            # value the validator rejects. Neither is a row of the real table.
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("|") and not re.fullmatch(r"[|\s:-]+", line):
            # Split on unescaped pipes only: CONTRIBUTING.md separates
            # vocabulary values inside one cell with a literal `\|`.
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))]
            if len(cells) == columns:
                rows.append(cells)
    assert len(rows) > 1, f"no table with {columns} columns found after {anchor!r}"
    return rows[1:]  # drop the header row


def readme_vocabulary() -> dict[tuple[str, str], set[str]]:
    """README's assertion-vocabulary table, keyed by (surface, field)."""
    table: dict[tuple[str, str], set[str]] = {}
    for surface, field, value, _assertion in markdown_rows(
        README_PATH, "### Assertion vocabulary", 4
    ):
        key = (surface.strip("`"), field.strip("`"))
        table.setdefault(key, set()).add(value.strip("`"))
    return table


def contributing_rpc_methods() -> set[str]:
    """Method names from CONTRIBUTING.md's per-surface field table."""
    for surface, fields in markdown_rows(CONTRIBUTING_PATH, "Per-surface body", 2):
        if surface.strip("`") == "rpc":
            return set(re.findall(r'"([a-z0-9][a-z0-9-]*)"', fields))
    raise AssertionError("no `rpc` row in CONTRIBUTING.md's per-surface table")


class TestDocumentationMatchesVocabulary(unittest.TestCase):
    def test_readme_table_names_exactly_the_rpc_assert_kinds(self) -> None:
        documented = readme_vocabulary()[("rpc", "[[assert]].kind")]
        self.assertEqual(documented, validate.RPC_ASSERT_KINDS)

    def test_readme_table_names_exactly_the_xdr_kinds(self) -> None:
        self.assertEqual(readme_vocabulary()[("xdr", "kind")], validate.XDR_KINDS)

    def test_readme_table_names_exactly_the_soroban_expect_kinds(self) -> None:
        self.assertEqual(
            readme_vocabulary()[("soroban", "[expect].kind")],
            validate.SOROBAN_EXPECT_KINDS,
        )

    def test_contributing_names_exactly_the_rpc_methods(self) -> None:
        self.assertEqual(contributing_rpc_methods(), validate.RPC_METHODS)

    def test_readme_table_has_no_row_for_an_unsupported_surface(self) -> None:
        # A row for a surface the validator rejects would document something no
        # fixture can use, and would silently widen the table's keys.
        surfaces = {surface for surface, _field in readme_vocabulary()}
        self.assertEqual(surfaces, validate.SURFACES)


class TestVocabularyParserSkipsCode(unittest.TestCase):
    """Only prose belongs to the vocabulary tables; code samples never do.

    A fenced block can legitimately contain a table-shaped line, and inline
    backticks are how the prose spells a vocabulary value. Neither may add a
    surface, a field or a value that the validator does not accept, and neither
    may hide a real prose violation.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "doc.md"

    def write(self, body: str) -> None:
        self.path.write_text("### Assertion vocabulary\n\n" + body, encoding="utf-8")

    def test_rows_inside_fenced_blocks_are_ignored(self) -> None:
        self.write(
            "| surface | field | value | assertion |\n"
            "| --- | --- | --- | --- |\n"
            "| `rpc` | `[[assert]].kind` | `field-absent` | flagged in prose |\n"
            "\n"
            "```toml\n"
            "| rpc | [[assert]].kind | retired-kind | not part of the table |\n"
            "```\n"
            "\n"
            "~~~text\n"
            "| rpc | [[assert]].kind | also-retired | still not a row |\n"
            "~~~\n"
            "\n"
            "| `rpc` | `[[assert]].kind` | `field-present` | flagged in prose |\n"
        )
        rows = markdown_rows(self.path, "### Assertion vocabulary", 4)
        self.assertEqual(
            [(row[0], row[2]) for row in rows],
            [("`rpc`", "`field-absent`"), ("`rpc`", "`field-present`")],
        )

    def test_backticked_terms_are_reported_without_backticks(self) -> None:
        self.write(
            "| surface | field | value | assertion |\n"
            "| --- | --- | --- | --- |\n"
            "| `rpc` | `[[assert]].kind` | `field-absent` | prose only |\n"
        )
        row = markdown_rows(self.path, "### Assertion vocabulary", 4)[0]
        self.assertEqual(row[0].strip("`"), "rpc")
        self.assertEqual(row[1].strip("`"), "[[assert]].kind")
        self.assertEqual(row[2].strip("`"), "field-absent")

    def test_escaped_pipe_stays_inside_its_cell(self) -> None:
        self.write(
            '| surface | fields |\n'
            '| --- | --- |\n'
            '| `rpc` | "get-ledger" \\| "get-network" |\n'
        )
        row = markdown_rows(self.path, "### Assertion vocabulary", 2)[0]
        self.assertEqual(row[1], '"get-ledger" \\| "get-network"')
        self.assertEqual(
            re.findall(r'"([a-z0-9][a-z0-9-]*)"', row[1]),
            ["get-ledger", "get-network"],
        )

    def test_prose_violation_after_a_fence_is_still_parsed(self) -> None:
        self.write(
            "```bash\n"
            "python3 tools/validate/validate.py\n"
            "```\n"
            "\n"
            "| surface | field | value | assertion |\n"
            "| --- | --- | --- | --- |\n"
            "| `rpc` | `[[assert]].kind` | `not-a-real-kind` | bad prose value |\n"
        )
        rows = markdown_rows(self.path, "### Assertion vocabulary", 4)
        self.assertEqual([row[2].strip("`") for row in rows], ["not-a-real-kind"])


if __name__ == "__main__":
    unittest.main()
