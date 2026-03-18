"""
Extensible document parser system for Voxyflow RAG pipeline.

Phase 1: .txt, .md, .markdown support.
Phase 2: PDF, DOCX, XLSX support (graceful — skipped if deps missing).
"""

from __future__ import annotations

import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnsupportedFileType(Exception):
    """Raised when no parser is registered for the given file extension."""

    def __init__(self, extension: str):
        self.extension = extension
        super().__init__(
            f"Unsupported file type: {extension!r}. "
            "Supported formats: .txt, .md, .pdf, .docx, .xlsx, .xls, .csv."
        )


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ParsedDocument:
    """Result of parsing a document file."""

    text: str
    """Full extracted plain text."""

    chunks: list[str] = field(default_factory=list)
    """Text split into overlapping chunks (~500 chars, 50 char overlap)."""

    metadata: dict = field(default_factory=dict)
    """filename, filetype, size_bytes, chunk_count, etc."""


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

_CHUNK_MIN = 100
_CHUNK_MAX = 600
_CHUNK_OVERLAP = 50

# Simple sentence boundary: end of sentence punctuation followed by whitespace or end
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')


def _split_into_chunks(text: str) -> list[str]:
    """
    Split text into overlapping chunks.

    Strategy:
    1. Split on paragraph breaks (\\n\\n).
    2. Re-split paragraphs > _CHUNK_MAX chars on sentence boundaries.
    3. Keep chunks between _CHUNK_MIN and _CHUNK_MAX chars.
    4. Add _CHUNK_OVERLAP char overlap between consecutive chunks.
    """
    # Step 1: paragraph split
    raw_paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

    # Step 2: re-split long paragraphs
    segments: list[str] = []
    for para in raw_paragraphs:
        if len(para) <= _CHUNK_MAX:
            segments.append(para)
        else:
            # Split on sentence boundaries
            sentences = _SENTENCE_END_RE.split(para)
            current = ""
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(current) + len(sentence) + 1 <= _CHUNK_MAX:
                    current = (current + " " + sentence).strip() if current else sentence
                else:
                    if current:
                        segments.append(current)
                    # Sentence itself may be too long — hard cut
                    while len(sentence) > _CHUNK_MAX:
                        segments.append(sentence[:_CHUNK_MAX])
                        sentence = sentence[_CHUNK_MAX - _CHUNK_OVERLAP:]
                    current = sentence
            if current:
                segments.append(current)

    # Step 3: filter by min length
    segments = [s for s in segments if len(s) >= _CHUNK_MIN]

    if not segments:
        # Fallback: if text is very short, return as a single chunk (if non-empty)
        stripped = text.strip()
        return [stripped] if stripped else []

    # Step 4: add overlap
    chunks: list[str] = []
    for i, seg in enumerate(segments):
        if i == 0:
            chunks.append(seg)
        else:
            # Prepend tail of previous segment for context overlap
            prev_tail = segments[i - 1][-_CHUNK_OVERLAP:].strip()
            chunk = (prev_tail + " " + seg).strip() if prev_tail else seg
            # Trim to max if overlap pushed it over
            if len(chunk) > _CHUNK_MAX:
                chunk = chunk[:_CHUNK_MAX]
            chunks.append(chunk)

    return chunks


# ---------------------------------------------------------------------------
# Base parser
# ---------------------------------------------------------------------------


class BaseParser(ABC):
    """Abstract base class for document parsers."""

    supported_extensions: list[str] = []

    @abstractmethod
    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        """Parse raw file bytes into a ParsedDocument."""
        ...


# ---------------------------------------------------------------------------
# Text / Markdown parser
# ---------------------------------------------------------------------------


class TextParser(BaseParser):
    """Parser for plain text and Markdown files."""

    supported_extensions = ['.txt', '.md', '.markdown']

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('latin-1', errors='replace')

        ext = Path(filename).suffix.lower()
        chunks = _split_into_chunks(text)

        return ParsedDocument(
            text=text,
            chunks=chunks,
            metadata={
                'filename': filename,
                'filetype': ext,
                'size_bytes': len(content),
                'chunk_count': len(chunks),
            },
        )


# ---------------------------------------------------------------------------
# PDF parser (Phase 2)
# ---------------------------------------------------------------------------


class PDFParser(BaseParser):
    """Parser for PDF files. Requires pypdf>=4.0.0."""

    supported_extensions = ['.pdf']

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        import io
        from pypdf import PdfReader  # type: ignore[import]

        reader = PdfReader(io.BytesIO(content))
        page_texts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            page_texts.append(page_text)

        text = "\n\n".join(page_texts)
        chunks = _split_into_chunks(text)

        return ParsedDocument(
            text=text,
            chunks=chunks,
            metadata={
                'filename': filename,
                'filetype': '.pdf',
                'size_bytes': len(content),
                'chunk_count': len(chunks),
                'page_count': len(reader.pages),
            },
        )


# ---------------------------------------------------------------------------
# DOCX parser (Phase 2)
# ---------------------------------------------------------------------------


class DocxParser(BaseParser):
    """Parser for Word documents. Requires python-docx>=1.1.0."""

    supported_extensions = ['.docx', '.doc']

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        import io
        from docx import Document as DocxDocument  # type: ignore[import]

        doc = DocxDocument(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        chunks = _split_into_chunks(text)

        return ParsedDocument(
            text=text,
            chunks=chunks,
            metadata={
                'filename': filename,
                'filetype': Path(filename).suffix.lower(),
                'size_bytes': len(content),
                'chunk_count': len(chunks),
            },
        )


# ---------------------------------------------------------------------------
# XLSX / CSV parser (Phase 2)
# ---------------------------------------------------------------------------


class XlsxParser(BaseParser):
    """
    Parser for spreadsheets.

    - .xlsx / .xls: requires openpyxl>=3.1.0
    - .csv: no external dependency required
    """

    supported_extensions = ['.xlsx', '.xls', '.csv']

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        ext = Path(filename).suffix.lower()

        if ext == '.csv':
            text = self._parse_csv(content)
        else:
            text = self._parse_xlsx(content)

        chunks = _split_into_chunks(text)

        return ParsedDocument(
            text=text,
            chunks=chunks,
            metadata={
                'filename': filename,
                'filetype': ext,
                'size_bytes': len(content),
                'chunk_count': len(chunks),
            },
        )

    def _parse_csv(self, content: bytes) -> str:
        import csv
        import io

        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('latin-1', errors='replace')

        reader = csv.reader(io.StringIO(text))
        rows = ["\t".join(row) for row in reader if any(cell.strip() for cell in row)]
        return "\n".join(rows)

    def _parse_xlsx(self, content: bytes) -> str:
        import io
        import openpyxl  # type: ignore[import]

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet_texts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = []
            for row in ws.iter_rows(values_only=True):
                if any(cell is not None for cell in row):
                    rows.append("\t".join("" if cell is None else str(cell) for cell in row))
            if rows:
                sheet_texts.append(f"[{sheet_name}]\n" + "\n".join(rows))
        wb.close()
        return "\n\n".join(sheet_texts)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class DocumentParserRegistry:
    """
    Registry that maps file extensions to parser instances.

    Usage:
        registry = DocumentParserRegistry()
        parser = registry.get_parser("report.txt")
        result = parser.parse(file_bytes, "report.txt")

    Phase 1: .txt, .md, .markdown
    Phase 2: .pdf (pypdf), .docx/.doc (python-docx), .xlsx/.xls/.csv (openpyxl / built-in csv)
    All Phase 2 parsers are registered with graceful degradation — missing deps are skipped.
    """

    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}
        # Register built-in parsers
        self.register(TextParser())

        # Phase 2 — PDF parser (graceful: skipped if pypdf not installed)
        try:
            import pypdf  # noqa: F401
            self.register(PDFParser())
        except ImportError:
            logger.debug("DocumentParserRegistry: pypdf not installed — PDF support disabled")

        # Phase 2 — DOCX parser (graceful: skipped if python-docx not installed)
        try:
            import docx  # noqa: F401
            self.register(DocxParser())
        except ImportError:
            logger.debug("DocumentParserRegistry: python-docx not installed — DOCX support disabled")

        # Phase 2 — XLSX/CSV parser (graceful: openpyxl optional, csv always works)
        xlsx_parser = XlsxParser()
        try:
            import openpyxl  # noqa: F401
            self.register(xlsx_parser)
        except ImportError:
            logger.debug("DocumentParserRegistry: openpyxl not installed — XLSX/XLS support disabled, registering CSV only")
            # Register CSV support only (no openpyxl needed for .csv)
            self._parsers['.csv'] = xlsx_parser
            logger.debug("DocumentParserRegistry: registered XlsxParser for '.csv'")

    def register(self, parser: BaseParser) -> None:
        """Register a parser for all its supported extensions."""
        for ext in parser.supported_extensions:
            self._parsers[ext.lower()] = parser
            logger.debug(f"DocumentParserRegistry: registered {type(parser).__name__} for {ext!r}")

    def get_parser(self, filename: str) -> BaseParser:
        """Return the appropriate parser for the given filename.

        Raises UnsupportedFileType if no parser is registered for the extension.
        """
        ext = Path(filename).suffix.lower()
        parser = self._parsers.get(ext)
        if parser is None:
            raise UnsupportedFileType(ext)
        return parser

    @property
    def supported_extensions(self) -> list[str]:
        """List of all supported file extensions."""
        return list(self._parsers.keys())


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: DocumentParserRegistry | None = None


def get_document_parser_registry() -> DocumentParserRegistry:
    """Return the global DocumentParserRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = DocumentParserRegistry()
    return _registry
