#!/usr/bin/env python3
"""Record what you found in a form someone else can reproduce.
Needs trailing_bytes.py (from the insider threats article) in the same folder."""
import datetime
import hashlib
import sys

from trailing_bytes import jpeg_end, png_end


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


if len(sys.argv) != 2:
    print("usage: python evidence_log.py image.jpg", file=sys.stderr)
    sys.exit(2)
path = sys.argv[1]
with open(path, "rb") as f:
    data = f.read()
try:
    end = jpeg_end(data) if data[:2] == b"\xff\xd8" else png_end(data)
except ValueError as err:
    print(f"{path}: cannot find the end of the image ({err})", file=sys.stderr)
    sys.exit(2)
extra = data[end:]

now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
print(f"examined (UTC):     {now}")
print(f"file:               {path}")
print(f"size:               {len(data)} bytes")
print(f"SHA-256 (file):     {sha256(data)}")
print(f"image ends at:      byte offset {end}")
print(f"trailing bytes:     {len(extra)}")
if extra:
    print(f"SHA-256 (trailing): {sha256(extra)}")
    print(f"first 16 bytes:     {extra[:16].hex(' ')}")
