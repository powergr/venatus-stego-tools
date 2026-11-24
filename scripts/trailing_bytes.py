#!/usr/bin/env python3
"""Report bytes that sit after the logical end of a JPEG or PNG file.

Usage: python trailing_bytes.py photo.jpg logo.png ...
Exit code 0 if every file is clean, 1 if any file has trailing data, so it can run in a pipeline.
Exit code 2 if there is no argument, or if a file could not be read or is not a whole JPEG or PNG
(and no other file had trailing data).
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
        while i + 1 < n and data[i + 1] == 0xFF:  # fill bytes before a marker
            i += 1
        if i + 1 >= n:
            break  # the file ends in fill bytes, so there is no EOI
        marker = data[i + 1]
        i += 2
        if marker == 0xD9:  # EOI: the logical end of the image
            return i
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers with no length field
            continue
        if i + 2 > n:
            raise ValueError("file ends inside a segment header")
        length = struct.unpack(">H", data[i:i + 2])[0]
        if length < 2:  # the length counts its own two bytes
            raise ValueError(f"invalid segment length {length} at offset {i}")
        i += length  # skip this segment
        if marker == 0xDA:  # SOS: skip the entropy-coded scan data that follows
            while i + 1 < n:
                if data[i] == 0xFF:
                    following = data[i + 1]
                    if following == 0xFF:  # a fill byte: the real marker byte comes next
                        i += 1
                        continue
                    if following != 0x00 and not 0xD0 <= following <= 0xD7:
                        break  # a real marker, so the scan is over
                i += 1
    raise ValueError("no EOI marker found")


def png_end(data: bytes) -> int:
    """Offset just past the IEND chunk."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG")
    i = 8
    while i + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[i:i + 8])
        chunk_end = i + 12 + length  # length + type + data + CRC
        if chunk_end > len(data):
            raise ValueError(f"truncated {kind.decode('latin-1')} chunk at offset {i}")
        i = chunk_end
        if kind == b"IEND":
            return i
    raise ValueError("no IEND chunk found")


def check(path: str) -> int:
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] == b"\xff\xd8":
        end = jpeg_end(data)
    elif data[:8] == PNG_SIGNATURE:
        end = png_end(data)
    else:
        raise ValueError("not a JPEG or PNG file")
    extra = len(data) - end
    status = f"{extra} trailing bytes" if extra else "clean"
    print(f"{path}: {len(data)} bytes, image ends at {end}, {status}")
    if extra:
        print(f"  first trailing bytes: {data[end:end + 16].hex(' ')}")
    return extra


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python trailing_bytes.py photo.jpg logo.png ...", file=sys.stderr)
        sys.exit(2)
    found, failed = [], 0
    for p in sys.argv[1:]:
        try:
            found.append(check(p))
        except (ValueError, OSError) as err:
            print(f"{p}: cannot analyze ({err})", file=sys.stderr)
            failed += 1
    sys.exit(1 if any(found) else 2 if failed else 0)
