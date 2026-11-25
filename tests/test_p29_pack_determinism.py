"""Protocol 29 release archive reproducibility (CF-06)."""
from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_support as support  # noqa: E402

pack = support.pack


class Protocol29PackDeterminismTests(unittest.TestCase):
    def test_two_protocol29_builds_are_identical_and_within_limits(self) -> None:
        source = support.REPO_ROOT / "protocol-29"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = pack.build_archive(source, root / "first", "1.0.0")
            second = pack.build_archive(source, root / "second", "1.0.0")
            first_bytes = first.path.read_bytes()
            second_bytes = second.path.read_bytes()
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.sha256, hashlib.sha256(first_bytes).hexdigest())

        members, _, _ = pack.collect_members(source)
        directories = pack.directories_of(members)
        pack.check_limits(members, directories)
        with tarfile.open(fileobj=io.BytesIO(first_bytes), mode="r:gz") as archive:
            entries = archive.getmembers()
        names = [entry.name for entry in entries]
        self.assertEqual(names, sorted(names, key=lambda name: name.encode("utf-8")))
        self.assertTrue(all(entry.mtime == 0 for entry in entries))
        self.assertEqual(first.entries, len(entries))
        self.assertLessEqual(first.uncompressed_bytes, pack.MAX_TOTAL_BYTES)

    def test_repeated_builds_with_fixed_timestamps_have_identical_digests(self) -> None:
        """Issue #604: identical input and timestamps give one digest.

        The source tree is copied, every file is stamped with a fixed mtime,
        and the timestamps are changed again between the two builds. If the
        packer read them, the second archive would differ; both must match
        each other and the archive built from the untouched repository pack.
        """
        source = support.REPO_ROOT / "protocol-29"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            copied = root / "protocol-29"
            shutil.copytree(source, copied)
            files = sorted(path for path in copied.rglob("*") if path.is_file())
            for index, path in enumerate(files):
                os.utime(path, ns=(1_000_000_000 + index, 1_000_000_000 + index))
            first = pack.build_archive(copied, root / "first", "1.0.0")
            for index, path in enumerate(files):
                os.utime(path, ns=(2_000_000_000 + index, 2_000_000_000 + index))
            second = pack.build_archive(copied, root / "second", "1.0.0")
            reference = pack.build_archive(source, root / "reference", "1.0.0")
            first_bytes = first.path.read_bytes()
            second_bytes = second.path.read_bytes()
            reference_bytes = reference.path.read_bytes()

        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.sha256, reference.sha256)
        self.assertEqual(first_bytes, reference_bytes)

        # The gzip header carries neither a name nor a timestamp.
        header = first_bytes[:10]
        self.assertEqual(header[:2], b"\x1f\x8b")
        self.assertEqual(header[3] & 0x08, 0, "gzip FNAME flag must not be set")
        self.assertEqual(int.from_bytes(header[4:8], "little"), 0)

        with tarfile.open(fileobj=io.BytesIO(first_bytes), mode="r:gz") as archive:
            entries = archive.getmembers()
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(entry.mtime, 0, f"{entry.name} has a non-normalized mtime")
            self.assertEqual(entry.uid, 0)
            self.assertEqual(entry.gid, 0)
        names = [entry.name for entry in entries]
        self.assertEqual(
            [name.encode("utf-8") for name in names],
            sorted(name.encode("utf-8") for name in names),
            "archive members must be sorted in UTF-8 byte order",
        )
        self.assertEqual(len(names), len(set(names)))

    def test_unsorted_entries_do_not_match_the_canonical_archive(self) -> None:
        source = support.REPO_ROOT / "protocol-29"
        members, _, _ = pack.collect_members(source)
        directories = set(pack.directories_of(members))
        names = sorted(set(members) | directories, key=lambda name: name.encode("utf-8"))
        raw = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as stream:
            with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT, encoding="utf-8") as archive:
                for name in reversed(names):
                    if name in members:
                        data = members[name]
                        archive.addfile(
                            pack._tar_info(name, directory=False, size=len(data)), io.BytesIO(data)
                        )
                    else:
                        archive.addfile(pack._tar_info(name, directory=True))

        self.assertNotEqual(
            hashlib.sha256(raw.getvalue()).digest(),
            hashlib.sha256(pack.render_archive(members)).digest(),
        )


if __name__ == "__main__":
    unittest.main()
