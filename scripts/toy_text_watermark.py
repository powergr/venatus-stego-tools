"""A toy red/green-list text watermark, for intuition only.
Real systems work on real language models; here a Zipf-distributed 'vocabulary' stands in."""
import numpy as np

V, T, KEY = 2000, 200, 12345
P1, P2, MOD = 1315423911, 2654435761, 1000003
ranks = np.arange(1, V + 1)
base = 1.0 / ranks
base /= base.sum()
tokens = np.arange(V, dtype=np.int64)  # P2 does not fit in 32 bits, so be explicit about the width

def green_mask(prev):
    """Half the vocabulary is 'green' for each previous token, chosen by a keyed hash."""
    return ((prev * P1 + tokens * P2 + KEY) % MOD) % 2 == 0

def generate(rng, delta):
    out, prev = [], 0
    for _ in range(T):
        logits = np.log(base) + (delta * green_mask(prev) if delta else 0.0)
        p = np.exp(logits - logits.max()); p /= p.sum()
        prev = int(rng.choice(V, p=p))
        out.append(prev)
    return out

def z_score(seq):
    greens = sum(bool(green_mask(a)[b]) for a, b in zip(seq, seq[1:]))
    n = len(seq) - 1
    return (greens - 0.5 * n) / np.sqrt(0.25 * n)

def scrub(rng, seq, frac):
    """Crude stand-in for paraphrasing: replace a fraction of tokens at random."""
    seq = list(seq)
    for i in np.flatnonzero(rng.random(len(seq)) < frac):
        seq[i] = int(rng.choice(V, p=base))
    return seq

rng = np.random.default_rng(7)
marked = [generate(rng, delta=2.0) for _ in range(100)]
plain = [generate(rng, delta=0.0) for _ in range(100)]
def summary(label, group):
    z = np.array([z_score(s) for s in group])
    print(f"{label:<30} mean z = {z.mean():6.2f}   flagged at z > 4: {int((z > 4).sum()):3d} of {len(z)}")

summary("plain text (no watermark)", plain)
summary("watermarked", marked)
for frac in (0.1, 0.3, 0.5):
    summary(f"watermarked, {int(frac * 100)}% tokens replaced", [scrub(rng, s, frac) for s in marked])
