# Apple JPEG sample: stale MPF frame count

## Reproduction and actual cause

The original `Apple_iPhone15ProMax.jpg` was found in the user's downloaded
ExifTool Apple sample archive and tested directly, without modifying it.

- SHA-256: `840c8c862c41b690ca4400cce7c061f6ec65ae55550171d421af5fdd2c100ee5`
- File size: 5,663 bytes; decoded primary: 8 x 8 RGB pixels.
- Pillow 11.3 opens it as `MpoImageFile`, format `MPO`, `n_frames = 2`.
- MPF TIFF base: 3,638; second image's relative offset: 4,428,450.
- Absolute second-image offset: **4,432,088**, outside the file.
- The MPF entry declares 151,403 bytes for that missing image.
- Reading the primary succeeds; `seek(1)` / `load()` raises
  `ValueError: No data found for frame`.
- Before the fix, `Sanitizer.process()` returned
  `Multi-frame images are not supported for safe sanitization.`

Pillow's JPEG factory promotes a JPEG to MPO when the APP2 MPF index declares
multiple images. Its MPO plugin assigns `n_frames` from MPF tag `0xB001`; that
count does not establish that the referenced image bytes are actually present.
See the [Pillow JPEG implementation](https://github.com/python-pillow/Pillow/blob/11.3.0/src/PIL/JpegImagePlugin.py)
and [MPO implementation](https://github.com/python-pillow/Pillow/blob/11.3.0/src/PIL/MpoImagePlugin.py).

The [ExifTool sample repository](https://exiftool.org/sample_images.html) explains
that main image content is replaced and data after the primary JPEG EOI is removed,
while original APP segments are retained. This sample therefore contains an
obsolete MPF index pointing into the original, much larger file. Ordinary EXIF
thumbnails are not responsible for the reported frame count. The absent image's
MP type is `Undefined`; its removed content cannot be identified from this file.

## Fix and safety boundary

`jpeg_structure.py` parses marker lengths, entropy-coded scan boundaries and EOI,
then validates the MPF TIFF index and entry bounds. It does not search blindly for
SOI/EOI bytes, which can legitimately occur inside metadata and preview images.

An obsolete multi-image index is accepted only when:

1. The primary JPEG is structurally complete and decodes successfully.
2. Its EOI ends exactly at EOF, with no unclassified trailing bytes.
3. There is exactly one well-formed MPF index with consistent JPEG entries.
4. Every secondary entry starts outside the actual file.

Cleanup removes the MPF APP2 segment and other removable metadata without
recompressing the primary. Output pixels, orientation, ICC policy and scanned
sensitive fields are verified. Inspection distinguishes the declared MPF count
from the one present primary image. The verification report retains the source
warning describing stale references.

Present or partly present secondary images, overlapping entries, ambiguous
trailers, malformed or duplicate indexes remain unsupported. Genuine MPO is
rejected even when Pillow's Ultra HDR exception exposes only a base JPEG with no
`n_frames` property. APNG, animated WebP and multi-page TIFF protection remains.

## Regression tests and actual results

`tests/unit/test_jpeg_frames.py` includes synthetic little/big-endian stale indexes,
real two-image MPO, the Ultra HDR factory exception, overlapping/partly present
entries, trailing data, missing primary EOI, malformed/duplicate indexes, nested
JPEG previews, unsupported animated/multi-page formats and the original sample.

The public sample is not redistributed. The original-file test is enabled by
`METASTRIP_APPLE_SAMPLE`; it verifies the exact source hash and performs real
end-to-end sanitization. All generated tests run without downloads.

```powershell
$env:METASTRIP_APPLE_SAMPLE = 'C:\path\to\Apple_iPhone15ProMax.jpg'
.\.venv\Scripts\python.exe -m pytest -ra
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts/check_core_offline.py
```

Actual Windows results after the fix:

- Full pytest: **59 passed, 3 skipped** in 7.59 seconds, including the original
  Apple sample. Skips require unavailable ExifTool/FFmpeg/ffprobe.
- Ruff: passed for the entire repository after correcting one existing nested
  context-manager style issue in a preferences test.
- Existing offline suite: **35/35 passed**.
- Original sample: a readable, single-image JPEG copy was produced, original
  bytes preserved, decoded pixels and orientation unchanged, no MPF/XMP in the
  output, and no remaining sensitive fields reported by the available scanner.

ExifTool was not available for independent output inspection. The result is
`Passed with warnings`, explicitly describing limited scanner coverage and stale
MPF references; no universal metadata-removal guarantee is made.
