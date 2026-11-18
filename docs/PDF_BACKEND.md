# PDF backend and licensing

MetaStrip v0.1.0 retains PyMuPDF under the AGPLv3 option. The application
is distributed under AGPL-3.0-only.

## What the backend does

- `app/core/inspector.py` checks encryption, repair status, and size, then reads
  document properties, XMP, trailer ID, attachments, and annotations.
- `app/core/sanitizer.py` checks forms, signatures, and active objects. It removes
  supported metadata and attachments, preserves annotation appearances where
  requested, and writes a full copy with unreachable objects removed and no new ID.
- `app/core/verifier.py` compares page count, geometry, extracted text, and 36 DPI
  render hashes with annotations excluded. Tests also check retained annotation
  appearance and rejection of encrypted input.

## Replacement assessment

| Option | Capabilities | Migration work |
| --- | --- | --- |
| [pypdf](https://pypdf.readthedocs.io/en/stable/) (BSD-3-Clause) | Python PDF objects, metadata, attachments, and text extraction | Requires a separate renderer. A full-clone writer needs explicit control over retained objects, the trailer ID, forms, and annotations. |
| [pikepdf](https://pikepdf.readthedocs.io/en/stable/) (MPL-2.0) with [qpdf](https://github.com/qpdf/qpdf) (Apache-2.0) | Native-backed object editing and non-incremental saves | Requires a separate text and rendering backend. qpdf generates a trailer ID by default. Annotation and malformed-document behavior need parity testing. MPL obligations still apply to covered files. |
| [pypdfium2 and PDFium](https://pypdfium2.readthedocs.io/en/stable/) | Native text extraction and raster rendering. The wrapper offers Apache-2.0 or BSD-3-Clause terms. PDFium and bundled components have separate notices. | A candidate for verification in a two-library migration. Metadata rewriting and object policy still need a writer and independent tests. |

A writer plus PDFium is technically plausible. It would change the writer
and the reference renderer and add a second parser. Migration needs coverage
for incremental PDFs, malformed and repaired files, encrypted and active PDFs,
embedded and associated files, retained annotations, fonts, crop boxes, and
rotated pages. Compare acceptance decisions and output integrity alongside
wall time and peak memory. Native rendering is available in both designs.
Package descriptions cannot establish performance parity.

On one synthetic 32-page Windows fixture, the current backend removed the
author, XMP, and trailer ID. Its output matched the original's text and render
hashes under both MuPDF and PDFium. The pikepdf 10.18.2 trial preserved those
checks but generated a trailer ID even after the input ID was removed. The
pypdf 7.1.0 full-clone trial removed the tested metadata, but the output
failed the MuPDF page comparison and PDFium 5.15.2 could not open it.
Median text extraction and 36 DPI rendering over five runs on that fixture
took 9.14 ms with MuPDF and 5.68 ms with PDFium. These timings exclude rewriting
and do not establish performance on representative documents.

## Source release

Use the AGPLv3 distribution plan in the [release checklist](RELEASE_CHECKLIST.md).
The original MIT notice is preserved in [LICENSES/MIT.txt](../LICENSES/MIT.txt).
Review the terms and Corresponding Source requirements again if binaries are
distributed later. [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html)
