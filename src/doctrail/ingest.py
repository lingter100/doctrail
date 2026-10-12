"""Bounded supported-format extraction. Uploaded HTML is never interpreted."""

import io
import unicodedata
import warnings

from pypdf import PdfReader

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_CONTENT_CHARS = 300_000
MAX_PDF_PAGES = 100


class ExtractionError(ValueError):
    pass


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def extract(source: bytes, kind: str) -> tuple[str, list[tuple[int, int, int | None]]]:
    if len(source) > MAX_FILE_BYTES:
        raise ExtractionError("file_too_large")
    if kind in ("txt", "md"):
        try:
            content = normalize(source.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise ExtractionError("utf8_required") from exc
        pages = [(0, len(content), None)]
    elif kind == "pdf":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                reader = PdfReader(io.BytesIO(source), strict=True)
                if reader.is_encrypted:
                    raise ExtractionError("encrypted_pdf_unsupported")
                if len(reader.pages) > MAX_PDF_PAGES:
                    raise ExtractionError("pdf_page_limit")
                parts: list[str] = []
                pages = []
                cursor = 0
                for index, page in enumerate(reader.pages, 1):
                    part = normalize(page.extract_text() or "")
                    if cursor + len(part) > MAX_CONTENT_CHARS:
                        raise ExtractionError("extracted_content_too_large")
                    pages.append((cursor, cursor + len(part), index))
                    parts.append(part)
                    cursor += len(part) + 1
                content = "\n".join(parts)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError("pdf_parse_failed") from exc
        if not content.strip():
            raise ExtractionError("pdf_text_missing_ocr_unsupported")
    else:
        raise ExtractionError("unsupported_file_type")
    if len(content) > MAX_CONTENT_CHARS:
        raise ExtractionError("extracted_content_too_large")
    if not content.strip():
        raise ExtractionError("empty_document")
    if "\x00" in content:
        raise ExtractionError("binary_content_unsupported")
    return content, pages
