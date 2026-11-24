"""Hide bits in the least significant bit of one color channel, then see what survives
a lossless save, a JPEG re-save, and a resize."""
import io
import numpy as np
from PIL import Image

rng = np.random.default_rng(42)
h, w = 256, 256
y, x = np.mgrid[0:h, 0:w]
photo = np.stack([
    120 + 60 * np.sin(x / 31.0) + rng.normal(0, 3, (h, w)),
    110 + 50 * np.cos(y / 27.0) + rng.normal(0, 3, (h, w)),
    100 + 40 * np.sin((x + y) / 45.0) + rng.normal(0, 3, (h, w)),
], axis=-1).clip(0, 255).astype(np.uint8)

bits = rng.integers(0, 2, 2000).astype(np.uint8)          # 2,000-bit payload
stego = photo.copy()
flat = stego[:, :, 2].reshape(-1)
flat[:bits.size] = (flat[:bits.size] & 0xFE) | bits         # embed in the blue LSB plane
stego[:, :, 2] = flat.reshape(h, w)

def read_bits(arr):
    return (arr[:, :, 2].reshape(-1)[:bits.size] & 1).astype(np.uint8)

def report(label, arr):
    wrong = int(np.count_nonzero(read_bits(arr) != bits))
    print(f"{label:<34} {wrong:4d} of {bits.size} bits wrong ({100 * wrong / bits.size:5.1f}%)")

buf = io.BytesIO(); Image.fromarray(stego).save(buf, "PNG"); buf.seek(0)
report("lossless PNG round trip", np.array(Image.open(buf)))
for q in (95, 85, 75):
    buf = io.BytesIO(); Image.fromarray(stego).save(buf, "JPEG", quality=q); buf.seek(0)
    report(f"re-saved as JPEG, quality {q}", np.array(Image.open(buf).convert("RGB")))
small = Image.fromarray(stego).resize((230, 230), Image.LANCZOS).resize((w, h), Image.LANCZOS)
report("resized to 90% and back", np.array(small))

# appended data does not survive a re-encode either
buf = io.BytesIO(); Image.fromarray(photo).save(buf, "JPEG", quality=90)
original = buf.getvalue() + b"88" + bytes(rng.integers(0, 256, 3000).astype(np.uint8)) + b"88"
img = Image.open(io.BytesIO(original)); out = io.BytesIO(); img.save(out, "JPEG", quality=90)
print(f"{'JPEG with 3,004 appended bytes':<34} {len(original):6d} bytes; after one re-save: {len(out.getvalue()):6d} bytes")
print("appended marker still present after re-save:", b"88" in out.getvalue()[-10:])
