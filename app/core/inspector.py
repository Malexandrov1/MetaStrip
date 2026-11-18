"""Local inspection with explicit scanner coverage and untrusted text handling."""

import json
import warnings
from pathlib import Path
from threading import Event
from typing import Any

from PIL import ExifTags, Image

from app.core.exiftool import run_exiftool
from app.core.formats import detect_format
from app.core.jpeg_structure import STALE_MPF_WARNING, jpeg_frame_info
from app.core.models import (
    DependencyError,
    FileFormat,
    InspectionResult,
    MetadataField,
    MetaStripError,
    UnsupportedFormatError,
)
from app.core.tools import check_cancel, run_tool, video_input_args
from app.utils.dependency_checker import check_dependencies

_TECHNICAL = {
    "imagewidth",
    "imageheight",
    "imagelength",
    "exifimagewidth",
    "exifimageheight",
    "imagesize",
    "megapixels",
    "encodingprocess",
    "bitspersample",
    "colorcomponents",
    "ycbcrsubsampling",
    "compression",
    "photometricinterpretation",
    "stripoffsets",
    "samplesperpixel",
    "rowsperstrip",
    "stripbytecounts",
    "planarconfiguration",
    "tilewidth",
    "tilelength",
    "tileoffsets",
    "tilebytecounts",
    "orientation",
    "resolutionunit",
    "xresolution",
    "yresolution",
    "ycbcrpositioning",
    "colorspace",
    "exifversion",
    "flashpixversion",
    "componentsconfiguration",
    "interopindex",
    "interopversion",
    "jfifversion",
    "pixelunits",
    "pixelsperunitx",
    "pixelsperunity",
    "bitdepth",
    "colortype",
    "filter",
    "interlace",
    "srgb rendering",
    "srgb renderingintent",
    "srgb_rendering",
    "gamma",
    "whitepointx",
    "whitepointy",
    "redx",
    "redy",
    "greenx",
    "greeny",
    "bluex",
    "bluey",
    "backgroundcolor",
    "significantbits",
    "alphaisused",
    "animation",
    "canvaswidth",
    "canvasheight",
    "vp8version",
    "horizontal scale",
    "vertical scale",
    "transform",
    "dctencodeversion",
    "app14flags0",
    "app14flags1",
    "vpexversion",
    "hasalpha",
    "hasanimation",
    "hasexif",
    "hasxmp",
    "hasicc",
    "exifbyteorder",
    "srgbrendering",
    "srgbrenderingintent",
    "horizontalscale",
    "verticalscale",
    "subfiletype",
    "newsubfiletype",
    "extrasamples",
    "sampleformat",
    "minsamplevalue",
    "maxsamplevalue",
    "predictor",
    "fillorder",
    "inkset",
    "numberofinks",
    "dotrange",
    "colormap",
}


def category_for(name: str) -> str:
    lower = name.lower()
    if any(word in lower for word in ("gps", "location", "latitude", "longitude")):
        return "Location"
    if any(word in lower for word in ("date", "time")):
        return "Dates"
    if any(word in lower for word in ("author", "artist", "copyright", "creator", "owner")):
        return "Author"
    if any(word in lower for word in ("software", "producer", "encoder")):
        return "Software"
    if any(word in lower for word in ("camera", "make", "model", "lens", "serial", "exposure")):
        return "Camera"
    return "Other"


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return f"[binary data: {len(value)} bytes]"
    return str(value)[:4096]


def _field(name: str, value: Any, *, sensitive: bool | None = None) -> MetadataField:
    group, _, tag = name.rpartition(":")
    if sensitive is None:
        sensitive = not (
            tag.lower() in _TECHNICAL
            or group in {"File", "System", "JFIF", "Adobe"}
            or group.startswith("ICC")
            or name in {"EXIF:InterColorProfile", "IFD0:InterColorProfile"}
        )
    category = category_for(name) if sensitive else "Technical"
    return MetadataField(name, _text(value), category, sensitive)


def _pymupdf() -> Any:
    try:
        import pymupdf
    except ImportError as exc:
        raise DependencyError(
            "PDF support requires PyMuPDF. Install the project dependencies."
        ) from exc
    return pymupdf


def video_probe(path: Path, cancel: Event | None = None) -> dict[str, Any]:
    executable = check_dependencies()["ffprobe"]
    if executable is None:
        raise DependencyError("Video inspection requires ffprobe on PATH or METASTRIP_FFPROBE.")
    raw = run_tool(
        [
            executable,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            "-of",
            "json",
            *video_input_args(path),
        ],
        cancel,
    )
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise MetaStripError("ffprobe returned invalid metadata.") from exc
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("streams"), list)
        or not result["streams"]
        or not all(isinstance(stream, dict) for stream in result["streams"])
        or not isinstance(result.get("format", {}), dict)
        or any(
            not isinstance(container.get("tags", {}), dict)
            for container in [result.get("format", {}), *result["streams"]]
        )
    ):
        raise MetaStripError("No readable media streams were found.")
    return result


class MetadataInspector:
    """Inspect a file; never execute metadata or log its values."""

    def inspect(self, path: Path, cancel: Event | None = None) -> InspectionResult:
        path = Path(path)
        try:
            check_cancel(cancel)
            format_ = detect_format(path)
            path = path.resolve()
            if format_ == FileFormat.PDF:
                return self._pdf(path, format_, cancel)
            if format_ in {FileFormat.MP4, FileFormat.MOV}:
                return self._video(path, format_, cancel)
            return self._image(path, format_, cancel)
        except MetaStripError:
            raise
        except (
            OSError,
            ValueError,
            SyntaxError,
            RuntimeError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise MetaStripError(
                "The file is malformed, unreadable, or exceeds safe image limits."
            ) from exc

    def _image(self, path: Path, format_: FileFormat, cancel: Event | None) -> InspectionResult:
        if path.stat().st_size > 512 * 1024 * 1024:
            raise MetaStripError("Images larger than 512 MiB exceed the safe inspection limit.")
        notes: list[str] = []
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image.load()
                fields = [
                    MetadataField("File:Format", format_.value, "General", False),
                    MetadataField(
                        "Image:Dimensions", f"{image.width} × {image.height}", "Technical", False
                    ),
                    MetadataField(
                        "Image:Frames", str(getattr(image, "n_frames", 1)), "Technical", False
                    ),
                ]
                if format_ == FileFormat.JPEG and "mp" in image.info:
                    frames = jpeg_frame_info(path.read_bytes())
                    fields.append(
                        MetadataField(
                            "Image:DeclaredMPFImages",
                            str(frames.declared_frames),
                            "Technical",
                            False,
                        )
                    )
                    if frames.stale_index:
                        fields[2] = MetadataField("Image:Frames", "1", "Technical", False)
                        notes.append(STALE_MPF_WARNING)
                for key, value in image.info.items():
                    if key in {
                        "exif",
                        "icc_profile",
                        "jfif",
                        "jfif_version",
                        "jfif_unit",
                        "jfif_density",
                        "dpi",
                        "aspect",
                        "gamma",
                        "chromaticity",
                        "srgb",
                        "transparency",
                        "background",
                        "progressive",
                        "progression",
                        "adobe",
                        "adobe_transform",
                        "interlace",
                    }:
                        if key == "icc_profile":
                            fields.append(_field("ICC:Profile", value, sensitive=False))
                        continue
                    if format_ == FileFormat.TIFF and key == "resolution":
                        fields.append(_field("Image:resolution", value, sensitive=False))
                        continue
                    if format_ == FileFormat.WEBP and key in {"loop", "duration", "timestamp"}:
                        fields.append(_field(f"Image:{key}", value, sensitive=False))
                        continue
                    fields.append(_field(f"Image:{key}", value))
                exif = image.getexif()
                for key, value in exif.items():
                    if key in {34665, 34853, 40965}:
                        try:
                            nested = exif.get_ifd(key)
                        except (KeyError, ValueError, TypeError):
                            nested = {}
                        for subkey, subvalue in nested.items():
                            tag = (ExifTags.GPSTAGS if key == 34853 else ExifTags.TAGS).get(
                                subkey, str(subkey)
                            )
                            prefix = "GPS" if key == 34853 else "EXIF"
                            fields.append(_field(f"{prefix}:{tag}", subvalue))
                    else:
                        fields.append(_field(f"EXIF:{ExifTags.TAGS.get(key, str(key))}", value))
        executable = check_dependencies()["exiftool"]
        if executable:
            raw = run_exiftool(executable, ["-j", "-G1", "-a", "-s"], path, cancel)
            try:
                records = json.loads(raw)
                if not isinstance(records, list) or len(records) != 1:
                    raise ValueError
                record = records[0]
                if not isinstance(record, dict):
                    raise ValueError
            except (ValueError, IndexError, TypeError) as exc:
                raise MetaStripError("ExifTool returned invalid metadata.") from exc
            for key, value in record.items():
                if key == "SourceFile" or key.startswith("ExifTool:"):
                    if key.endswith((":Warning", ":Error")):
                        notes.append(
                            "ExifTool reported a structural warning; coverage may be incomplete."
                        )
                    continue
                fields.append(_field(key, value))
        else:
            notes.append("ExifTool is unavailable; inspection uses the limited Pillow scanner.")
        return InspectionResult(path, format_, tuple(fields), tuple(notes))

    def _pdf(self, path: Path, format_: FileFormat, cancel: Event | None) -> InspectionResult:
        pymupdf = _pymupdf()
        fields: list[MetadataField] = []
        with pymupdf.open(path) as document:
            if document.needs_pass or document.metadata.get("encryption"):
                raise UnsupportedFormatError("Encrypted PDFs are not supported.")
            if document.is_repaired:
                raise MetaStripError("Damaged PDFs requiring repair are not supported.")
            if not document.page_count:
                raise MetaStripError("The PDF has no readable pages.")
            if document.page_count > 10000:
                raise MetaStripError("PDFs exceeding 10,000 pages exceed safe verification limits.")
            for page in document:
                check_cancel(cancel)
                if page.rect.width * page.rect.height > 80_000_000:
                    raise MetaStripError("A PDF page exceeds the safe rendering size limit.")
            for name, value in document.metadata.items():
                if value:
                    fields.append(
                        _field(f"PDF:{name}", value, sensitive=name not in {"format", "encryption"})
                    )
            xml = document.get_xml_metadata()
            if xml:
                fields.append(_field("PDF:XMP", xml))
            if document.xref_get_key(-1, "ID")[0] != "null":
                fields.append(_field("PDF:DocumentID", "[document fingerprint present]"))
            fields.append(MetadataField("PDF:Pages", str(document.page_count), "Technical", False))
            if document.embfile_count():
                fields.append(_field("PDF:EmbeddedFiles", document.embfile_count()))
            annotations = sum(1 for page in document for _ in (page.annots() or []))
            if annotations:
                fields.append(_field("PDF:Annotations", annotations, sensitive=False))
            for page_index, page in enumerate(document):
                check_cancel(cancel)
                for annotation in page.annots() or []:
                    for name in ("title", "content", "subject", "creationDate", "modDate", "id"):
                        value = annotation.info.get(name)
                        if value:
                            fields.append(
                                _field(f"PDF:Page{page_index + 1}:Annotation:{name}", value)
                            )
                    if document.xref_get_key(annotation.xref, "RC")[0] != "null":
                        fields.append(
                            _field(
                                f"PDF:Page{page_index + 1}:Annotation:RichText",
                                "[rich text present]",
                            )
                        )
        return InspectionResult(
            path,
            format_,
            tuple(fields),
            (
                "PDF inspection covers document properties, XMP, embedded files "
                "and annotation counts. "
                "Visible content, hidden text, forms, links and arbitrary objects "
                "are not fully audited.",
            ),
        )

    def _video(self, path: Path, format_: FileFormat, cancel: Event | None) -> InspectionResult:
        probe = video_probe(path, cancel)
        fields: list[MetadataField] = []
        technical_tags = {"major_brand", "minor_version", "compatible_brands"}
        containers = [("Container", probe.get("format", {}))]
        containers.extend(
            (f"Stream{index}", stream) for index, stream in enumerate(probe["streams"])
        )
        for prefix, container in containers:
            for name, value in container.get("tags", {}).items():
                # Default generated muxer labels contain no source identity.
                generated = name == "encoder" and str(value).startswith("Lavf")
                generated |= name == "language" and value == "und"
                generated |= name == "handler_name" and value in {"VideoHandler", "SoundHandler"}
                generated |= name == "vendor_id" and value in {"[0][0][0][0]", "FFMP"}
                fields.append(
                    _field(
                        f"{prefix}:{name}",
                        value,
                        sensitive=name not in technical_tags and not generated,
                    )
                )
        return InspectionResult(
            path,
            format_,
            tuple(fields),
            (
                "Video checks cover ffprobe container and stream tags. "
                "Codec payloads, side data and "
                "visible or audible identifying content are not fully audited.",
            ),
        )
