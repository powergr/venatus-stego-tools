#!/usr/bin/env python3
"""Scan a file for known file signatures (magic numbers) at every offset.

Usage:
    python sigscan.py mystery.bin
    python sigscan.py mystery.bin --min-bytes 3 --json
    python sigscan.py mystery.bin --start-only

The signature list comes from ../data/file-signatures.json, the same data published at
https://venatus.me/file-signatures/. Standard library only.

A hit is a candidate, not proof. Short signatures match by accident in compressed or random data,
so check the bytes around each hit, or use a parser that validates the structure (see carve_demo.py).
"""
import argparse
import json
import os
import sys

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "file-signatures.json")


def load_signatures(path=DEFAULT_DB):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def to_bytes(hex_text):
    return bytes.fromhex(hex_text.replace(" ", ""))


def risk(matched_bytes):
    """Same rule of thumb as the website: 6 or more bytes is low, 4 or 5 is medium, 3 or fewer is high."""
    return "low" if matched_bytes >= 6 else "medium" if matched_bytes >= 4 else "high"


def scan(data, signatures, min_bytes=4, start_only=False):
    """Return a list of hits sorted by file offset. Each hit is a dict.

    With start_only the file is not searched at all: each signature is checked once, at offset 0.
    """
    hits = []
    for sig in signatures:
        checks = [(c["offset"], to_bytes(c["hex"])) for c in sig["magic"]]
        matched = sum(len(b) for _, b in checks)
        if matched < min_bytes:
            continue

        def hit(start):
            return {
                "offset": start,
                "id": sig["id"],
                "name": sig["name"],
                "category": sig["category"],
                "matched_bytes": matched,
                "risk": risk(matched),
                "extensions": sig["extensions"],
            }

        if start_only:
            if all(data[o:o + len(b)] == b for o, b in checks):
                hits.append(hit(0))
            continue

        first_offset, first_bytes = checks[0]
        pos = data.find(first_bytes)
        while pos != -1:
            start = pos - first_offset
            if start >= 0 and all(data[start + o:start + o + len(b)] == b for o, b in checks):
                hits.append(hit(start))
            pos = data.find(first_bytes, pos + 1)
    hits.sort(key=lambda h: (h["offset"], -h["matched_bytes"], h["id"]))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find known file signatures at every offset of a file.")
    ap.add_argument("file")
    ap.add_argument("--db", default=DEFAULT_DB, help="path to file-signatures.json")
    ap.add_argument("--min-bytes", type=int, default=4,
                    help="ignore signatures shorter than this many bytes (default 4; use 3 to include gzip and JPEG)")
    ap.add_argument("--start-only", action="store_true", help="only report signatures that start at offset 0")
    ap.add_argument("--limit", type=int, default=200, help="maximum hits to print (default 200)")
    ap.add_argument("--json", action="store_true", help="print hits as JSON")
    args = ap.parse_args(argv)

    with open(args.file, "rb") as f:
        data = f.read()
    hits = scan(data, load_signatures(args.db), args.min_bytes, args.start_only)
    hidden = len(hits) - args.limit

    if args.json:
        json.dump(hits[:args.limit], sys.stdout, indent=1)
        print()
        if hidden > 0:  # stderr, so the JSON on stdout stays valid
            print(f"warning: {hidden} more hits not shown (raise --limit)", file=sys.stderr)
    else:
        print(f"{'offset':>8}  {'hex':>8}  {'risk':<6} {'bytes':>5}  format")
        for h in hits[:args.limit]:
            print(f"{h['offset']:>8}  {h['offset']:>#8x}  {h['risk']:<6} {h['matched_bytes']:>5}  {h['name']}")
        if hidden > 0:
            print(f"... {hidden} more hits not shown (raise --limit)")
        print(f"\n{len(hits)} candidate hit(s) in {len(data)} bytes. Verify each one before you trust it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
