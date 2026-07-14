from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jyotish_agent.doctrine.ingestion import (
    DocumentIngestor,
    ExtractedPage,
    IngestionCatalog,
    IngestionConfig,
    IngestionFailure,
    OcrResult,
    PyPdfExtractor,
)
from jyotish_agent.doctrine.sources import SourceRecord


ROOT = Path(__file__).parents[2]
GOLDEN = ROOT / "tests/fixtures/doctrine/mixed-page-extraction.json"


class FakeExtractor:
    tool_name = "fake-pdf"
    tool_version = "1.2.3"

    def __init__(self, pages: tuple[ExtractedPage, ...]) -> None:
        self.pages = pages

    def extract(self, _path: Path) -> tuple[ExtractedPage, ...]:
        return self.pages


class FakeRenderer:
    tool_name = "fake-renderer"
    tool_version = "2.0.0"

    def render(self, _path: Path, page_number: int, *, dpi: int) -> bytes:
        assert dpi == 300
        return f"page:{page_number}".encode()


class FakeOcr:
    tool_name = "fake-tesseract"
    tool_version = "5.4.0"

    def recognize(self, image: bytes, *, languages: tuple[str, ...], psm: int) -> OcrResult:
        assert image == b"page:2"
        assert languages == ("sa", "en")
        assert psm == 6
        return OcrResult(
            text="Chapter Two  \r\nSutra 2.3\r\nMixed OCR text.\r\n",
            confidence=0.72,
            language="sa+en",
        )


def _source(file_bytes: bytes, **updates: object) -> SourceRecord:
    payload: dict[str, object] = {
        "source_id": "mixed_source_v1",
        "title": "Mixed source fixture",
        "author_or_commentator": "Fixture author",
        "translator_editor": "Fixture editor",
        "edition": "Fixture edition 1",
        "publisher": "Fixture publisher",
        "year": 2026,
        "isbn": None,
        "languages": ["sa", "en"],
        "domain": "jaimini",
        "school_role": "baseline",
        "license_class": "copyrighted_local",
        "local_file": "jaimini/mixed/source.pdf",
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
        "page_offset": 10,
        "scan_quality": "good",
        "ocr_required": True,
        "ocr_status": "required",
    }
    payload.update(updates)
    return SourceRecord.model_validate(payload)


def _write_source(tmp_path: Path, content: bytes = b"fixture-pdf") -> tuple[Path, SourceRecord]:
    root = tmp_path / "private_sources"
    source = _source(content)
    path = root / source.local_file
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return root, source


def _ingestor() -> DocumentIngestor:
    return DocumentIngestor(
        extractor=FakeExtractor(
            (
                ExtractedPage(
                    page_number=1,
                    text="अध्याय एक  \r\nSūtra 1.1\r\nMixed Sanskrit and English.\r\n",
                ),
                ExtractedPage(page_number=2, text=""),
            )
        ),
        renderer=FakeRenderer(),
        ocr=FakeOcr(),
    )


def test_mixed_text_and_ocr_ingestion_is_byte_stable_and_round_trips_coordinates(
    tmp_path: Path,
) -> None:
    root, source = _write_source(tmp_path)
    config = IngestionConfig(
        languages=("sa", "en"),
        ocr_min_confidence=0.80,
        render_dpi=300,
        tesseract_psm=6,
    )

    first = _ingestor().ingest(source, root=root, config=config)
    second = _ingestor().ingest(source, root=root, config=config)

    assert first == second
    assert first.artifact_sha256 == second.artifact_sha256
    assert first.normalized_content_sha256 == second.normalized_content_sha256
    assert [page.page_number for page in first.pages] == [1, 2]
    assert [page.printed_page for page in first.pages] == [11, 12]
    assert first.pages[0].text == "अध्याय एक\nSūtra 1.1\nMixed Sanskrit and English."
    assert first.pages[0].source_method == "embedded_text"
    assert first.pages[0].admission_status == "admitted"
    assert first.pages[1].source_method == "ocr"
    assert first.pages[1].admission_status == "quarantined_low_confidence"
    assert first.pages[1].confidence == 0.72
    assert first.activation_allowed is False
    assert [(anchor.kind, anchor.label, anchor.start, anchor.end) for anchor in first.pages[0].anchors] == [
        ("heading", "अध्याय एक", 0, 9),
        ("sutra", "1.1", 10, 19),
    ]
    assert [(anchor.kind, anchor.label) for anchor in first.pages[1].anchors] == [
        ("heading", "Chapter Two"),
        ("sutra", "2.3"),
    ]

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    projection = {
        "pages": [
            {
                "page_number": page.page_number,
                "printed_page": page.printed_page,
                "text": page.text,
                "source_method": page.source_method,
                "confidence": page.confidence,
                "admission_status": page.admission_status,
                "anchors": [anchor.model_dump(mode="json") for anchor in page.anchors],
            }
            for page in first.pages
        ]
    }
    assert projection == golden


def test_ingestion_records_exact_tool_and_config_provenance(tmp_path: Path) -> None:
    root, source = _write_source(tmp_path)
    artifact = _ingestor().ingest(
        source,
        root=root,
        config=IngestionConfig(languages=("sa", "en")),
    )
    assert [(tool.name, tool.version) for tool in artifact.tools] == [
        ("fake-pdf", "1.2.3"),
        ("fake-renderer", "2.0.0"),
        ("fake-tesseract", "5.4.0"),
    ]
    assert len(artifact.config_sha256) == 64
    assert all(len(page.normalized_sha256) == 64 for page in artifact.pages)


def test_reingestion_catalog_deduplicates_by_artifact_identity(tmp_path: Path) -> None:
    root, source = _write_source(tmp_path)
    artifact = _ingestor().ingest(
        source,
        root=root,
        config=IngestionConfig(languages=("sa", "en")),
    )
    catalog = IngestionCatalog()
    assert catalog.register(artifact) == "inserted"
    assert catalog.register(artifact) == "duplicate"
    assert catalog.artifacts == (artifact,)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"not a pdf", "PDF_CORRUPT"),
    ],
)
def test_real_pdf_adapter_returns_typed_corrupt_error(
    tmp_path: Path, content: bytes, expected: str
) -> None:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(content)
    with pytest.raises(IngestionFailure) as raised:
        PyPdfExtractor().extract(path)
    assert raised.value.code == expected
    assert str(tmp_path) not in str(raised.value)


def test_real_pdf_adapter_returns_typed_encrypted_error(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "encrypted.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with path.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(IngestionFailure) as raised:
        PyPdfExtractor().extract(path)
    assert raised.value.code == "PDF_ENCRYPTED"
    assert "secret" not in str(raised.value)
    assert str(path) not in str(raised.value)


def test_ingestor_rejects_unsupported_file_before_extraction(tmp_path: Path) -> None:
    content = b"not-pdf"
    root = tmp_path / "private_sources"
    source = _source(content, local_file="jaimini/mixed/source.txt")
    path = root / source.local_file
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    with pytest.raises(IngestionFailure) as raised:
        _ingestor().ingest(source, root=root, config=IngestionConfig())
    assert raised.value.code == "PDF_UNSUPPORTED"


def test_missing_ocr_adapter_fails_typed_instead_of_admitting_blank_page(
    tmp_path: Path,
) -> None:
    root, source = _write_source(tmp_path)
    ingestor = DocumentIngestor(
        extractor=FakeExtractor((ExtractedPage(page_number=1, text=""),)),
        renderer=None,
        ocr=None,
    )
    with pytest.raises(IngestionFailure) as raised:
        ingestor.ingest(source, root=root, config=IngestionConfig())
    assert raised.value.code == "OCR_UNAVAILABLE"
