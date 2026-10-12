package io.doctrail;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;
import org.apache.pdfbox.io.RandomAccessReadBuffer;
import org.apache.pdfbox.pdfparser.PDFParser;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.encryption.InvalidPasswordException;
import org.apache.pdfbox.text.PDFTextStripper;

/** Bounded extraction: uploaded HTML is plain text and parser diagnostics are never returned. */
public final class Ingest {
    public static final int MAX_FILE_BYTES = 5 * 1024 * 1024;
    public static final int MAX_CONTENT_CHARS = 300_000;
    public static final int MAX_PDF_PAGES = 100;

    private Ingest() {}

    public record Page(int startOffset, int endOffset, Integer page) {}
    public record Extraction(String content, List<Page> pages) {
        public Extraction { pages = List.copyOf(pages); }
    }

    public static final class ExtractionError extends RuntimeException {
        public ExtractionError(String code) { super(code); }
    }

    public static String normalize(String text) {
        return Normalizer.normalize(text.replace("\r\n", "\n").replace('\r', '\n'), Normalizer.Form.NFC);
    }

    public static int codePointLength(String text) {
        return text.codePointCount(0, text.length());
    }

    /** Python str.isspace/strip includes the information separators and nonbreaking spaces. */
    public static boolean isBlank(String text) {
        return text.codePoints().allMatch(point -> Character.isWhitespace(point)
                || Character.isSpaceChar(point) || point == 0x85);
    }

    public static Extraction extract(byte[] source, String kind) {
        if (source.length > MAX_FILE_BYTES) throw new ExtractionError("file_too_large");
        Extraction extraction;
        if ("txt".equals(kind) || "md".equals(kind)) {
            String text;
            try {
                text = StandardCharsets.UTF_8.newDecoder()
                        .onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT)
                        .decode(ByteBuffer.wrap(source)).toString();
            } catch (CharacterCodingException ignored) {
                throw new ExtractionError("utf8_required");
            }
            if (text.startsWith("\uFEFF")) text = text.substring(1);
            text = normalize(text);
            extraction = new Extraction(text, List.of(new Page(0, codePointLength(text), null)));
        } else if ("pdf".equals(kind)) {
            extraction = extractPdf(source);
            if (isBlank(extraction.content())) throw new ExtractionError("pdf_text_missing_ocr_unsupported");
        } else {
            throw new ExtractionError("unsupported_file_type");
        }
        if (codePointLength(extraction.content()) > MAX_CONTENT_CHARS) {
            throw new ExtractionError("extracted_content_too_large");
        }
        if (isBlank(extraction.content())) throw new ExtractionError("empty_document");
        if (extraction.content().indexOf('\0') >= 0) throw new ExtractionError("binary_content_unsupported");
        return extraction;
    }

    private static Extraction extractPdf(byte[] source) {
        // Application logging disables PDFBox/fontbox diagnostic categories, which may contain source text.
        try (var input = new RandomAccessReadBuffer(source)) {
            var parser = new PDFParser(input);
            // parse() resets leniency to true; pass false to the parsing entrypoint itself.
            try (PDDocument document = parser.parse(false)) {
                if (document.isEncrypted()) throw new ExtractionError("encrypted_pdf_unsupported");
                if (document.getNumberOfPages() > MAX_PDF_PAGES) throw new ExtractionError("pdf_page_limit");
                var parts = new ArrayList<String>();
                var pages = new ArrayList<Page>();
                int cursor = 0;
                var stripper = new PDFTextStripper();
                stripper.setLineSeparator("\n");
                stripper.setPageStart("");
                stripper.setPageEnd("");
                for (int index = 1; index <= document.getNumberOfPages(); index++) {
                    stripper.setStartPage(index);
                    stripper.setEndPage(index);
                    String part = normalize(stripper.getText(document));
                    int length = codePointLength(part);
                    if (cursor + length > MAX_CONTENT_CHARS) throw new ExtractionError("extracted_content_too_large");
                    pages.add(new Page(cursor, cursor + length, index));
                    parts.add(part);
                    cursor += length + 1;
                }
                return new Extraction(String.join("\n", parts), pages);
            }
        } catch (ExtractionError error) {
            throw error;
        } catch (InvalidPasswordException ignored) {
            throw new ExtractionError("encrypted_pdf_unsupported");
        } catch (IOException | RuntimeException ignored) {
            // Deliberately discard parser exception messages and causes (uploaded content can occur in them).
            throw new ExtractionError("pdf_parse_failed");
        }
    }
}
