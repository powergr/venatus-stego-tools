#!/usr/bin/env python3
"""Find PNG, gzip and ZIP data inside a file, work out where each one ENDS by walking its real
structure, validate it, and carve it out. This is what size-aware parsers do.

Usage: python carve_demo.py mystery.bin
Every magic number hit is tried. A hit that does not validate, or that sits inside a file already
carved, is skipped as a false positive. Carved files are written to the current folder.
"""
import io
import struct
import sys
import zipfile
import zlib

if len(sys.argv) != 2:
    print("usage: python carve_demo.py mystery.bin", file=sys.stderr)
    sys.exit(2)
with open(sys.argv[1], "rb") as f:
    data = f.read()

# Anything that means "this candidate is not a valid file of that type".
INVALID = (ValueError, struct.error, zlib.error, zipfile.BadZipFile)


def png_end(start):
    i = start + 8
    while i + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[i:i + 8])
        i += 12 + length
        if kind == b"IEND":
            if i > len(data):
                raise ValueError("the IEND chunk is cut off")
            return i
    raise ValueError("no IEND chunk")


def gzip_end(start):
    d = zlib.decompressobj(wbits=31)  # 31 = gzip container
    d.decompress(data[start:])
    if not d.eof:
        raise ValueError("the gzip stream is cut off")
    return len(data) - len(d.unused_data)


def zip_end(start):
    """Try each end-of-central-directory record in turn. One can appear by chance inside stored data."""
    eocd = data.find(b"PK\x05\x06", start)
    while eocd != -1:
        if eocd + 22 <= len(data):
            comment_len = struct.unpack("<H", data[eocd + 20:eocd + 22])[0]
            end = eocd + 22 + comment_len
            if end <= len(data):
                try:
                    with zipfile.ZipFile(io.BytesIO(data[start:end])) as z:
                        if z.namelist() and z.testzip() is None:
                            return end
                except zipfile.BadZipFile:
                    pass
        eocd = data.find(b"PK\x05\x06", eocd + 1)
    raise ValueError("no valid end-of-central-directory record")


def describe(ext, chunk):
    """Validate the carved bytes and return a one-line result. Raises if they are not valid."""
    if ext == "png":
        crc_ok = zlib.crc32(chunk[12:29]) == struct.unpack(">I", chunk[29:33])[0]
        return f"IHDR checksum {'ok' if crc_ok else 'BAD'}, ends with IEND: {chunk[-8:-4] == b'IEND'}"
    if ext == "gz":
        text = zlib.decompress(chunk, 31)
        return f"decompresses to {len(text)} bytes, starts {text[:19]!r}"
    with zipfile.ZipFile(io.BytesIO(chunk)) as z:
        return f"files {z.namelist()}, integrity {'ok' if z.testzip() is None else 'BAD'}"


FORMATS = [(b"\x89PNG\r\n\x1a\n", "png", png_end),
           (b"\x1f\x8b\x08", "gz", gzip_end),
           (b"PK\x03\x04", "zip", zip_end)]
candidates = []
for magic, ext, end_of in FORMATS:
    pos = data.find(magic)
    while pos != -1:
        candidates.append((pos, ext, end_of))
        pos = data.find(magic, pos + 1)

print(f"{'type':<6}{'offset':>8}{'end':>8}{'size':>8}  check")
covered_until, carved = 0, 0
for start, ext, end_of in sorted(candidates, key=lambda c: c[0]):
    if start < covered_until:
        continue  # inside a file we already carved, such as a second ZIP entry
    try:
        end = end_of(start)
        chunk = data[start:end]
        note = describe(ext, chunk)
    except INVALID:
        continue  # a chance match, or a damaged file
    with open(f"carved_{start}.{ext}", "wb") as out:
        out.write(chunk)
    print(f"{ext:<6}{start:>8}{end:>8}{len(chunk):>8}  {note}")
    covered_until = end
    carved += 1
if carved == 0:
    print("no valid embedded files found")
