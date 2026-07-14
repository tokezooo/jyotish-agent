"""Deterministic PDF text/OCR ingestion with typed fail-closed boundaries."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from ..research_store import canonical_json
from .models import FrozenModel
from .sources import Sha256, SourceRecord


class IngestionFailure(RuntimeError):
    """Privacy-safe typed ingestion failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class IngestionConfig(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    normalization_version: Literal["doctrine-text-v1"] = "doctrine-text-v1"
    languages: tuple[str, ...] = ("sa", "en")
    ocr_min_confidence: float = Field(default=0.80, ge=0.0, le=1.0)
    render_dpi: int = Field(default=300, ge=150, le=600)
    tesseract_psm: int = Field(default=6, ge=3, le=13)

    @property
    def config_sha256(self) -> str:
        return _hash_payload(self.model_dump(mode="json"))


class ExtractedPage(FrozenModel):
    page_number: int = Field(ge=1)
    text: str


class OcrResult(FrozenModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    language: str


class TextAnchor(FrozenModel):
    kind: Literal["heading", "sutra", "verse"]
    label: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ToolProvenance(FrozenModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class NormalizedPage(FrozenModel):
    page_number: int = Field(ge=1)
    printed_page: int
    language: str = Field(min_length=1)
    text: str
    source_method: Literal["embedded_text", "ocr"]
    confidence: float = Field(ge=0.0, le=1.0)
    admission_status: Literal["admitted", "quarantined_low_confidence"]
    anchors: tuple[TextAnchor, ...]
    normalized_sha256: Sha256


class IngestionArtifact(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    source_sha256: Sha256
    config_sha256: Sha256
    tools: tuple[ToolProvenance, ...]
    pages: tuple[NormalizedPage, ...] = Field(min_length=1)
    normalized_content_sha256: Sha256
    artifact_sha256: Sha256

    @property
    def activation_allowed(self) -> bool:
        return all(page.admission_status == "admitted" for page in self.pages)


class TextExtractor(Protocol):
    tool_name: str
    tool_version: str

    def extract(self, path: Path) -> tuple[ExtractedPage, ...]: ...


class PageRenderer(Protocol):
    tool_name: str
    tool_version: str

    def render(self, path: Path, page_number: int, *, dpi: int) -> bytes: ...


class OcrAdapter(Protocol):
    tool_name: str
    tool_version: str

    def recognize(
        self, image: bytes, *, languages: tuple[str, ...], psm: int
    ) -> OcrResult: ...


class PyPdfExtractor:
    """Embedded-text adapter. Scanned pages are returned empty for OCR."""

    tool_name = "pypdf"

    def __init__(self) -> None:
        try:
            import pypdf
        except ImportError as exc:  # pragma: no cover - dependency is locked
            raise IngestionFailure(
                "PDF_TOOL_UNAVAILABLE", "The configured PDF extractor is unavailable."
            ) from exc
        self._pypdf = pypdf
        self.tool_version = pypdf.__version__

    def extract(self, path: Path) -> tuple[ExtractedPage, ...]:
        try:
            reader = self._pypdf.PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise IngestionFailure(
                    "PDF_ENCRYPTED", "Encrypted PDF sources require a decrypted local copy."
                )
            pages = tuple(
                ExtractedPage(page_number=index, text=page.extract_text() or "")
                for index, page in enumerate(reader.pages, start=1)
            )
        except IngestionFailure:
            raise
        except Exception as exc:
            raise IngestionFailure(
                "PDF_CORRUPT", "The PDF could not be parsed as a supported document."
            ) from exc
        if not pages:
            raise IngestionFailure("PDF_CORRUPT", "The PDF contains no pages.")
        return pages


class PdftoppmRenderer:
    """Raster adapter for scanned pages; bytes remain in memory."""

    tool_name = "pdftoppm"

    def __init__(self, executable: str = "pdftoppm") -> None:
        self.executable = executable
        try:
            result = subprocess.run(
                [executable, "-v"], capture_output=True, check=False, text=True
            )
        except OSError as exc:
            raise IngestionFailure(
                "OCR_UNAVAILABLE", "The configured PDF rasterizer is unavailable."
            ) from exc
        version_text = (result.stderr or result.stdout).splitlines()
        self.tool_version = version_text[0].strip() if version_text else "unknown"

    def render(self, path: Path, page_number: int, *, dpi: int) -> bytes:
        try:
            result = subprocess.run(
                [
                    self.executable,
                    "-f", str(page_number),
                    "-l", str(page_number),
                    "-r", str(dpi),
                    "-png", "-singlefile", str(path), "-",
                ],
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise IngestionFailure(
                "OCR_UNAVAILABLE", "The configured PDF rasterizer is unavailable."
            ) from exc
        if result.returncode != 0 or not result.stdout:
            raise IngestionFailure("OCR_FAILED", "The PDF page could not be rasterized.")
        return result.stdout


class TesseractOcrAdapter:
    """Deterministic TSV adapter preserving an aggregate OCR confidence."""

    tool_name = "tesseract"

    def __init__(self, executable: str = "tesseract") -> None:
        self.executable = executable
        try:
            result = subprocess.run(
                [executable, "--version"], capture_output=True, check=False, text=True
            )
        except OSError as exc:
            raise IngestionFailure(
                "OCR_UNAVAILABLE", "The configured OCR engine is unavailable."
            ) from exc
        lines = result.stdout.splitlines()
        self.tool_version = lines[0].strip() if lines else "unknown"

    def recognize(
        self, image: bytes, *, languages: tuple[str, ...], psm: int
    ) -> OcrResult:
        try:
            result = subprocess.run(
                [
                    self.executable, "stdin", "stdout", "-l", "+".join(languages),
                    "--psm", str(psm), "tsv",
                ],
                input=image,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise IngestionFailure(
                "OCR_UNAVAILABLE", "The configured OCR engine is unavailable."
            ) from exc
        if result.returncode != 0:
            raise IngestionFailure("OCR_FAILED", "OCR did not produce a usable result.")
        try:
            rows = list(
                csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t")
            )
        except (UnicodeDecodeError, csv.Error) as exc:
            raise IngestionFailure("OCR_FAILED", "OCR output was malformed.") from exc
        words: list[tuple[tuple[str, str, str], str, float]] = []
        for row in rows:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                confidence = float(row.get("conf", "-1"))
            except ValueError:
                confidence = -1.0
            words.append(
                (
                    (row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", "")),
                    text,
                    confidence,
                )
            )
        if not words:
            raise IngestionFailure("OCR_FAILED", "OCR returned no text.")
        lines: list[str] = []
        current_key: tuple[str, str, str] | None = None
        current_words: list[str] = []
        for key, text, _confidence in words:
            if current_key is not None and key != current_key:
                lines.append(" ".join(current_words))
                current_words = []
            current_key = key
            current_words.append(text)
        if current_words:
            lines.append(" ".join(current_words))
        valid_confidences = [confidence for _, _, confidence in words if confidence >= 0]
        confidence = (
            sum(valid_confidences) / len(valid_confidences) / 100.0
            if valid_confidences
            else 0.0
        )
        return OcrResult(
            text="\n".join(lines),
            confidence=round(max(0.0, min(1.0, confidence)), 6),
            language="+".join(languages),
        )


class DocumentIngestor:
    def __init__(
        self,
        *,
        extractor: TextExtractor,
        renderer: PageRenderer | None,
        ocr: OcrAdapter | None,
    ) -> None:
        self.extractor = extractor
        self.renderer = renderer
        self.ocr = ocr

    def ingest(
        self, source: SourceRecord, *, root: Path, config: IngestionConfig
    ) -> IngestionArtifact:
        path = self._resolve_source(source, root)
        if path.suffix.casefold() != ".pdf":
            raise IngestionFailure("PDF_UNSUPPORTED", "Only PDF source files are supported.")
        if _sha256_file(path) != source.sha256:
            raise IngestionFailure(
                "SOURCE_HASH_MISMATCH", "Source bytes do not match the manifest hash."
            )
        extracted = self.extractor.extract(path)
        page_numbers = [page.page_number for page in extracted]
        if page_numbers != list(range(1, len(extracted) + 1)):
            raise IngestionFailure(
                "PDF_COORDINATES_INVALID", "Extractor page numbers are not contiguous."
            )

        normalized: list[NormalizedPage] = []
        used_ocr = False
        for page in extracted:
            text = _normalize_text(page.text)
            method: Literal["embedded_text", "ocr"] = "embedded_text"
            confidence = 1.0
            language = "+".join(config.languages)
            if not text:
                if self.renderer is None or self.ocr is None:
                    raise IngestionFailure(
                        "OCR_UNAVAILABLE",
                        "A scanned page requires configured raster and OCR adapters.",
                    )
                used_ocr = True
                image = self.renderer.render(
                    path, page.page_number, dpi=config.render_dpi
                )
                result = self.ocr.recognize(
                    image,
                    languages=config.languages,
                    psm=config.tesseract_psm,
                )
                text = _normalize_text(result.text)
                if not text:
                    raise IngestionFailure("OCR_FAILED", "OCR returned no normalized text.")
                method = "ocr"
                confidence = result.confidence
                language = result.language
            status: Literal["admitted", "quarantined_low_confidence"] = (
                "admitted"
                if method == "embedded_text" or confidence >= config.ocr_min_confidence
                else "quarantined_low_confidence"
            )
            anchors = _extract_anchors(text)
            page_payload = {
                "page_number": page.page_number,
                "printed_page": page.page_number + source.page_offset,
                "language": language,
                "text": text,
                "source_method": method,
                "confidence": confidence,
                "admission_status": status,
                "anchors": [anchor.model_dump(mode="json") for anchor in anchors],
            }
            normalized.append(
                NormalizedPage(
                    **page_payload,
                    normalized_sha256=_hash_payload(page_payload),
                )
            )

        tools = [
            ToolProvenance(name=self.extractor.tool_name, version=self.extractor.tool_version)
        ]
        if used_ocr:
            assert self.renderer is not None and self.ocr is not None
            tools.extend(
                [
                    ToolProvenance(
                        name=self.renderer.tool_name, version=self.renderer.tool_version
                    ),
                    ToolProvenance(name=self.ocr.tool_name, version=self.ocr.tool_version),
                ]
            )
        content_payload = [
            page.model_dump(mode="json", exclude={"normalized_sha256"})
            for page in normalized
        ]
        normalized_content_sha256 = _hash_payload(content_payload)
        artifact_payload = {
            "schema_version": "1.0",
            "source_id": source.source_id,
            "source_sha256": source.sha256,
            "config_sha256": config.config_sha256,
            "tools": [tool.model_dump(mode="json") for tool in tools],
            "pages": [page.model_dump(mode="json") for page in normalized],
            "normalized_content_sha256": normalized_content_sha256,
        }
        return IngestionArtifact(
            **artifact_payload,
            artifact_sha256=_hash_payload(artifact_payload),
        )

    @staticmethod
    def _resolve_source(source: SourceRecord, root: Path) -> Path:
        root = Path(root)
        path = root / source.local_file
        if root.is_symlink() or path.is_symlink():
            raise IngestionFailure("SOURCE_PATH_UNSAFE", "Source path is unsafe.")
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError as exc:
            raise IngestionFailure("SOURCE_PATH_UNSAFE", "Source path is unsafe.") from exc
        if not path.is_file():
            raise IngestionFailure("SOURCE_FILE_MISSING", "Source file is missing.")
        current = root
        for part in source.local_file.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise IngestionFailure("SOURCE_PATH_UNSAFE", "Source path is unsafe.")
        return path


class IngestionCatalog:
    """Idempotency adapter keyed by immutable artifact identity."""

    def __init__(self) -> None:
        self._artifacts: dict[str, IngestionArtifact] = {}

    def register(self, artifact: IngestionArtifact) -> Literal["inserted", "duplicate"]:
        existing = self._artifacts.get(artifact.artifact_sha256)
        if existing is not None:
            if existing != artifact:
                raise IngestionFailure(
                    "ARTIFACT_IDENTITY_CONFLICT",
                    "Artifact identity maps to different normalized content.",
                )
            return "duplicate"
        self._artifacts[artifact.artifact_sha256] = artifact
        return "inserted"

    @property
    def artifacts(self) -> tuple[IngestionArtifact, ...]:
        return tuple(self._artifacts[key] for key in sorted(self._artifacts))


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    collapsed: list[str] = []
    for line in lines:
        if line or not collapsed or collapsed[-1]:
            collapsed.append(line)
    return "\n".join(collapsed)


_SUTRA = re.compile(r"(?im)^(?:s[uū]tra|s[ūu]tram?)\s+(\d+(?:\.\d+)+)\s*$")
_VERSE = re.compile(r"(?im)^(?:verse|śloka|sloka)\s+(\d+(?:\.\d+)*)\s*$")


def _extract_anchors(text: str) -> tuple[TextAnchor, ...]:
    anchors: list[TextAnchor] = []
    first_line_end = text.find("\n")
    if first_line_end < 0:
        first_line_end = len(text)
    first_line = text[:first_line_end]
    if first_line and len(first_line) <= 120 and not _SUTRA.fullmatch(first_line):
        anchors.append(
            TextAnchor(kind="heading", label=first_line, start=0, end=first_line_end)
        )
    for pattern, kind in ((_SUTRA, "sutra"), (_VERSE, "verse")):
        for match in pattern.finditer(text):
            anchors.append(
                TextAnchor(
                    kind=kind,
                    label=match.group(1),
                    start=match.start(),
                    end=match.end(),
                )
            )
    return tuple(sorted(anchors, key=lambda item: (item.start, item.kind, item.label)))


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
