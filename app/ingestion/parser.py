from pathlib import Path
from typing import Iterator

import pymupdf
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.errors import InvalidDocumentError


PARSER_NAME = "knowledge-agent-parser"
PARSER_VERSION = "2"

SUPPORTED_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def content_type_for_filename(filename: str) -> str:
    try:
        return SUPPORTED_CONTENT_TYPES[Path(filename).suffix.lower()]
    except KeyError as error:
        raise InvalidDocumentError(
            "Unsupported file type. Upload PDF, TXT, Markdown, or DOCX."
        ) from error


def _validate_path(file_path) -> Path:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"Expected file but found a directory: {path}")
    return path


def parse_pdf(file_path) -> list[dict]:
    path = _validate_path(file_path)
    records = []
    try:
        with pymupdf.open(path) as document:
            if not document.is_pdf:
                raise InvalidDocumentError("Uploaded content is not a PDF.")
            if document.needs_pass:
                raise InvalidDocumentError(
                    "Password-protected PDFs are not supported."
                )
            for page_number, page in enumerate(document, start=1):
                records.append(
                    {
                        "page": page_number,
                        "section": None,
                        "content": page.get_text(),
                        "filename": path.name,
                    }
                )
    except pymupdf.FileDataError as error:
        raise InvalidDocumentError(
            "The PDF is empty, corrupt, or unreadable."
        ) from error
    return records


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidDocumentError("Text documents must use UTF-8 encoding.") from error


def parse_text(file_path) -> list[dict]:
    path = _validate_path(file_path)
    return [{
        "page": None,
        "section": None,
        "content": _read_text(path),
        "filename": path.name,
    }]


def parse_markdown(file_path) -> list[dict]:
    path = _validate_path(file_path)
    text = _read_text(path)
    records = []
    section = None
    lines: list[str] = []

    def flush() -> None:
        if any(line.strip() for line in lines):
            records.append({
                "page": None,
                "section": section,
                "content": "\n".join(lines).strip(),
                "filename": path.name,
            })

    for line in text.splitlines():
        stripped = line.lstrip()
        marker, separator, title = stripped.partition(" ")
        is_heading = separator and marker and set(marker) == {"#"}
        if is_heading and title.strip():
            flush()
            lines = [line]
            section = title.strip()
        else:
            lines.append(line)
    flush()
    return records


def _iter_docx_blocks(document: Document) -> Iterator[Paragraph | Table]:
    # Paragraph and table collections are otherwise separate. This API keeps
    # their source order, which is essential for reliable evidence context.
    yield from document.iter_inner_content()


def parse_docx(file_path) -> list[dict]:
    path = _validate_path(file_path)
    try:
        document = Document(path)
    except Exception as error:
        raise InvalidDocumentError("The DOCX file is corrupt or unreadable.") from error

    records = []
    current_heading = None
    for position, block in enumerate(_iter_docx_blocks(document), start=1):
        if isinstance(block, Paragraph):
            content = block.text.strip()
            if not content:
                continue
            if block.style and block.style.name.startswith("Heading"):
                current_heading = content
        else:
            rows = [
                "\t".join(cell.text.strip() for cell in row.cells)
                for row in block.rows
            ]
            content = "\n".join(row for row in rows if row.strip())
            if not content:
                continue

        records.append({
            "page": None,
            "section": current_heading or ("Table" if isinstance(block, Table) else None),
            "content": content,
            "filename": path.name,
            "source_position": position,
        })
    return records


def parse_document(file_path, *, filename: str | None = None) -> tuple[str, list[dict]]:
    path = _validate_path(file_path)
    content_type = content_type_for_filename(filename or path.name)
    parser = {
        "application/pdf": parse_pdf,
        "text/plain": parse_text,
        "text/markdown": parse_markdown,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parse_docx,
    }[content_type]
    return content_type, parser(path)
