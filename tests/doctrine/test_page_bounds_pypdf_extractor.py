from __future__ import annotations

from pathlib import Path

import pytest

from jyotish_agent.doctrine.ingestion import (
    IngestionFailure,
    PageBoundsPyPdfExtractor,
    _origin_within_bounds,
    _transform_pdf_text_origin,
)


def _write_pdf(path: Path, content_streams: tuple[bytes, ...]) -> None:
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = pypdf.PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for content in content_streams:
        page = writer.add_blank_page(width=100, height=100)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_ref}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(content)
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)


def test_page_bounds_extractor_splits_generated_two_up_stream_deterministically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic-two-up.pdf"
    shared = (
        b"q 1 0 0 1 25 50 cm BT /F1 12 Tf (LEFT-ONLY) Tj ET Q "
        b"q 1 0 0 1 125 50 cm BT /F1 12 Tf (RIGHT-ONLY) Tj ET Q"
    )
    shifted = (
        b"q 1 0 0 1 -100 0 cm "
        b"q 1 0 0 1 25 50 cm BT /F1 12 Tf (LEFT-ONLY) Tj ET Q "
        b"q 1 0 0 1 125 50 cm BT /F1 12 Tf (RIGHT-ONLY) Tj ET Q Q"
    )
    _write_pdf(path, (shared, shifted))

    extractor = PageBoundsPyPdfExtractor()
    first = extractor.extract(path)
    second = extractor.extract(path)

    assert first == second
    assert [page.text.strip() for page in first] == ["LEFT-ONLY", "RIGHT-ONLY"]
    assert extractor.tool_name == "pypdf-page-bounds"


def test_text_origin_uses_full_affine_transform_including_rotation() -> None:
    # Text-space (10, 20), then a clockwise quarter-turn plus translation.
    assert _transform_pdf_text_origin(
        tm=(1.0, 0.0, 0.0, 1.0, 10.0, 20.0),
        cm=(0.0, -1.0, 1.0, 0.0, -30.0, 40.0),
    ) == (-10.0, 30.0)


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ((0.0, 0.0), True),
        ((99.999, 99.999), True),
        ((100.0, 50.0), False),
        ((50.0, 100.0), False),
        ((-0.001, 50.0), False),
    ],
)
def test_page_bounds_use_stable_half_open_upper_edges(
    origin: tuple[float, float], expected: bool
) -> None:
    assert _origin_within_bounds(origin, (0.0, 0.0, 100.0, 100.0)) is expected


def test_nonempty_stream_with_no_in_bounds_text_fails_typed(tmp_path: Path) -> None:
    path = tmp_path / "out-of-bounds.pdf"
    _write_pdf(path, (b"BT /F1 12 Tf 125 50 Td (SIBLING) Tj ET",))

    with pytest.raises(IngestionFailure) as raised:
        PageBoundsPyPdfExtractor().extract(path)

    assert raised.value.code == "PDF_TEXT_OUT_OF_BOUNDS"
    assert str(path) not in str(raised.value)


def test_blank_page_remains_available_for_explicit_ocr_fallback(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as handle:
        writer.write(handle)

    assert PageBoundsPyPdfExtractor().extract(path)[0].text == ""


def test_page_bounds_adapter_preserves_typed_corrupt_and_encrypted_errors(
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf")
    with pytest.raises(IngestionFailure) as corrupt_error:
        PageBoundsPyPdfExtractor().extract(corrupt)
    assert corrupt_error.value.code == "PDF_CORRUPT"

    pypdf = pytest.importorskip("pypdf")
    encrypted = tmp_path / "encrypted.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with encrypted.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(IngestionFailure) as encrypted_error:
        PageBoundsPyPdfExtractor().extract(encrypted)
    assert encrypted_error.value.code == "PDF_ENCRYPTED"
