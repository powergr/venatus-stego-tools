# Venatus Stego Tools

Small, tested Python scripts from the guides at [venatus.me](https://venatus.me), plus the file signature dataset behind the [File Signature Reference](https://venatus.me/file-signatures/).

Every script is short enough to read in one sitting. Most use only the Python standard library. Each one is here so you can run it, change it, and see what happens, instead of copying code out of an article.

## Quick start

You need Python 3.9 or newer, because `make_mystery.py` uses `random.randbytes`. There is nothing to install for most scripts.

```
python scripts/make_mystery.py
python scripts/sigscan.py mystery.bin --min-bytes 3
python scripts/carve_demo.py mystery.bin
python scripts/entropy_profile.py mystery.bin 512
```

Run those four commands in an empty folder. The first builds a practice file, and the other three analyze it. The scripts write their output files into the current folder, so use a scratch folder.

Two demos need extra packages:

```
pip install -r requirements.txt
```

## The scripts

| Script | What it does | Article |
| --- | --- | --- |
| `scripts/make_mystery.py` | Builds `mystery.bin`, a small firmware-like blob with a PNG, a gzip stream, and a ZIP archive hidden between padding and random bytes. Running it twice gives identical bytes on the same machine, but other zlib builds can shift the offsets slightly. | [The Complete Guide to Binwalk](https://venatus.me/blog/binwalk-complete-guide/) |
| `scripts/carve_demo.py` | Finds PNG, gzip, and ZIP data inside a file, works out where each one ends by walking its real structure, validates it, and carves it out. It tries every hit and skips chance matches and damaged files. | [The Complete Guide to Binwalk](https://venatus.me/blog/binwalk-complete-guide/) |
| `scripts/entropy_profile.py` | Prints the Shannon entropy of every block of a file, with a text bar. An optional second argument sets the block size. | [The Complete Guide to Binwalk](https://venatus.me/blog/binwalk-complete-guide/) |
| `scripts/sigscan.py` | Scans a file for the signatures in `data/file-signatures.json` at every offset. Written for this repository. | [File Signature Reference](https://venatus.me/file-signatures/) |
| `scripts/trailing_bytes.py` | Reports bytes that sit after the logical end of a JPEG or PNG. Exits with code 1 when it finds any, and with code 2 when a file is unreadable or is not a whole JPEG or PNG, so it works in a pipeline. | [Insider Threats and Data Exfiltration](https://venatus.me/blog/insider-threats-and-data-exfiltration/) |
| `scripts/evidence_log.py` | Records what you found in a form someone else can reproduce: timestamp, hashes, offsets. Needs `trailing_bytes.py` in the same folder. | [Steganography in the Courtroom](https://venatus.me/blog/steganography-in-the-courtroom/) |
| `scripts/recompress_demo.py` | Hides bits in one color channel, then shows what survives a lossless save, a JPEG re-save, and a resize. Needs numpy and Pillow. | [How Platforms Detect Hidden Data at Scale](https://venatus.me/blog/how-platforms-detect-hidden-data-at-scale/) |
| `scripts/toy_text_watermark.py` | A toy red and green list text watermark, for intuition only. Needs numpy. | [AI Content Watermarking, C2PA and SynthID](https://venatus.me/blog/ai-content-watermarking-c2pa-synthid/) |

## Scanning for file signatures

`sigscan.py` looks for every signature at every offset. It is a quick way to see what might be hiding inside an unknown file.

```
python scripts/sigscan.py mystery.bin --min-bytes 3
```

On the practice file, it reports the PNG at offset 192, the gzip stream at 2147, and the ZIP archive at 2567. Exact offsets can differ by a few bytes, because the compressed sizes depend on your zlib build. The script also reports two more ZIP hits. One is the second file's local header, and the other is the end-of-central-directory record, which a ZIP file always carries.

A hit is a candidate, not proof. Short signatures match by accident in compressed or random data. That is why the default ignores signatures shorter than four bytes, and why the output has a `risk` column. Check the bytes around each hit, or use a parser that validates the structure, as `carve_demo.py` does.

Useful options:

- `--min-bytes 3` includes short signatures such as gzip and JPEG.
- `--start-only` reports only signatures that begin at offset 0, which is how you identify a whole file.
- `--json` prints the hits as JSON.

## The signature dataset

`data/file-signatures.json` holds 95 signatures. Each entry has the header bytes with offsets, an optional trailer, extensions, a media type, a category, and a note about carving.

Two flags describe how much to trust an entry:

- `tested` is true when a real file with one of the listed extensions carries the header, and the file was made by software other than ours.
- `trailerTested` is true when such a file also ends with the listed trailer.

Entries that are not tested come from published format specifications. They are probably right, but nobody has checked them against a file here. Please verify those before you rely on them.

The same data is available as [JSON](https://venatus.me/data/file-signatures.json) and [CSV](https://venatus.me/data/file-signatures.csv) from the website. The copy in this repository can lag behind the website, so check the date on the reference page.

## Tests

```
python -m unittest discover -s tests -v
```

The tests build real sample files with the standard library, then check that `sigscan.py` names each one correctly. They also check the dataset for malformed entries, rebuild `mystery.bin` twice to confirm it is reproducible, and run every script. The two numpy demos are skipped when numpy and Pillow are missing. Nothing is written into the repository.

The scripts and tests passed on Python 3.15.2 with numpy 2.5.5 and Pillow 13.0.0, on Windows 11.

## Safety

Treat any file you analyze as untrusted data. Never open or run something you carved out of an unknown file on your main computer. Use a virtual machine or a throwaway folder. These scripts read files and write carved copies, and nothing more.

## Found a mistake?

Please [open an issue](https://github.com/powergr/venatus-feedback/issues). Tell us which script or signature, what you expected, and what happened. A sample file or a link to the format specification is the best evidence.

## License

The code is released under the MIT License, and the full text is in the `LICENSE` file.

The dataset in `data/` is released under the [Creative Commons Attribution 4.0 license](https://creativecommons.org/licenses/by/4.0/). Please credit "Venatus, File Signature Reference, https://venatus.me/file-signatures/" when you reuse it.
