"""Deterministic PDF text/OCR ingestion with typed fail-closed boundaries."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import subprocess
import unicodedata
from collections.abc import Sequence
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


PdfBounds = tuple[float, float, float, float]
PdfMatrix = tuple[float, float, float, float, float, float]
_IDENTITY_PDF_MATRIX: PdfMatrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_PDF_TEXT_SHOW_OPERATORS = {b"Tj", b"TJ", b"'", b'"'}


def _transform_pdf_text_origin(
    *, tm: Sequence[float], cm: Sequence[float]
) -> tuple[float, float]:
    """Return the text origin after applying the current transformation matrix."""

    return (
        float(tm[4]) * float(cm[0])
        + float(tm[5]) * float(cm[2])
        + float(cm[4]),
        float(tm[4]) * float(cm[1])
        + float(tm[5]) * float(cm[3])
        + float(cm[5]),
    )


def _origin_within_bounds(
    origin: tuple[float, float], bounds: PdfBounds
) -> bool:
    """Use closed lower and open upper edges for deterministic crop ownership."""

    x, y = origin
    left, bottom, right, top = bounds
    return left <= x < right and bottom <= y < top


def _compose_pdf_matrices(local: Sequence[float], parent: Sequence[float]) -> PdfMatrix:
    """Compose PDF affine matrices for a local point transformed into its parent."""

    la, lb, lc, ld, le, lf = (float(value) for value in local)
    pa, pb, pc, pd, pe, pf = (float(value) for value in parent)
    return (
        la * pa + lb * pc,
        la * pb + lb * pd,
        lc * pa + ld * pc,
        lc * pb + ld * pd,
        le * pa + lf * pc + pe,
        le * pb + lf * pd + pf,
    )


def _blank_pdf_text_operands(operator: bytes, operands: list[object]) -> None:
    """Suppress glyphs while retaining positioning operands for canonical extraction."""

    def empty_like(value: object) -> str | bytes:
        return b"" if isinstance(value, bytes) else ""

    if operator in {b"Tj", b"'"} and operands:
        operands[-1] = empty_like(operands[-1])
    elif operator == b'"' and len(operands) >= 3:
        operands[2] = empty_like(operands[2])
    elif operator == b"TJ" and operands and isinstance(operands[0], list):
        array = operands[0]
        for index, value in enumerate(array):
            if isinstance(value, (str, bytes)):
                array[index] = empty_like(value)


class PageBoundsPyPdfExtractor:
    """Embedded-text adapter filtering chunks by visible page bounds.

    This is intentionally separate from :class:`PyPdfExtractor`: default pypdf
    extraction is part of existing page commitments and must remain byte-stable.
    """

    tool_name = "pypdf-page-bounds"

    def __init__(self) -> None:
        try:
            import pypdf
        except ImportError as exc:  # pragma: no cover - dependency is locked
            raise IngestionFailure(
                "PDF_TOOL_UNAVAILABLE", "The configured PDF extractor is unavailable."
            ) from exc
        self._pypdf = pypdf
        self.tool_version = pypdf.__version__

    @staticmethod
    def _visible_bounds(page: object) -> PdfBounds:
        media = page.mediabox  # type: ignore[attr-defined]
        crop = page.cropbox  # type: ignore[attr-defined]
        bounds = (
            max(float(media.left), float(crop.left)),
            max(float(media.bottom), float(crop.bottom)),
            min(float(media.right), float(crop.right)),
            min(float(media.top), float(crop.top)),
        )
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise IngestionFailure(
                "PDF_BOUNDS_INVALID", "The PDF page has invalid visible bounds."
            )
        return bounds

    def extract(self, path: Path) -> tuple[ExtractedPage, ...]:
        try:
            reader = self._pypdf.PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise IngestionFailure(
                    "PDF_ENCRYPTED", "Encrypted PDF sources require a decrypted local copy."
                )
            pages: list[ExtractedPage] = []
            for index, page in enumerate(reader.pages, start=1):
                bounds = self._visible_bounds(page)
                embedded_text = page.extract_text() or ""
                form_bases: list[PdfMatrix] = [_IDENTITY_PDF_MATRIX]
                form_resources: list[object] = [page["/Resources"].get_object()]
                form_markers: list[bool] = []
                font_sizes: list[float] = [12.0]
                text_leading: list[float] = [0.0]
                graphics_states: list[list[tuple[float, float]]] = [[]]

                def visit_operand_before(
                    operator: bytes,
                    operands: list[object],
                    cm: Sequence[float],
                    tm: Sequence[float],
                    _bounds: PdfBounds = bounds,
                ) -> None:
                    if operator == b"q":
                        graphics_states[-1].append(
                            (font_sizes[-1], text_leading[-1])
                        )
                        return
                    if operator == b"Tf" and len(operands) >= 2:
                        try:
                            font_sizes[-1] = float(operands[1])
                        except (TypeError, ValueError):
                            pass
                        return
                    if operator in {b"TL", b"TD"} and operands:
                        try:
                            scale_x = math.sqrt(
                                float(tm[0]) ** 2 + float(tm[2]) ** 2
                            )
                            leading_operand = (
                                operands[0]
                                if operator == b"TL"
                                else -float(operands[1])
                            )
                            text_leading[-1] = (
                                float(leading_operand) * font_sizes[-1] * scale_x
                            )
                        except (IndexError, TypeError, ValueError):
                            text_leading[-1] = 0.0
                        return
                    if operator == b"Do":
                        marker = False
                        try:
                            resources = form_resources[-1]
                            xobjects = resources["/XObject"].get_object()  # type: ignore[index]
                            xobject = xobjects[operands[0]].get_object()
                            if xobject.get("/Subtype") != "/Image":
                                form_matrix = tuple(
                                    float(value)
                                    for value in xobject.get(
                                        "/Matrix", _IDENTITY_PDF_MATRIX
                                    )
                                )
                                effective_parent = _compose_pdf_matrices(
                                    cm, form_bases[-1]
                                )
                                form_bases.append(
                                    _compose_pdf_matrices(
                                        form_matrix, effective_parent
                                    )
                                )
                                child_resources = xobject.get("/Resources")
                                form_resources.append(
                                    child_resources.get_object()
                                    if child_resources is not None
                                    else resources
                                )
                                font_sizes.append(12.0)
                                text_leading.append(0.0)
                                graphics_states.append([])
                                marker = True
                        except Exception:
                            # pypdf owns malformed-XObject handling; keep its behavior.
                            marker = False
                        form_markers.append(marker)
                        return
                    if operator not in _PDF_TEXT_SHOW_OPERATORS:
                        return

                    effective_cm = _compose_pdf_matrices(cm, form_bases[-1])
                    show_tm = tuple(float(value) for value in tm)
                    if operator in {b"'", b'"'}:
                        mutable_tm = list(show_tm)
                        mutable_tm[4] -= text_leading[-1] * mutable_tm[2]
                        mutable_tm[5] -= text_leading[-1] * mutable_tm[3]
                        show_tm = tuple(mutable_tm)
                    visible = _origin_within_bounds(
                        _transform_pdf_text_origin(tm=show_tm, cm=effective_cm),
                        _bounds,
                    )
                    if not visible:
                        _blank_pdf_text_operands(operator, operands)

                def visit_operand_after(
                    operator: bytes,
                    _operands: list[object],
                    _cm: Sequence[float],
                    _tm: Sequence[float],
                ) -> None:
                    if operator == b"Q":
                        if graphics_states[-1]:
                            font_sizes[-1], text_leading[-1] = (
                                graphics_states[-1].pop()
                            )
                        return
                    if operator == b"Do" and form_markers:
                        if form_markers.pop():
                            form_bases.pop()
                            form_resources.pop()
                            font_sizes.pop()
                            text_leading.pop()
                            graphics_states.pop()

                canonical_visible_text = page.extract_text(
                    visitor_operand_before=visit_operand_before,
                    visitor_operand_after=visit_operand_after,
                ) or ""
                visible_text = canonical_visible_text
                if embedded_text.strip() and not visible_text.strip():
                    raise IngestionFailure(
                        "PDF_TEXT_OUT_OF_BOUNDS",
                        "Embedded PDF text exists but none lies within visible page bounds.",
                    )
                pages.append(ExtractedPage(page_number=index, text=visible_text))
        except IngestionFailure:
            raise
        except Exception as exc:
            raise IngestionFailure(
                "PDF_CORRUPT", "The PDF could not be parsed as a supported document."
            ) from exc
        if not pages:
            raise IngestionFailure("PDF_CORRUPT", "The PDF contains no pages.")
        return tuple(pages)


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
