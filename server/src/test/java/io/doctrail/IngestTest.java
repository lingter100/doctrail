package io.doctrail;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.encryption.AccessPermission;
import org.apache.pdfbox.pdmodel.encryption.StandardProtectionPolicy;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.apache.pdfbox.pdmodel.font.Standard14Fonts;
import org.junit.jupiter.api.Test;

class IngestTest {
    @Test
    void strictUtf8BomNewlinesNfcAndCodePointPageOffsets() {
        var extraction = Ingest.extract("\uFEFF😀e\u0301\r\n가\rx".getBytes(StandardCharsets.UTF_8), "txt");
        assertEquals("😀é\n가\nx", extraction.content());
        assertEquals(6, extraction.pages().getFirst().endOffset());
        assertNull(extraction.pages().getFirst().page());
        assertEquals("\uFEFFx", Ingest.extract("\uFEFF\uFEFFx".getBytes(StandardCharsets.UTF_8), "md").content());
        assertCode("utf8_required", new byte[]{(byte) 0xFF}, "txt");
        assertCode("utf8_required", new byte[]{(byte) 0xC0, (byte) 0xAF}, "txt");
        assertCode("utf8_required", new byte[]{(byte) 0xED, (byte) 0xA0, (byte) 0x80}, "md");
        assertCode("utf8_required", new byte[]{(byte) 0xF0, (byte) 0x9F}, "txt");
    }

    @Test
    void safeErrorsAndUnicodeContentBounds() {
        assertCode("unsupported_file_type", "<h1>uploaded</h1>".getBytes(StandardCharsets.UTF_8), "html");
        assertCode("binary_content_unsupported", new byte[]{'a', 0, 'b'}, "txt");
        assertCode("empty_document", "\u0085\u00A0\u001C\u202F".getBytes(StandardCharsets.UTF_8), "md");
        assertCode("extracted_content_too_large", "😀".repeat(300001).getBytes(StandardCharsets.UTF_8), "txt");
        assertCode("file_too_large", new byte[Ingest.MAX_FILE_BYTES + 1], "txt");
        assertEquals(300000, Ingest.codePointLength(Ingest.extract("😀".repeat(300000)
                .getBytes(StandardCharsets.UTF_8), "txt").content()));
        assertEquals("<script>alert(1)</script>", Ingest.extract("<script>alert(1)</script>"
                .getBytes(StandardCharsets.UTF_8), "md").content());
    }

    @Test
    void corruptPdfDoesNotExposeSourceOrCause() {
        assertCode("pdf_parse_failed", "sensitive malformed uploaded PDF".getBytes(StandardCharsets.UTF_8), "pdf");
    }

    @Test
    void pdfPagesPreserveEvidenceAndExcludeJoinSeparators() throws IOException {
        var extraction = Ingest.extract(pdf(2, true, false), "pdf");
        var chunks = Retrieval.chunkContent(extraction.content(), extraction.pages());
        assertEquals(2, chunks.size());
        assertEquals(1, chunks.get(0).page());
        assertEquals(2, chunks.get(1).page());
        assertTrue(chunks.get(0).text().contains("synthetic evidence 1"));
        assertTrue(chunks.get(1).text().contains("synthetic evidence 2"));
        assertEquals(extraction.pages().get(0).endOffset() + 1, extraction.pages().get(1).startOffset());
        for (var chunk : chunks) {
            assertEquals(chunk.text(), extraction.content().substring(
                    extraction.content().offsetByCodePoints(0, chunk.startOffset()),
                    extraction.content().offsetByCodePoints(0, chunk.endOffset())));
        }
    }

    @Test
    void pdfLimitsAndEncryptionHaveKnownCodes() throws IOException {
        assertCode("pdf_page_limit", pdf(101, false, false), "pdf");
        assertCode("pdf_text_missing_ocr_unsupported", pdf(1, false, false), "pdf");
        assertCode("encrypted_pdf_unsupported", pdf(1, true, true), "pdf");
    }

    private static void assertCode(String code, byte[] source, String kind) {
        var error = assertThrows(Ingest.ExtractionError.class, () -> Ingest.extract(source, kind));
        assertEquals(code, error.getMessage());
        assertNull(error.getCause());
    }

    private static byte[] pdf(int count, boolean text, boolean encrypted) throws IOException {
        try (var document = new PDDocument(); var output = new ByteArrayOutputStream()) {
            for (int i = 1; i <= count; i++) {
                var page = new PDPage();
                document.addPage(page);
                if (text) {
                    try (var stream = new PDPageContentStream(document, page)) {
                        stream.beginText();
                        stream.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA), 12);
                        stream.newLineAtOffset(72, 720);
                        stream.showText("synthetic evidence " + i);
                        stream.endText();
                    }
                }
            }
            if (encrypted) document.protect(new StandardProtectionPolicy("owner", "reader", new AccessPermission()));
            document.save(output);
            return output.toByteArray();
        }
    }
}
