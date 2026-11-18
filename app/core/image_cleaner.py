"""Lossless metadata filtering: image bitstreams are never recompressed."""

import struct
import zlib
from pathlib import Path

from PIL import Image

from app.core.jpeg_structure import jpeg_frame_info, jpeg_segments
from app.core.models import FileFormat, MetaStripError


def _fail() -> None:
    raise MetaStripError("Malformed image structure; no sanitized copy was created.")


def clean_png(data: bytes, preserve_icc: bool) -> bytes:
    output = bytearray(data[:8])
    position = 8
    keep = {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"gAMA",
        b"cHRM",
        b"sRGB",
        b"sBIT",
        b"bKGD",
        b"pHYs",
    }
    if preserve_icc:
        keep.add(b"iCCP")
    found_end = False
    while position + 12 <= len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        end = position + length + 12
        if end > len(data):
            _fail()
        kind = data[position + 4 : position + 8]
        payload = data[position + 8 : end - 4]
        if zlib.crc32(kind + payload) != int.from_bytes(data[end - 4 : end], "big"):
            _fail()
        if kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise MetaStripError("Animated PNG files are not supported for safe sanitization.")
        if kind not in keep and not kind[0] & 32:
            raise MetaStripError("Unknown critical PNG chunk; safe processing is unavailable.")
        if kind in keep:
            output.extend(data[position:end])
        position = end
        if kind == b"IEND":
            found_end = True
            break
    if not found_end:
        _fail()
    return bytes(output)


def clean_jpeg(data: bytes, preserve_icc: bool, orientation: int) -> bytes:
    output = bytearray(b"\xff\xd8")
    if orientation != 1:
        # Rebuild the orientation tag without copying the original EXIF segment.
        tiff = b"II*\x00\x08\x00\x00\x00\x01\x00"
        tiff += struct.pack("<HHI", 274, 3, 1) + struct.pack("<H", orientation) + b"\x00\x00"
        tiff += b"\x00\x00\x00\x00"
        block = b"Exif\x00\x00" + tiff
        output += b"\xff\xe1" + struct.pack(">H", len(block) + 2) + block
    for marker, start, end, payload_start in jpeg_segments(data):
        if marker is None or marker == 0xD9:
            output.extend(data[start:end])
            continue
        payload = data[payload_start:end]
        if marker == 0xE0 and payload.startswith(b"JFIF\x00") and len(payload) >= 14:
            # Zero the thumbnail dimensions and omit its pixels.
            block = payload[:12] + b"\x00\x00"
            output += b"\xff\xe0" + struct.pack(">H", len(block) + 2) + block
        elif marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00") and preserve_icc:
            output.extend(data[start:end])
        elif marker == 0xEE and payload.startswith(b"Adobe"):
            output += b"\xff\xee" + struct.pack(">H", 14) + payload[:12]
        elif not (0xE0 <= marker <= 0xEF or marker == 0xFE):
            output.extend(data[start:end])
    return bytes(output)


def clean_webp(data: bytes, preserve_icc: bool) -> bytes:
    if int.from_bytes(data[4:8], "little") + 8 > len(data):
        _fail()
    output = bytearray(b"WEBP")
    position = 12
    limit = int.from_bytes(data[4:8], "little") + 8
    while position + 8 <= limit:
        kind = data[position : position + 4]
        length = int.from_bytes(data[position + 4 : position + 8], "little")
        end = position + 8 + length + length % 2
        if end > limit:
            _fail()
        payload = bytearray(data[position + 8 : position + 8 + length])
        if kind in {b"ANIM", b"ANMF"}:
            raise MetaStripError("Animated WebP files are not supported for safe sanitization.")
        if kind == b"VP8X":
            if length != 10 or payload[0] & 2:
                _fail()
            payload[0] &= ~0x0C  # EXIF and XMP feature flags.
            if not preserve_icc:
                payload[0] &= ~0x20
        if kind in {b"VP8 ", b"VP8L", b"ALPH", b"VP8X"} or (kind == b"ICCP" and preserve_icc):
            output += kind + length.to_bytes(4, "little") + payload
            if length % 2:
                output += b"\x00"
        position = end
    if position != limit:
        _fail()
    return b"RIFF" + len(output).to_bytes(4, "little") + output


def clean_image(source: Path, output: Path, format_: FileFormat, preserve_icc: bool) -> None:
    if source.stat().st_size > 512 * 1024 * 1024:
        raise MetaStripError("Images larger than 512 MiB exceed the safe processing limit.")
    data = source.read_bytes()
    frames = jpeg_frame_info(data) if format_ == FileFormat.JPEG else None
    with Image.open(source) as image:
        if frames and frames.declared_frames > 1 and not frames.stale_index:
            raise MetaStripError(
                "Multi-picture JPEG contains present or partially present additional image "
                "data; safe sanitization is not supported."
            )
        if getattr(image, "n_frames", 1) != 1 and not (frames and frames.stale_index):
            raise MetaStripError("Multi-frame images are not supported for safe sanitization.")
        image.load()
        orientation = int(image.getexif().get(274, 1))
        if orientation not in range(1, 9):
            raise MetaStripError("The image has an invalid display orientation.")
    if format_ == FileFormat.JPEG:
        cleaned = clean_jpeg(data, preserve_icc, orientation)
    elif format_ == FileFormat.PNG:
        if orientation != 1:
            raise MetaStripError("Oriented PNG files require normalization before sanitization.")
        cleaned = clean_png(data, preserve_icc)
    else:
        if orientation != 1:
            raise MetaStripError("Oriented WebP files require normalization before sanitization.")
        cleaned = clean_webp(data, preserve_icc)
    output.write_bytes(cleaned)
