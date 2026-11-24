#!/usr/bin/env python3
"""Report bytes that sit after the logical end of a JPEG or PNG file.

Usage: python trailing_bytes.py photo.jpg logo.png ...
Exit code 1 if any file has trailing data, so it can run in a pipeline.
"""
import struct
import sys

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def jpeg_end(data: bytes) -> int:
    """Offset just past the EOI marker, found by walking the real marker structure."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    i, n = 2, len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            raise ValueError(f"expected a marker at offset {i}")
        while data[i + 1] == 0xFF:  # fill bytes before a marker
            i += 1
        marker = data[i + 1]
        i += 2
        if marker == 0xD9:  # EOI: the logical end of the image
            return i
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers with no length field
            continue
        i += struct.unpack(">H", data[i:i + 2])[0]  # skip this segment
        if marker == 0xDA:  # SOS: skip the entropy-coded scan data that follows
            while i + 1 < n:
                if data[i] == 0xFF and data[i + 1] != 0x00 and not 0xD0 <= data[i + 1] <= 0xD7:
                    break
                i += 1
    raise ValueError("no EOI marker found")


def png_end(data: bytes) -> int:
    """Offset just past the IEND chunk."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG")
    i = 8
    while i + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[i:i + 8])
        i += 12 + length  # length + type + data + CRC
        if kind == b"IEND":
            return i
    raise ValueError("no IEND chunk found")


def check(path: str) -> int:
    data = open(path, "rb").read()
    end = jpeg_end(data) if data[:2] == b"\xff\xd8" else png_end(data)
    extra = len(data) - end
    status = f"{extra} trailing bytes" if extra else "clean"
    print(f"{path}: {len(data)} bytes, image ends at {end}, {status}")
    if extra:
        print(f"  first trailing bytes: {data[end:end + 16].hex(' ')}")
    return extra


if __name__ == "__main__":
    found = [check(p) for p in sys.argv[1:]]
    sys.exit(1 if any(found) else 0)
