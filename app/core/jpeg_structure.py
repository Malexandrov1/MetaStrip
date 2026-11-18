"""JPEG codestream boundaries and conservative MPF index validation."""

import struct
from collections.abc import Iterator
from dataclasses import dataclass

from app.core.models import MetaStripError


def jpeg_segments(data: bytes) -> Iterator[tuple[int | None, int, int, int]]:
    """Yield marker, start, end and payload offset; None denotes encoded scan data.

    EOI is recognized structurally, never by searching inside EXIF or compressed
    bytes. Only the first complete codestream is traversed.
    """
    if not data.startswith(b"\xff\xd8"):
        raise MetaStripError("Invalid JPEG start marker.")
    position = 2
    while position < len(data):
        start = position
        if data[position] != 255:
            break
        while position < len(data) and data[position] == 255:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker == 0xD9:
            yield marker, start, position, position
            return
        if marker in {0, 0xD8} or 0xD0 <= marker <= 0xD7 or position + 2 > len(data):
            break
        length = int.from_bytes(data[position : position + 2], "big")
        end = position + length
        if length < 2 or end > len(data):
            break
        yield marker, start, end, position + 2
        position = end
        if marker != 0xDA:
            continue
        scan_start = position
        while (position := data.find(b"\xff", position)) != -1:
            following = position + 1
            while following < len(data) and data[following] == 255:
                following += 1
            if following >= len(data):
                break
            if data[following] == 0 or 0xD0 <= data[following] <= 0xD7:
                position = following + 1
                continue
            yield None, scan_start, position, position
            break
        else:
            break
    raise MetaStripError("Malformed or incomplete JPEG codestream.")


@dataclass(frozen=True)
class JpegFrameInfo:
    declared_frames: int = 1
    stale_index: bool = False


STALE_MPF_WARNING = (
    "The MPF index declares additional images outside this file, but the complete "
    "primary JPEG ends at EOF. Stale MPF references are removed; only the primary "
    "image is present and verified."
)


def jpeg_frame_info(data: bytes) -> JpegFrameInfo:
    """Distinguish absent MPF references from present or partly present images.

    ExifTool's sample repository retains original APP2 indexes after replacing the
    primary image and removing its trailer. Accept that case only when every
    secondary entry starts beyond EOF and no bytes follow the primary EOI.
    """
    indexes = []
    primary_end = 0
    for marker, _start, end, payload_start in jpeg_segments(data):
        if marker == 0xE2 and data[payload_start : payload_start + 4] == b"MPF\x00":
            indexes.append((payload_start + 4, data[payload_start + 4 : end]))
        if marker == 0xD9:
            primary_end = end
    if not indexes:
        return JpegFrameInfo()
    if len(indexes) != 1:
        raise MetaStripError("Multiple MPF indexes cannot be safely sanitized.")
    base, tiff = indexes[0]
    try:
        if tiff[:4] == b"II*\x00":
            order = "<"
        elif tiff[:4] == b"MM\x00*":
            order = ">"
        else:
            raise ValueError
        offset = struct.unpack_from(order + "I", tiff, 4)[0]
        if offset < 8:
            raise ValueError
        count = struct.unpack_from(order + "H", tiff, offset)[0]
        if offset + 2 + count * 12 + 4 > len(tiff):
            raise ValueError
        tags = {}
        for index in range(count):
            tag, kind, size, value = struct.unpack_from(
                order + "HHII", tiff, offset + 2 + index * 12
            )
            if tag in {0xB001, 0xB002}:
                if tag in tags:
                    raise ValueError
                tags[tag] = (kind, size, value)
        kind, size, frames = tags[0xB001]
        entry_kind, entry_bytes, entry_offset = tags[0xB002]
        if kind != 4 or size != 1 or frames < 1 or entry_kind != 7:
            raise ValueError
        if entry_bytes != frames * 16 or entry_offset + entry_bytes > len(tiff):
            raise ValueError
        entries = [
            struct.unpack_from(order + "IIIHH", tiff, entry_offset + index * 16)
            for index in range(frames)
        ]
        if entries[0][2] != 0 or any(entry[1] == 0 for entry in entries):
            raise ValueError
        if any((entry[0] >> 24) & 7 for entry in entries):
            raise ValueError
    except (KeyError, ValueError, struct.error) as exc:
        raise MetaStripError("Malformed MPF index; safe frame detection is unavailable.") from exc
    stale = (
        frames > 1
        and primary_end == len(data)
        and all(entry[2] > 0 and base + entry[2] >= len(data) for entry in entries[1:])
    )
    return JpegFrameInfo(frames, stale)
