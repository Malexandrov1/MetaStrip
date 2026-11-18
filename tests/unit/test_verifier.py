"""Content checks must retain native precision and rendered transparency."""

from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from app.core.inspector import MetadataInspector
from app.core.models import CancelledError, ProcessingOptions, VerificationState
from app.core.verifier import Verifier, image_fingerprint


def test_changed_high_bit_depth_samples_fail_verification(tmp_path: Path) -> None:
    source = tmp_path / "original.png"
    output = tmp_path / "tampered.png"
    Image.new("I;16", (8, 8), 1000).save(source)
    Image.new("I;16", (8, 8), 1001).save(output)
    result = Verifier().verify(
        MetadataInspector().inspect(source), output, ProcessingOptions(tmp_path)
    )
    assert result.state == VerificationState.FAILED


def test_changed_palette_transparency_fails_verification(tmp_path: Path) -> None:
    source = tmp_path / "original.png"
    output = tmp_path / "tampered.png"
    image = Image.new("P", (8, 8), 0)
    image.putpalette([10, 20, 30, 180, 190, 200] + [0] * 762)
    image.save(source, transparency=0)
    image.save(output, transparency=1)
    result = Verifier().verify(
        MetadataInspector().inspect(source), output, ProcessingOptions(tmp_path)
    )
    assert result.state == VerificationState.FAILED
    assert result.warnings == ("Decoded pixels or display orientation changed.",)


def test_large_image_fingerprint_covers_last_band_and_can_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.png"
    changed = tmp_path / "changed.png"
    image = Image.new("RGBA", (2048, 1600), (40, 50, 60, 170))
    image.save(source)
    image.putpixel((2047, 1599), (40, 50, 60, 171))
    image.save(changed)
    assert image_fingerprint(source) != image_fingerprint(changed)

    cancel = Event()
    original_crop = Image.Image.crop

    def crop_then_cancel(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
        band = original_crop(image, box)
        cancel.set()
        return band

    monkeypatch.setattr(Image.Image, "crop", crop_then_cancel)
    with pytest.raises(CancelledError):
        image_fingerprint(source, cancel)
