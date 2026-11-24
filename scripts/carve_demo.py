#!/usr/bin/env python3
"""Find PNG, gzip and ZIP data inside a file, work out where each one ENDS by walking its real
structure, validate it, and carve it out. This is what size-aware parsers do."""
import io
import struct
import sys
import zipfile
import zlib

data = open(sys.argv[1], "rb").read()


def png_end(start):
    i = start + 8
    while True:
        length, kind = struct.unpack(">I4s", data[i:i + 8])
        i += 12 + length
        if kind == b"IEND":
            return i


def gzip_end(start):
    d = zlib.decompressobj(wbits=31)  # 31 = gzip container
    d.decompress(data[start:])
    return len(data) - len(d.unused_data)


def zip_end(start):
    eocd = data.index(b"PK\x05\x06", start)  # end-of-central-directory record
    comment_len = struct.unpack("<H", data[eocd + 20:eocd + 22])[0]
    return eocd + 22 + comment_len


found = [(data.find(b"\x89PNG\r\n\x1a\n"), "png", png_end),
         (data.find(b"\x1f\x8b\x08"), "gz", gzip_end),
         (data.find(b"PK\x03\x04"), "zip", zip_end)]
print(f"{'type':<6}{'offset':>8}{'end':>8}{'size':>8}  check")
for start, ext, end_of in sorted(f for f in found if f[0] >= 0):
    end = end_of(start)
    chunk = data[start:end]
    if ext == "png":
        crc_ok = zlib.crc32(chunk[12:29]) == struct.unpack(">I", chunk[29:33])[0]
        note = f"IHDR checksum {'ok' if crc_ok else 'BAD'}, ends with IEND: {chunk[-8:-4] == b'IEND'}"
    elif ext == "gz":
        text = zlib.decompress(chunk, 31)
        note = f"decompresses to {len(text)} bytes, starts {text[:19]!r}"
    else:
        z = zipfile.ZipFile(io.BytesIO(chunk))
        note = f"files {z.namelist()}, integrity {'ok' if z.testzip() is None else 'BAD'}"
    open(f"carved_{start}.{ext}", "wb").write(chunk)
    print(f"{ext:<6}{start:>8}{end:>8}{len(chunk):>8}  {note}")
