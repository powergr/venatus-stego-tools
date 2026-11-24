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


SOS = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"


class JpegAndPngEdgeCases(unittest.TestCase):
    """Damaged and unusual files. Each must give a clear ValueError or the right answer, never a crash."""

    @classmethod
    def setUpClass(cls):
        cls.tb = load_module("trailing_bytes")

    def test_jpeg_ending_in_fill_bytes(self):
        for data in (b"\xff\xd8\xff\xff", b"\xff\xd8\xff\xff\xff\xff"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.tb.jpeg_end(data)

    def test_jpeg_cut_off_inside_a_segment_header(self):
        for data in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe0\x00"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.tb.jpeg_end(data)

    def test_jpeg_segment_length_must_be_at_least_two(self):
        for length in (0, 1):
            data = b"\xff\xd8\xff\xe0" + struct.pack(">H", length) + b"\xff\xd9"
            with self.subTest(length=length), self.assertRaisesRegex(ValueError, "invalid segment length"):
                self.tb.jpeg_end(data)

    def test_jpeg_fill_bytes_before_a_restart_marker(self):
        for fill in (b"\xff", b"\xff\xff\xff"):
            data = b"\xff\xd8" + SOS + b"\x12" + fill + b"\xff\xd0\x34\x56\xff\xd9"
            with self.subTest(fill_bytes=len(fill)):
                self.assertEqual(self.tb.jpeg_end(data), len(data))

    def test_jpeg_fill_bytes_before_the_end_marker(self):
        data = b"\xff\xd8" + SOS + b"\x12\x34\xff\xff\xff\xd9"
        self.assertEqual(self.tb.jpeg_end(data), len(data))

    def test_jpeg_data_after_the_end_marker_is_not_counted(self):
        data = b"\xff\xd8" + SOS + b"\x12\xff\xff\xd0\x56\xff\xd9"
        self.assertEqual(self.tb.jpeg_end(data + b"trailing"), len(data))

    def test_png_with_a_cut_off_iend_chunk(self):
        png = tiny_png()
        for data in (png[:-1], png[:-4]):  # the checksum is cut short
            with self.subTest(cut=len(png) - len(data)), self.assertRaisesRegex(ValueError, "truncated"):
                self.tb.png_end(data)
        with self.assertRaises(ValueError):  # almost the whole chunk is gone, so no IEND header is left to read
            self.tb.png_end(png[:-11])

    def test_png_with_an_oversized_chunk_length(self):
        png = tiny_png()
        bogus = png[:-12] + struct.pack(">I", 99999) + b"IEND" + b"\x00" * 4
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.tb.png_end(bogus)

    def test_png_without_an_iend_chunk(self):
        with self.assertRaisesRegex(ValueError, "no IEND"):
            self.tb.png_end(tiny_png()[:-12])


class CommandLineBehaviour(unittest.TestCase):
    """Missing arguments and bad input give a short message and a non-zero exit code, not a traceback."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.junk = os.path.join(cls.dir, "notes.txt")
        with open(cls.junk, "wb") as f:
            f.write(b"this is not an image\n" * 5)
        cls.cut_png = os.path.join(cls.dir, "cut.png")
        with open(cls.cut_png, "wb") as f:
            f.write(tiny_png()[:-2])
        cls.tampered = os.path.join(cls.dir, "tampered.png")
        with open(cls.tampered, "wb") as f:
            f.write(tiny_png() + b"extra")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assert_clean_failure(self, result, code=2):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(result.stderr.strip())

    def test_every_script_explains_itself_when_given_no_arguments(self):
        for script in ("trailing_bytes.py", "evidence_log.py", "carve_demo.py", "entropy_profile.py"):
            with self.subTest(script=script):
                result = run_script(script, cwd=self.dir)
                self.assert_clean_failure(result)
                self.assertIn("usage", result.stderr)

    def test_trailing_bytes_rejects_non_images(self):
        self.assert_clean_failure(run_script("trailing_bytes.py", self.junk, cwd=self.dir))

    def test_trailing_bytes_reports_a_cut_off_png_without_a_negative_count(self):
        result = run_script("trailing_bytes.py", self.cut_png, cwd=self.dir)
        self.assert_clean_failure(result)
        self.assertNotIn("-", result.stdout)

    def test_trailing_bytes_exit_code_one_wins_over_a_bad_file(self):
        result = run_script("trailing_bytes.py", self.junk, self.tampered, cwd=self.dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("5 trailing bytes", result.stdout)
        self.assertIn("cannot analyze", result.stderr)

    def test_trailing_bytes_reports_a_missing_file(self):
        result = run_script("trailing_bytes.py", os.path.join(self.dir, "missing.jpg"), cwd=self.dir)
        self.assert_clean_failure(result)

    def test_evidence_log_rejects_non_images(self):
        self.assert_clean_failure(run_script("evidence_log.py", self.junk, cwd=self.dir))

    def test_entropy_profile_rejects_bad_block_sizes(self):
        for size in ("0", "-5", "abc"):
            with self.subTest(block_size=size):
                self.assert_clean_failure(run_script("entropy_profile.py", self.junk, size, cwd=self.dir))

    def test_entropy_of_identical_bytes_prints_as_zero_not_negative_zero(self):
        path = os.path.join(self.dir, "padding.bin")
        with open(path, "wb") as f:
            f.write(b"\x00" * 1024 + b"\xff" * 1024)
        result = run_script("entropy_profile.py", path, "512", cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("-0.00", result.stdout)
        self.assertEqual(len(re.findall(r"\s0\.00\s", result.stdout)), 4)


class CarveDemoFalsePositives(unittest.TestCase):
    """carve_demo must skip chance matches and damaged files, and still find the real ones."""

    @classmethod
    def setUpClass(cls):
        cls.real_gzip = gzip.compress(b"setting=1\n" * 30, mtime=0)

    def carve(self, blob):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "blob.bin")
            with open(path, "wb") as f:
                f.write(blob)
            result = run_script("carve_demo.py", path, cwd=d)
            carved = {}
            for name in os.listdir(d):
                if name.startswith("carved_"):
                    with open(os.path.join(d, name), "rb") as f:
                        carved[name] = f.read()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result, carved

    def test_a_chance_gzip_header_before_the_real_stream(self):
        decoy = b"\x1f\x8b\x08\x00\xde\xad\xbe\xef" + b"\x00" * 30
        blob = b"\x00" * 50 + decoy + b"\xff" * 20 + self.real_gzip + b"tail"
        _, carved = self.carve(blob)
        self.assertEqual(list(carved.values()), [self.real_gzip])
        self.assertEqual(list(carved)[0], f"carved_{blob.index(self.real_gzip)}.gz")

    def test_a_truncated_gzip_stream_is_skipped(self):
        result, carved = self.carve(b"\x00" * 20 + self.real_gzip[:-6])
        self.assertEqual(carved, {})
        self.assertIn("no valid embedded files found", result.stdout)

    def test_a_truncated_png_is_skipped(self):
        result, carved = self.carve(b"\x00" * 20 + tiny_png()[:-5])
        self.assertEqual(carved, {})
        self.assertIn("no valid embedded files found", result.stdout)

    def test_a_png_with_an_oversized_chunk_is_skipped(self):
        png = tiny_png()
        bogus = png[:-12] + struct.pack(">I", 99999) + b"IEND" + b"\x00" * 4
        _, carved = self.carve(b"\x00" * 20 + bogus)
        self.assertEqual(carved, {})

    def test_a_valid_gzip_stream_inside_a_png_is_not_carved_separately(self):
        png = (b"\x89PNG\r\n\x1a\n"
               + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
               + png_chunk(b"tEXt", b"k\x00" + self.real_gzip)
               + png_chunk(b"IEND", b""))
        _, carved = self.carve(b"\x00" * 10 + png)
        self.assertEqual(list(carved), ["carved_10.png"])
        self.assertEqual(carved["carved_10.png"], png)

    def test_a_zip_end_record_that_appears_inside_stored_data(self):
        fake_end_record = b"PK\x05\x06" + b"\x00" * 18
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("a.bin", b"A" * 50 + fake_end_record + b"B" * 50)
            z.writestr("b.txt", b"second entry")
        real_zip = buf.getvalue()
        result, carved = self.carve(b"\x00" * 40 + real_zip + b"\x00" * 40)
        self.assertEqual(list(carved), ["carved_40.zip"])
        self.assertEqual(carved["carved_40.zip"], real_zip)
        self.assertIn("integrity ok", result.stdout)

    def test_the_second_zip_entry_is_not_reported_as_a_second_archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.txt", b"one")
            z.writestr("b.txt", b"two")
        _, carved = self.carve(buf.getvalue())
        self.assertEqual(len(carved), 1)


class SigscanStartOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sigscan = load_module("sigscan")
        cls.db = cls.sigscan.load_signatures()

    def samples(self):
        tar = io.BytesIO()
        with tarfile.open(fileobj=tar, mode="w", format=tarfile.USTAR_FORMAT) as t:
            info = tarfile.TarInfo("a.txt")
            info.size = 5
            t.addfile(info, io.BytesIO(b"hello"))
        mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41"
        return {"png": tiny_png(), "tar": tar.getvalue(), "mp4": mp4, "gzip": gzip.compress(b"x" * 100)}

    def test_start_only_equals_a_full_scan_filtered_to_offset_zero(self):
        for name, data in self.samples().items():
            with self.subTest(sample=name):
                full = sorted(h["id"] for h in self.sigscan.scan(data, self.db, min_bytes=2) if h["offset"] == 0)
                quick = sorted(h["id"] for h in self.sigscan.scan(data, self.db, min_bytes=2, start_only=True))
                self.assertEqual(full, quick)
                self.assertIn(name, quick)

    def test_start_only_works_for_signatures_that_do_not_begin_at_offset_zero(self):
        data = self.samples()
        for name in ("tar", "mp4"):
            with self.subTest(sample=name):
                ids = [h["id"] for h in self.sigscan.scan(data[name], self.db, min_bytes=2, start_only=True)]
                self.assertIn(name, ids)

    def test_start_only_ignores_a_signature_that_appears_later_in_the_file(self):
        data = b"plain text first\n" + tiny_png()
        self.assertNotIn("png", [h["id"] for h in self.sigscan.scan(data, self.db, min_bytes=2, start_only=True)])
        self.assertIn("png", [h["id"] for h in self.sigscan.scan(data, self.db, min_bytes=2)])

    def test_json_output_warns_on_stderr_when_hits_are_cut_off(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "many.bin")
            with open(path, "wb") as f:
                f.write(b"PK\x03\x04" * 300)
            result = run_script("sigscan.py", path, "--json", "--limit", "5", cwd=d)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 5)
        self.assertIn("more hits not shown", result.stderr)


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
