import io
from itertools import pairwise

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from doctrail.ingest import ExtractionError, extract
from doctrail.retrieval import chunk_content, rank_chunks, tokenize


def text_pdf(text="synthetic evidence", pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def test_tokenizer_is_explicit_simple_baseline():
    assert tokenize("Hello HELLO 42 권한관리") == ["hello", "hello", "42", "권한", "한관", "관리"]


def test_offsets_preserve_normalized_unicode_and_overlap():
    source = ("원문 😀 e\u0301\r\n" * 400).encode()
    content, pages = extract(source, "md")
    chunks = chunk_content(content, pages)
    assert len(chunks) > 1
    assert "\r" not in content
    assert "é" in content
    assert chunks[0].start_offset == 0
    assert chunks[-1].end_offset == len(content)
    assert all(content[c.start_offset : c.end_offset] == c.text for c in chunks)
    assert all(a.end_offset >= b.start_offset for a, b in pairwise(chunks))


def test_bm25_match_nonmatch_and_deterministic_order():
    candidates = [
        {"chunk_id": "b", "text": "refund policy refund"},
        {"chunk_id": "a", "text": "refund policy refund"},
        {"chunk_id": "c", "text": "shipping only"},
    ]
    hits = rank_chunks("refund", candidates)
    assert [hit["chunk_id"] for hit in hits] == ["a", "b"]
    assert hits[0]["score"] > 0
    assert rank_chunks("missing", candidates) == []
    assert rank_chunks("!!!", candidates) == []
    assert rank_chunks("refund", []) == []


def test_pdf_page_navigation_and_exact_offsets():
    content, pages = extract(text_pdf(pages=2), "pdf")
    chunks = chunk_content(content, pages)
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert all(content[c.start_offset : c.end_offset] == c.text for c in chunks)
    assert "synthetic evidence" in content


def test_ties_use_stable_evidence_fields_before_random_ids():
    candidates = [
        {"chunk_id": "000-random", "text": "same query", "filename": "z.md"},
        {"chunk_id": "999-random", "text": "same query", "filename": "a.md"},
    ]
    assert [hit["filename"] for hit in rank_chunks("query", candidates)] == ["a.md", "z.md"]


@pytest.mark.parametrize(
    ("source", "kind", "code"),
    [
        (b"\xff", "txt", "utf8_required"),
        (b"<h1>uploaded</h1>", "html", "unsupported_file_type"),
        (b"bad PDF", "pdf", "pdf_parse_failed"),
        (b"  ", "txt", "empty_document"),
        (b"a\x00b", "txt", "binary_content_unsupported"),
        (b"a" * 300001, "txt", "extracted_content_too_large"),
        (b"a" * (5 * 1024 * 1024 + 1), "txt", "file_too_large"),
    ],
    ids=["encoding", "format", "pdf", "empty", "binary", "content_limit", "file_limit"],
)
def test_safe_extraction_failures(source, kind, code):
    with pytest.raises(ExtractionError, match=code):
        extract(source, kind)


def test_empty_pdf_reports_ocr_unsupported():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ExtractionError, match="pdf_text_missing_ocr_unsupported"):
        extract(output.getvalue(), "pdf")


def test_pdf_page_limit():
    with pytest.raises(ExtractionError, match="pdf_page_limit"):
        extract(text_pdf(pages=101), "pdf")
