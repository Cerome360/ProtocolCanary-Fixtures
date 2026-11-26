"""docs/upstream-matrix.md must agree with upstream-matrix.json (F-024).

The page is prose for people and the JSON file is data for tooling; both state
which upstream release belongs to which protocol. Nothing else keeps them
consistent, so these tests parse the page's tables and check every release and
commit against the matrix, and check that the page names the passphrases and
links that the issue requires.

Stdlib only. Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "upstream-matrix.md"
README_PATH = REPO_ROOT / "README.md"
MATRIX_PATH = REPO_ROOT / "upstream-matrix.json"
MATRIX_SCHEMA_PATH = REPO_ROOT / "schemas" / "upstream-matrix.json"

# Issue #624 calls this file's counterpart `catalogue/index.json` and asks for
# Active/Candidate/Deprecated status properties. Neither exists in this
# repository: `upstream-matrix.json` is the protocol catalogue and the schema
# has no status property. The docs record release state by which network
# sections exist, so the three statuses are derived from that evidence rather
# than invented as new fields.
STATUS_RULES = ("Active", "Candidate", "Deprecated")

PASSPHRASES = {
    "Testnet": "Test SDF Network ; September 2015",
    "Futurenet": "Test SDF Future Network ; October 2022",
    "Mainnet": "Public Global Stellar Network ; September 2015",
}

# Table row: | Component | `release` | [`short`](https://github.com/o/r/commit/<sha>) |
ROW = re.compile(
    r"^\| (?P<component>[^|]+?) \| `v?(?P<version>[0-9]+\.[0-9]+\.[0-9]+)` \| "
    r"\[`(?P<short>[0-9a-f]{8})`\]\(https://github\.com/(?P<repo>[^/]+/[^/]+)/commit/"
    r"(?P<sha>[0-9a-f]{40})\) \|$"
)
COMPONENT_NAMES = {
    "Stellar Core": "stellar-core",
    "Stellar RPC (`soroban-rpc`)": "soroban-rpc",
    "Soroban host environment (`rs-soroban-env`)": "rs-soroban-env",
}
HORIZON = "Stellar Horizon"
HORIZON_REPOSITORY = "stellar/stellar-horizon"


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def parse_sections(text: str) -> dict[tuple[str, str], list[dict]]:
    """Rows keyed by (protocol, network) from the `## Protocol N` / `### Network`
    headings."""
    sections: dict[tuple[str, str], list[dict]] = {}
    protocol = network = None
    for line in text.split("\n"):
        heading = re.match(r"^## Protocol ([0-9]+)$", line)
        if heading:
            protocol, network = heading.group(1), None
            continue
        if line.startswith("## "):
            protocol = network = None
            continue
        sub = re.match(r"^### (Testnet|Mainnet)$", line)
        if sub and protocol:
            network = sub.group(1)
            continue
        row = ROW.match(line)
        if row and protocol and network:
            sections.setdefault((protocol, network), []).append(row.groupdict())
    return sections


def release_status(sections: dict[tuple[str, str], list[dict]], protocol: str) -> str:
    """The documented release status for a protocol.

    Mainnet coverage means Active, Testnet-only coverage means Candidate, and
    no network section means Deprecated. This mirrors the page's own wording:
    Protocol 28 and 29 are released to both networks, while Protocol 30 says
    explicitly that Mainnet is not listed and no activation is claimed.
    """
    if sections.get((protocol, "Mainnet")):
        return "Active"
    if sections.get((protocol, "Testnet")):
        return "Candidate"
    return "Deprecated"


def markdown_table_blocks(text: str) -> list[list[str]]:
    """Contiguous runs of lines beginning with a pipe."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.startswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def satisfies(version: str, comparators: str) -> bool:
    """Whether MAJOR.MINOR.PATCH ``version`` meets every comparator in the range."""
    have = tuple(int(part) for part in version.split("."))
    for comparator in comparators.split(" "):
        match = re.fullmatch(r"(>=|<=|>|<|=)?([0-9]+\.[0-9]+\.[0-9]+)", comparator)
        assert match, comparator
        op = match.group(1) or "="
        want = tuple(int(part) for part in match.group(2).split("."))
        ok = {
            ">=": have >= want,
            "<=": have <= want,
            ">": have > want,
            "<": have < want,
            "=": have == want,
        }[op]
        if not ok:
            return False
    return True


class RangeHelperTests(unittest.TestCase):
    def test_satisfies(self) -> None:
        self.assertTrue(satisfies("28.0.1", ">=28.0.0 <29.0.0"))
        self.assertTrue(satisfies("28.0.0", ">=28.0.0 <29.0.0"))
        self.assertFalse(satisfies("29.0.0", ">=28.0.0 <29.0.0"))
        self.assertFalse(satisfies("27.9.9", ">=28.0.0 <29.0.0"))
        self.assertTrue(satisfies("28.0.0", "28.0.0"))
        self.assertFalse(satisfies("28.0.1", "=28.0.0"))
        self.assertTrue(satisfies("28.10.0", ">28.9.9"))


class UpstreamMatrixDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = read_doc()
        cls.sections = parse_sections(cls.text)
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    def test_the_page_documents_protocols_28_29_and_30(self) -> None:
        self.assertEqual(
            set(self.sections),
            {("28", "Testnet"), ("28", "Mainnet"), ("29", "Testnet"), ("29", "Mainnet"), ("30", "Testnet")},
        )

    def test_every_section_lists_core_rpc_horizon_and_the_host_environment(self) -> None:
        expected = set(COMPONENT_NAMES) | {HORIZON}
        for key, rows in self.sections.items():
            self.assertEqual({r["component"] for r in rows}, expected, key)

    def test_every_release_is_inside_the_range_the_matrix_records(self) -> None:
        for (protocol, network), rows in self.sections.items():
            for row in rows:
                name = COMPONENT_NAMES.get(row["component"])
                if name is None:
                    continue  # Horizon is not in the matrix; checked below
                recorded = self.matrix["protocols"][protocol][name]["range"]
                self.assertTrue(
                    satisfies(row["version"], recorded),
                    f"{protocol}/{network}/{name}: {row['version']} is outside {recorded}",
                )

    def test_each_commit_link_names_the_matrix_repository(self) -> None:
        for (protocol, network), rows in self.sections.items():
            for row in rows:
                name = COMPONENT_NAMES.get(row["component"])
                expected = (
                    self.matrix["protocols"][protocol][name]["repository"]
                    if name
                    else HORIZON_REPOSITORY
                )
                self.assertEqual(row["repo"], expected, f"{protocol}/{network}/{row['component']}")

    def test_the_short_commit_is_the_start_of_the_full_commit(self) -> None:
        for rows in self.sections.values():
            for row in rows:
                self.assertEqual(row["sha"][:8], row["short"], row["component"])

    def test_horizon_tracks_the_protocol_major_version(self) -> None:
        for (protocol, network), rows in self.sections.items():
            horizon = next(r for r in rows if r["component"] == HORIZON)
            self.assertEqual(horizon["version"].split(".")[0], protocol, network)

    def test_mainnet_is_never_older_than_testnet_for_a_protocol(self) -> None:
        def parse(version: str) -> tuple[int, ...]:
            return tuple(int(p) for p in version.split("."))

        for protocol in ("28", "29"):
            testnet = {r["component"]: r["version"] for r in self.sections[(protocol, "Testnet")]}
            mainnet = {r["component"]: r["version"] for r in self.sections[(protocol, "Mainnet")]}
            for component, version in testnet.items():
                self.assertGreaterEqual(parse(mainnet[component]), parse(version), component)

    def test_the_network_passphrases_are_documented_exactly(self) -> None:
        for network, passphrase in PASSPHRASES.items():
            self.assertIn(f"| {network} | `{passphrase}` |", self.text)

    def test_the_source_page_is_linked_and_dated(self) -> None:
        self.assertIn("https://developers.stellar.org/docs/networks/software-versions", self.text)
        self.assertIn(self.matrix["source"], self.text)
        self.assertIn(self.matrix["checkedOn"], self.text)

    def test_the_machine_readable_matrix_is_linked(self) -> None:
        self.assertIn("(../upstream-matrix.json)", self.text)
        self.assertIn("(../schemas/upstream-matrix.json)", self.text)

    def test_relative_links_resolve_to_files(self) -> None:
        for target in re.findall(r"\]\((?!https?://|#)([^)#]+)(?:#[^)]*)?\)", self.text):
            path = (DOC_PATH.parent / target).resolve()
            self.assertTrue(path.exists(), f"{target} -> {path}")

    def test_the_readme_links_the_page(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn("(docs/upstream-matrix.md)", readme)
        self.assertIn("(upstream-matrix.json)", readme)


class CatalogueSynchronizationTests(unittest.TestCase):
    """The docs, catalogue and schema must name the same protocols (issue #624)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = read_doc()
        cls.sections = parse_sections(cls.text)
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(MATRIX_SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_the_catalogued_protocols_match_the_schema_and_the_page(self) -> None:
        catalogue = set(self.matrix["protocols"])
        schema_required = set(self.schema["properties"]["protocols"]["required"])
        documented = {protocol for protocol, _ in self.sections}
        self.assertEqual(catalogue, schema_required)
        self.assertEqual(catalogue, documented)

    def test_release_statuses_are_derived_from_documented_network_evidence(self) -> None:
        statuses = {
            protocol: release_status(self.sections, protocol)
            for protocol in self.matrix["protocols"]
        }
        self.assertEqual(
            statuses,
            {"28": "Active", "29": "Active", "30": "Candidate"},
        )
        self.assertEqual(set(statuses.values()), {"Active", "Candidate"})
        self.assertEqual(set(STATUS_RULES) - set(statuses.values()), {"Deprecated"})

    def test_every_status_protocol_has_a_catalogue_and_schema_section(self) -> None:
        schema_required = set(self.schema["properties"]["protocols"]["required"])
        for protocol in self.matrix["protocols"]:
            status = release_status(self.sections, protocol)
            self.assertIn(status, STATUS_RULES)
            self.assertIn(protocol, schema_required)
            self.assertIn(protocol, self.matrix["protocols"])

    def test_every_release_row_is_parsed_by_the_strict_pattern(self) -> None:
        parsed = [
            match
            for line in self.text.split("\n")
            if (match := ROW.match(line)) is not None
        ]
        self.assertEqual(len(parsed), sum(len(rows) for rows in self.sections.values()))
        self.assertEqual(len(parsed), 20)

    def test_every_markdown_table_has_a_header_separator_and_fixed_columns(self) -> None:
        blocks = markdown_table_blocks(self.text)
        self.assertTrue(blocks)
        for block in blocks:
            with self.subTest(header=block[0]):
                self.assertGreaterEqual(len(block), 2)
                columns = block[0].count("|")
                self.assertGreaterEqual(columns, 2)
                self.assertEqual(block[1], "|" + "---|" * (columns - 1))
                for line in block:
                    self.assertTrue(line.startswith("|"), line)
                    self.assertEqual(line.count("|"), columns, line)
                    self.assertEqual(line, line.rstrip(), "trailing whitespace")
                    self.assertNotIn("\t", line)

    def test_release_tables_use_the_documented_column_headings(self) -> None:
        release_tables = [
            block
            for block in markdown_table_blocks(self.text)
            if block[0] == "| Component | Release | Commit |"
        ]
        self.assertEqual(len(release_tables), 5)
        for block in release_tables:
            self.assertEqual(block[1], "|---|---|---|")
            self.assertTrue(all(ROW.match(line) for line in block[2:]), block)


if __name__ == "__main__":
    unittest.main()
