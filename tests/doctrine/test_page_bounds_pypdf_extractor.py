from __future__ import annotations

from pathlib import Path

import pytest

from jyotish_agent.doctrine.ingestion import (
    IngestionFailure,
    PageBoundsPyPdfExtractor,
    _origin_within_bounds,
    _transform_pdf_text_origin,
)


def _write_pdf(
    path: Path,
    content_streams: tuple[bytes, ...],
    *,
    crop_bounds: tuple[float, float, float, float] | None = None,
) -> None:
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        RectangleObject,
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
        if crop_bounds is not None:
            page.cropbox = RectangleObject(crop_bounds)
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


def _write_form_pdf(
    path: Path,
    *,
    page_prefix: bytes = b"",
    form_content: bytes = b"BT /F1 12 Tf (FORM-TEXT) Tj ET",
    placement: tuple[float, float] = (25, 50),
    page_suffix: bytes = b"",
    crop_bounds: tuple[float, float, float, float] | None = None,
) -> None:
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        RectangleObject,
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
    form = DecodedStreamObject()
    form.set_data(form_content)
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [FloatObject(0), FloatObject(0), FloatObject(80), FloatObject(40)]
            ),
            NameObject("/Resources"): DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): font_ref}
                    )
                }
            ),
        }
    )
    form_ref = writer._add_object(form)
    page = writer.add_blank_page(width=100, height=100)
    if crop_bounds is not None:
        page.cropbox = RectangleObject(crop_bounds)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_ref}
            ),
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Fm1"): form_ref}
            )
        }
    )
    content = DecodedStreamObject()
    x, y = placement
    invocation = f"q 1 0 0 1 {x:g} {y:g} cm /Fm1 Do Q".encode()
    content.set_data(page_prefix + invocation + page_suffix)
    page[NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as handle:
        writer.write(handle)


def _write_nested_form_pdf(
    path: Path,
    *,
    page_prefix: bytes = b"",
    placements: tuple[tuple[float, float], ...] = ((25, 50), (125, 50)),
    crop_bounds: tuple[float, float, float, float] | None = None,
) -> None:
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        RectangleObject,
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
    inner = DecodedStreamObject()
    inner.set_data(b"BT /F1 12 Tf (INNER-TEXT) Tj ET")
    inner.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [FloatObject(0), FloatObject(0), FloatObject(80), FloatObject(40)]
            ),
            NameObject("/Resources"): DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): font_ref}
                    )
                }
            ),
        }
    )
    inner_ref = writer._add_object(inner)
    outer = DecodedStreamObject()
    outer.set_data(b"/Inner Do")
    outer.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [FloatObject(0), FloatObject(0), FloatObject(80), FloatObject(40)]
            ),
            NameObject("/Resources"): DictionaryObject(
                {
                    NameObject("/XObject"): DictionaryObject(
                        {NameObject("/Inner"): inner_ref}
                    )
                }
            ),
        }
    )
    outer_ref = writer._add_object(outer)
    page = writer.add_blank_page(width=100, height=100)
    if crop_bounds is not None:
        page.cropbox = RectangleObject(crop_bounds)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Outer"): outer_ref}
            )
        }
    )
    content = DecodedStreamObject()
    invocations = b" ".join(
        f"q 1 0 0 1 {x:g} {y:g} cm /Outer Do Q".encode()
        for x, y in placements
    )
    content.set_data(page_prefix + invocations)
    page[NameObject("/Contents")] = writer._add_object(content)
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


def test_page_bounds_extractor_preserves_default_form_xobject_text_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "form-xobject.pdf"
    _write_form_pdf(path)

    pypdf = pytest.importorskip("pypdf")
    default = pypdf.PdfReader(path, strict=True).pages[0].extract_text()
    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert default.strip() == "FORM-TEXT"
    assert bounded == default


def test_page_bounds_extractor_tracks_nested_form_placement_for_siblings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested-form-xobject.pdf"
    _write_nested_form_pdf(path)

    pypdf = pytest.importorskip("pypdf")
    default = pypdf.PdfReader(path, strict=True).pages[0].extract_text()
    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert default.count("INNER-TEXT") == 2
    assert bounded.count("INNER-TEXT") == 1
    assert bounded.strip() == "INNER-TEXT"


def test_page_bounds_extractor_preserves_default_single_text_object_tstar_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "multiline.pdf"
    _write_pdf(
        path,
        (
            b"BT /F1 12 Tf 3 TL 1 0 0 1 25 70 Tm "
            b"(HELLO) Tj T* (WORLD) Tj ET",
        ),
        crop_bounds=(10, 10, 90, 90),
    )

    pypdf = pytest.importorskip("pypdf")
    default = pypdf.PdfReader(path, strict=True).pages[0].extract_text()
    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert default == "HELLO\nWORLD"
    assert bounded == default


def test_page_bounds_extractor_filters_sibling_inside_one_text_object(
    tmp_path: Path,
) -> None:
    path = tmp_path / "single-text-object-sibling.pdf"
    _write_pdf(
        path,
        (
            b"BT /F1 12 Tf 1 0 0 1 25 50 Tm (VISIBLE) Tj "
            b"1 0 0 1 125 50 Tm (SIBLING) Tj ET",
        ),
    )

    pypdf = pytest.importorskip("pypdf")
    default = pypdf.PdfReader(path, strict=True).pages[0].extract_text()
    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert "VISIBLE" in default and "SIBLING" in default
    assert bounded.strip() == "VISIBLE"
    assert "SIBLING" not in bounded


@pytest.mark.parametrize("shorthand", [b"(SIBLING) '", b'0 0 (SIBLING) "'])
def test_page_bounds_extractor_applies_implicit_tstar_before_shorthand_text(
    tmp_path: Path, shorthand: bytes
) -> None:
    path = tmp_path / "shorthand-sibling.pdf"
    _write_pdf(
        path,
        (
            b"BT /F1 12 Tf 10 TL 1 0 0 1 25 70 Tm (VISIBLE) Tj "
            + shorthand
            + b" ET",
        ),
        crop_bounds=(10, 10, 90, 90),
    )

    pypdf = pytest.importorskip("pypdf")
    default = pypdf.PdfReader(path, strict=True).pages[0].extract_text()
    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert "VISIBLE" in default and "SIBLING" in default
    assert bounded.strip() == "VISIBLE"
    assert "SIBLING" not in bounded


@pytest.mark.parametrize("shorthand", [b"(SIBLING) '", b'0 0 (SIBLING) "'])
def test_page_bounds_extractor_tracks_td_leading_for_shorthand_text(
    tmp_path: Path, shorthand: bytes
) -> None:
    path = tmp_path / "td-shorthand-sibling.pdf"
    _write_pdf(
        path,
        (
            b"BT /F1 12 Tf 1 0 0 1 25 70 Tm 0 -10 TD "
            b"(VISIBLE) Tj "
            + shorthand
            + b" ET",
        ),
    )

    pypdf = pytest.importorskip("pypdf")
    default = pypdf.PdfReader(path, strict=True).pages[0].extract_text()
    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert "VISIBLE" in default and "SIBLING" in default
    assert bounded.strip() == "VISIBLE"
    assert "SIBLING" not in bounded


def test_page_bounds_extractor_excludes_text_raised_above_crop(tmp_path: Path) -> None:
    path = tmp_path / "positive-text-rise.pdf"
    _write_pdf(
        path,
        (b"BT /F1 12 Tf 20 Ts 1 0 0 1 25 85 Tm (RISEN-OUT) Tj ET",),
        crop_bounds=(10, 10, 90, 90),
    )

    with pytest.raises(IngestionFailure) as raised:
        PageBoundsPyPdfExtractor().extract(path)

    assert raised.value.code == "PDF_TEXT_OUT_OF_BOUNDS"


def test_page_bounds_extractor_includes_text_lowered_into_crop(tmp_path: Path) -> None:
    path = tmp_path / "negative-text-rise.pdf"
    _write_pdf(
        path,
        (b"BT /F1 12 Tf -20 Ts 1 0 0 1 25 95 Tm (LOWERED-IN) Tj ET",),
        crop_bounds=(10, 10, 90, 90),
    )

    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert bounded.strip() == "LOWERED-IN"


def test_page_bounds_extractor_restores_text_rise_across_graphics_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "saved-text-rise.pdf"
    _write_pdf(
        path,
        (
            b"BT /F1 12 Tf 20 Ts q -20 Ts Q "
            b"1 0 0 1 25 85 Tm (RESTORED-RISEN-OUT) Tj ET",
        ),
        crop_bounds=(10, 10, 90, 90),
    )

    with pytest.raises(IngestionFailure) as raised:
        PageBoundsPyPdfExtractor().extract(path)

    assert raised.value.code == "PDF_TEXT_OUT_OF_BOUNDS"


def test_page_bounds_extractor_inherits_positive_parent_text_rise_in_form(
    tmp_path: Path,
) -> None:
    path = tmp_path / "form-positive-text-rise.pdf"
    _write_form_pdf(
        path,
        page_prefix=b"BT /F1 12 Tf 20 Ts ET ",
        placement=(25, 85),
        crop_bounds=(10, 10, 90, 90),
    )

    with pytest.raises(IngestionFailure) as raised:
        PageBoundsPyPdfExtractor().extract(path)

    assert raised.value.code == "PDF_TEXT_OUT_OF_BOUNDS"


def test_page_bounds_extractor_inherits_negative_parent_text_rise_in_form(
    tmp_path: Path,
) -> None:
    path = tmp_path / "form-negative-text-rise.pdf"
    _write_form_pdf(
        path,
        page_prefix=b"BT /F1 12 Tf -20 Ts ET ",
        placement=(25, 95),
        crop_bounds=(10, 10, 90, 90),
    )

    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert bounded.strip() == "FORM-TEXT"


def test_page_bounds_extractor_inherits_parent_leading_for_form_quote(
    tmp_path: Path,
) -> None:
    path = tmp_path / "form-parent-leading.pdf"
    _write_form_pdf(
        path,
        page_prefix=b"BT /F1 12 Tf 100 TL ET ",
        form_content=b"BT /F1 12 Tf (FORM-QUOTE) ' ET",
        placement=(25, 85),
        crop_bounds=(10, 10, 90, 90),
    )

    with pytest.raises(IngestionFailure) as raised:
        PageBoundsPyPdfExtractor().extract(path)

    assert raised.value.code == "PDF_TEXT_OUT_OF_BOUNDS"


def test_page_bounds_extractor_does_not_leak_form_text_state_after_do(
    tmp_path: Path,
) -> None:
    path = tmp_path / "form-text-state-isolation.pdf"
    _write_form_pdf(
        path,
        form_content=b"BT /F1 12 Tf 20 Ts (FORM-LOCAL) Tj ET",
        placement=(25, 25),
        page_suffix=b" BT /F1 12 Tf 1 0 0 1 25 85 Tm (AFTER-FORM) Tj ET",
        crop_bounds=(10, 10, 90, 90),
    )

    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert "FORM-LOCAL" in bounded
    assert "AFTER-FORM" in bounded


def test_page_bounds_extractor_inherits_parent_rise_through_nested_forms(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested-form-parent-rise.pdf"
    _write_nested_form_pdf(
        path,
        page_prefix=b"BT 20 Ts ET ",
        placements=((25, 85),),
        crop_bounds=(10, 10, 90, 90),
    )

    with pytest.raises(IngestionFailure) as raised:
        PageBoundsPyPdfExtractor().extract(path)

    assert raised.value.code == "PDF_TEXT_OUT_OF_BOUNDS"


def test_page_bounds_extractor_preserves_default_separate_text_objects(
    tmp_path: Path,
) -> None:
    path = tmp_path / "separate-text-objects.pdf"
    _write_pdf(
        path,
        (
            b"BT /F1 12 Tf 1 0 0 1 25 70 Tm (HELLO) Tj ET "
            b"BT /F1 12 Tf 1 0 0 1 25 30 Tm (WORLD) Tj ET",
        ),
        crop_bounds=(10, 10, 90, 90),
    )

    pypdf = pytest.importorskip("pypdf")
    default = pypdf.PdfReader(path, strict=True).pages[0].extract_text()
    bounded = PageBoundsPyPdfExtractor().extract(path)[0].text

    assert default == "HELLO\nWORLD"
    assert bounded == default


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
