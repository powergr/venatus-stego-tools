"""Tests for the Venatus companion scripts and the file signature data.

Run from the repository root:
    python -m unittest discover -s tests -v

Standard library only. The two numpy demos are skipped when numpy and Pillow are not installed.
Sample files are built in a temporary folder, so nothing is written into the repository.
"""
import bz2
import gzip
import hashlib
import importlib.util
import io
import json
import lzma
import os
import plistlib
import re
import sqlite3
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import wave
import zipfile
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
DB_PATH = os.path.join(ROOT, "data", "file-signatures.json")


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, SCRIPTS)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(SCRIPTS)
    return module


def run_script(name, *args, cwd):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, name), *args],
                          cwd=cwd, capture_output=True, text=True, timeout=120)


def png_chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def tiny_png():
    rows = b"".join(b"\x00" + bytes([x * 16 % 256, 0, 0]) * 4 for x in range(4))
    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))


def tiny_jpeg():
    """Not a viewable image, but it has the real marker structure: SOI, one segment, SOS, scan data, EOI."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sos = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"
    scan = b"\x12\x34\xff\x00\x56\x78"  # FF 00 is a stuffed byte, not a marker
    return b"\xff\xd8" + app0 + sos + scan + b"\xff\xd9"


class SignatureData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DB_PATH, encoding="utf-8") as f:
            cls.db = json.load(f)

    def test_ids_are_unique_and_slugs(self):
        ids = [e["id"] for e in self.db]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, r"^[a-z0-9_]+$")

    def test_every_entry_is_well_formed(self):
        for e in self.db:
            with self.subTest(id=e["id"]):
                self.assertTrue(e["name"] and e["notes"] and e["category"])
                self.assertIsInstance(e["mime"], str)  # empty when the format has no registered media type
                self.assertTrue(e["magic"])
                for m in e["magic"]:
                    self.assertIsInstance(m["offset"], int)
                    self.assertGreaterEqual(m["offset"], 0)
                    self.assertRegex(m["hex"], r"^([0-9A-F]{2})( [0-9A-F]{2})*$")
                if e["trailer"]:
                    self.assertRegex(e["trailer"], r"^([0-9A-F]{2})( [0-9A-F]{2})*$")

    def test_tested_flags_are_consistent(self):
        for e in self.db:
            with self.subTest(id=e["id"]):
                if e["tested"]:
                    self.assertTrue(e["extensions"] or e["id"].startswith("zlib_"))
                if e["trailer"] is None:
                    self.assertIsNone(e["trailerTested"])
                if e["trailerTested"]:
                    self.assertTrue(e["tested"])

    def test_no_two_entries_share_the_same_header(self):
        seen = {}
        for e in self.db:
            key = tuple((m["offset"], m["hex"]) for m in e["magic"])
            self.assertNotIn(key, seen, f"{e['id']} duplicates {seen.get(key)}")
            seen[key] = e["id"]


class SigscanIdentifiesRealFormats(unittest.TestCase):
    """Build real files with the standard library and check that sigscan names them at offset 0."""

    @classmethod
    def setUpClass(cls):
        cls.sigscan = load_module("sigscan")
        cls.db = cls.sigscan.load_signatures()

    def ids_at_start(self, data):
        return {h["id"] for h in self.sigscan.scan(data, self.db, min_bytes=2, start_only=True)}

    def assert_identified(self, data, expected_id):
        self.assertIn(expected_id, self.ids_at_start(data))

    def test_png(self):
        self.assert_identified(tiny_png(), "png")

    def test_jpeg(self):
        self.assert_identified(tiny_jpeg(), "jpeg")

    def test_gzip(self):
        self.assert_identified(gzip.compress(b"hello"), "gzip")

    def test_bzip2(self):
        self.assert_identified(bz2.compress(b"hello"), "bzip2")

    def test_xz(self):
        self.assert_identified(lzma.compress(b"hello", format=lzma.FORMAT_XZ), "xz")

    def test_zip_and_empty_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.txt", b"hello")
        self.assert_identified(buf.getvalue(), "zip")
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w"):
            pass
        self.assert_identified(empty.getvalue(), "zip_empty")

    def test_tar_uses_offset_257(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as t:
            info = tarfile.TarInfo("a.txt")
            info.size = 5
            t.addfile(info, io.BytesIO(b"hello"))
        self.assert_identified(buf.getvalue(), "tar")

    def test_sqlite(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db")
            con = sqlite3.connect(path)
            con.execute("create table t (a)")
            con.commit()
            con.close()
            with open(path, "rb") as f:
                self.assert_identified(f.read(), "sqlite")

    def test_wav_needs_both_checks(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 100)
        self.assert_identified(buf.getvalue(), "wav")
        # RIFF alone, with a different form type, must not be called WAV
        self.assertNotIn("wav", self.ids_at_start(b"RIFF\x24\x00\x00\x00AVI LIST"))

    def test_binary_plist(self):
        self.assert_identified(plistlib.dumps({"a": 1}, fmt=plistlib.FMT_BINARY), "bplist")

    def test_zlib_header_variants(self):
        data = b"hello hello hello hello" * 20
        self.assert_identified(zlib.compress(data, 9), "zlib_best")
        self.assert_identified(zlib.compress(data, 6), "zlib_default")
        self.assert_identified(zlib.compress(data, 3), "zlib_fast")
        self.assert_identified(zlib.compress(data, 1), "zlib_low")

    def test_small_hand_built_headers(self):
        self.assert_identified(b"%PDF-1.4\n%%EOF\n", "pdf")
        self.assert_identified(b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "gif89a")
        self.assert_identified(b"\x7fELF\x02\x01\x01" + b"\x00" * 9, "elf")

    def test_non_signature_text_is_not_identified(self):
        self.assertEqual(self.sigscan.scan(b"just some plain text\n" * 4, self.db, min_bytes=4, start_only=True), [])


class MysteryFile(unittest.TestCase):
    """make_mystery.py, sigscan.py, carve_demo.py and entropy_profile.py working together."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        result = run_script("make_mystery.py", cwd=cls.dir)
        assert result.returncode == 0, result.stderr
        cls.make_output = result.stdout
        cls.path = os.path.join(cls.dir, "mystery.bin")
        with open(cls.path, "rb") as f:
            cls.data = f.read()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def layout(self):
        """Parse the offset table printed by make_mystery.py, so tests never hard-code zlib-dependent sizes."""
        rows = {}
        for line in self.make_output.splitlines():
            m = re.match(r"^(.+?)\s{2,}(\d+)\s+0x[0-9a-f]+\s+(\d+)$", line)
            if m:
                # "padding" appears twice; keep the first one under its own name
                rows.setdefault(m.group(1).strip(), (int(m.group(2)), int(m.group(3))))
        return rows

    def test_layout_adds_up_to_the_file_size(self):
        total = 0
        count = 0
        for line in self.make_output.splitlines():
            m = re.match(r"^(.+?)\s{2,}(\d+)\s+0x[0-9a-f]+\s+(\d+)$", line)
            if m:
                total += int(m.group(3))
                count += 1
        self.assertEqual(count, 8)
        self.assertEqual(total, len(self.data))

    def test_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_script("make_mystery.py", cwd=d).returncode, 0)
            with open(os.path.join(d, "mystery.bin"), "rb") as f:
                again = f.read()
        self.assertEqual(hashlib.sha256(again).hexdigest(), hashlib.sha256(self.data).hexdigest())

    def test_sigscan_finds_each_embedded_file_at_its_real_offset(self):
        rows = self.layout()
        result = run_script("sigscan.py", self.path, "--min-bytes", "3", "--json", cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        hits = json.loads(result.stdout)
        by_id_offsets = {}
        for h in hits:
            by_id_offsets.setdefault(h["id"], set()).add(h["offset"])
        self.assertIn(rows["PNG image"][0], by_id_offsets["png"])
        self.assertIn(rows["gzip data"][0], by_id_offsets["gzip"])
        self.assertIn(rows["ZIP archive"][0], by_id_offsets["zip"])

    def test_sigscan_default_threshold_skips_three_byte_signatures(self):
        result = run_script("sigscan.py", self.path, "--json", cwd=self.dir)
        ids = {h["id"] for h in json.loads(result.stdout)}
        self.assertIn("png", ids)
        self.assertNotIn("gzip", ids)

    def test_carve_demo_validates_all_three_files(self):
        result = run_script("carve_demo.py", self.path, cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("IHDR checksum ok", result.stdout)
        self.assertIn("decompresses to", result.stdout)
        self.assertIn("integrity ok", result.stdout)
        rows = self.layout()
        carved = {name for name in os.listdir(self.dir) if name.startswith("carved_")}
        self.assertEqual(carved, {f"carved_{rows['PNG image'][0]}.png",
                                  f"carved_{rows['gzip data'][0]}.gz",
                                  f"carved_{rows['ZIP archive'][0]}.zip"})
        png_size = os.path.getsize(os.path.join(self.dir, f"carved_{rows['PNG image'][0]}.png"))
        self.assertEqual(png_size, rows["PNG image"][1])

    def test_entropy_profile_separates_text_padding_and_random(self):
        rows = self.layout()
        result = run_script("entropy_profile.py", self.path, "512", cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = {}
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            values[int(parts[0])] = float(parts[1])
        random_start = rows["random bytes"][0]
        random_block = ((random_start // 512) + 2) * 512  # a block fully inside the random region
        self.assertGreater(values[random_block], 7.5)
        # the first block is a text banner followed by the start of the PNG, so it sits well below random data
        self.assertLess(values[0], values[random_block] - 1.0)
        # the block that holds the 0xFF padding and the end of the gzip data is clearly structured
        self.assertLess(min(values.values()), 5.0)


class TrailingBytes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_clean_files_exit_zero(self):
        a = self.write("clean.jpg", tiny_jpeg())
        b = self.write("clean.png", tiny_png())
        result = run_script("trailing_bytes.py", a, b, cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(re.findall(r", clean$", result.stdout, re.M)), 2)

    def test_appended_data_is_reported_and_exit_code_is_one(self):
        secret = b"PK\x03\x04 hidden payload"
        a = self.write("tampered.jpg", tiny_jpeg() + secret)
        b = self.write("tampered.png", tiny_png() + secret)
        for path in (a, b):
            with self.subTest(path=os.path.basename(path)):
                result = run_script("trailing_bytes.py", path, cwd=self.dir)
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"{len(secret)} trailing bytes", result.stdout)

    def test_jpeg_end_ignores_a_fake_eoi_inside_a_segment(self):
        mod = load_module("trailing_bytes")
        data = tiny_jpeg()
        self.assertEqual(mod.jpeg_end(data), len(data))
        self.assertEqual(mod.jpeg_end(data + b"\xff\xd9" + b"x" * 10), len(data))

    def test_non_images_raise_a_clear_error(self):
        mod = load_module("trailing_bytes")
        with self.assertRaises(ValueError):
            mod.png_end(b"not a png at all")

    def test_evidence_log_records_hashes_and_offsets(self):
        secret = b"hidden payload"
        base = tiny_png()
        path = self.write("case.png", base + secret)
        result = run_script("evidence_log.py", path, cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn(hashlib.sha256(base + secret).hexdigest(), out)
        self.assertIn(hashlib.sha256(secret).hexdigest(), out)
        self.assertIn(f"byte offset {len(base)}", out)
        self.assertIn(f"trailing bytes:     {len(secret)}", out)


def have_numpy_and_pillow():
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(have_numpy_and_pillow(), "numpy and Pillow are not installed")
class NumpyDemos(unittest.TestCase):
    def test_recompress_demo_runs(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_script("recompress_demo.py", cwd=d)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())

    def test_toy_text_watermark_runs(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_script("toy_text_watermark.py", cwd=d)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
