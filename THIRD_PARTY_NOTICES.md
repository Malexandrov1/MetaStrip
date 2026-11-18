# Third-party notices

MetaStrip is distributed as a whole under [AGPL-3.0-only](LICENSE).
Copyright (c) 2026 MetaStrip contributors. Existing MIT grants and notices
for MIT-licensed material remain in [LICENSES/MIT.txt](LICENSES/MIT.txt).

The v0.1.0 release consists of MetaStrip source. It declares Python
dependencies and documents optional executables that users install separately.

| Component | Terms relevant to MetaStrip |
| --- | --- |
| Python | PSF license and included third-party terms. Preserve notices with any later interpreter redistribution. |
| PyMuPDF and MuPDF | MetaStrip uses the GNU AGPLv3 option. Preserve upstream notices and meet the applicable Corresponding Source obligations for a combined distribution. |
| PySide6, Shiboken6, and Qt | Use applicable community terms, including LGPLv3 where available. Qt modules and bundled components have their own terms. Review notices, source, and replacement or relinking requirements before redistributing Qt binaries. For any GPLv3 component combined with AGPLv3 code, assess AGPLv3 section 13. |
| Pillow | MIT-CMU and historical Pillow/PIL terms. Its native codecs may carry additional notices. Preserve the applicable license files when redistributing. |
| ExifTool | Optional external executable under the same terms as Perl, which offers Artistic and GNU GPL alternatives. Preserve the selected license terms if redistributed. |
| FFmpeg and ffprobe | Optional external executables. License terms depend on build options. Verify the exact build, applicable notices, and source duties before redistributing any copy. |
| setuptools, pytest, pytest-qt, and Ruff | MIT-licensed build and test tools. Their distributions and transitive packages have separate terms. |
| PyInstaller and its hooks | Optional future build tools with GPL terms and distribution exceptions as applicable. Review the actual bootloader, hooks, and collected packages before distributing a bundle. |

For a later binary release, identify every included component and version,
retain its notices, and supply the applicable license texts and Corresponding
Source. Collecting license files alone cannot satisfy source obligations.

## Upstream references

- [GNU AGPLv3](https://www.gnu.org/licenses/agpl-3.0.html)
- [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html)
- [PyMuPDF source](https://github.com/pymupdf/PyMuPDF)
- [MuPDF source](https://github.com/ArtifexSoftware/mupdf)
- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/commercial/index.html)
- [Qt module licensing](https://doc.qt.io/qt-6/licensing.html)
- [Qt for Python third-party licenses](https://doc.qt.io/qtforpython-6/licenses.html)
- [Python license](https://docs.python.org/3/license.html)
- [Pillow license](https://pillow.readthedocs.io/en/stable/about.html#license)
- [ExifTool licensing](https://exiftool.org/)
- [FFmpeg legal information](https://ffmpeg.org/legal.html)
- [PyInstaller license and exception](https://pyinstaller.org/en/stable/license.html)
