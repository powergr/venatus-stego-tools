#!/usr/bin/env python3
"""Print the Shannon entropy (bits per byte, 0 to 8) of every block of a file, with a text bar.

Usage: python entropy_profile.py file.bin [block_size]
The block size defaults to 512 bytes.
"""
import math
import sys
from collections import Counter

if len(sys.argv) not in (2, 3):
    print("usage: python entropy_profile.py file.bin [block_size]", file=sys.stderr)
    sys.exit(2)
try:
    BLOCK = int(sys.argv[2]) if len(sys.argv) == 3 else 512
except ValueError:
    BLOCK = 0
if BLOCK <= 0:
    print("block_size must be a positive whole number", file=sys.stderr)
    sys.exit(2)
with open(sys.argv[1], "rb") as f:
    data = f.read()


def entropy(chunk):
    n = len(chunk)
    # "+ 0.0" turns the -0.0 that a block of identical bytes produces into a plain 0.0
    return -sum(c / n * math.log2(c / n) for c in Counter(chunk).values()) + 0.0


print(f"{'offset':>7}  {'bits/byte':>9}  profile")
for off in range(0, len(data), BLOCK):
    e = entropy(data[off:off + BLOCK])
    print(f"{off:>7}  {e:>9.2f}  {'#' * round(e * 4)}")
