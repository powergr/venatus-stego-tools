#!/usr/bin/env python3
"""Build mystery.bin: a small, reproducible 'firmware-like' blob for practicing with binwalk.
Layout: text banner, PNG, padding, gzip, padding, ZIP, random bytes, trailing text.
Standard library only. Running it twice produces byte-identical output."""
import gzip
import io
import random
import struct
import zipfile
import zlib


def png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def make_png(size: int = 32) -> bytes:
    rows = b"".join(b"\x00" + bytes(v for x in range(size) for v in (x * 8 % 256, y * 8 % 256, 128))
                    for y in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(rows, 9)) + png_chunk(b"IEND", b""))


def make_gzip() -> bytes:
    text = b"".join(b"setting_%02d=%d\n" % (i, i * i) for i in range(40))
    return gzip.compress(text, mtime=0)


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("notes/readme.txt", b"Hello from inside the ZIP archive.\n" * 6),
                           ("run.sh", b"#!/bin/sh\necho demo\n")):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


parts = [
    ("banner (text)", b"DEMO-FW v1.0 build 2026-11-23\nboard=venatus-lab\n".ljust(192, b"\x00")),
    ("PNG image", make_png()),
    ("padding", b"\x00" * 160),
    ("gzip data", make_gzip()),
    ("padding", b"\xff" * 224),
    ("ZIP archive", make_zip()),
    ("random bytes", random.Random(1234).randbytes(8192)),
    ("trailer (text)", b"-- end of image --\n"),
]
blob, offset = b"", 0
print(f"{'part':<16}{'offset':>8}{'hex':>9}{'size':>8}")
for name, data in parts:
    print(f"{name:<16}{offset:>8}{offset:>#9x}{len(data):>8}")
    blob += data
    offset += len(data)
open("mystery.bin", "wb").write(blob)
print(f"\nwrote mystery.bin, {len(blob)} bytes")
