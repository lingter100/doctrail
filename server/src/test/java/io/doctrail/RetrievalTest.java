package io.doctrail;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class RetrievalTest {
    @Test
    void explicitAsciiAndKoreanBigramTokenizer() {
        assertEquals(List.of("hello", "hello", "42", "권한", "한관", "관리", "가", "i", "abc"),
                Retrieval.tokenize("Hello HELLO 42 권한관리 가 😀 é İABC"));
    }

    @Test
    void originalPythonGoldenScoresWithEmptyCorpusRowsAndDeduplicatedQueryTerms() {
        // Synthetic fixtures; expected numbers measured with the original Python rank_chunks.
        var candidates = List.of(candidate("a", "refund policy refund 권한관리"),
                candidate("b", "refund shipping 권한"), candidate("c", "policy 관리"), candidate("d", "!!!"));
        var first = Retrieval.rankChunks("refund refund 관리", candidates, 10);
        assertEquals(List.of("a", "c", "b"), first.stream().map(row -> row.get("chunk_id")).toList());
        assertEquals(List.of(1.17011084, 0.79011596, 0.66590559), first.stream().map(row -> row.get("score")).toList());
        var all = Retrieval.rankChunks("refund shipping policy 권한관리", candidates, 10);
        assertEquals(List.of("a", "b", "c"), all.stream().map(row -> row.get("chunk_id")).toList());
        assertEquals(List.of(2.86108644, 2.48846627, 1.58023191), all.stream().map(row -> row.get("score")).toList());
        assertFalse(candidates.getFirst().containsKey("score"));
        assertEquals(List.of(), Retrieval.rankChunks("notfound", candidates, 10));
        assertEquals(List.of(), Retrieval.rankChunks("!!!", candidates, 10));
        assertEquals(List.of(), Retrieval.rankChunks("refund", List.of(), 10));
        assertEquals(1, Retrieval.rankChunks("refund", candidates, 1).size());
    }

    @Test
    void unicodeTieOrderingUsesCodePointsRatherThanUtf16AndStableEvidenceBeforeIds() {
        List<Map<String, Object>> candidates = List.of(
                Map.of("chunk_id", "a", "text", "same", "filename", "😀.md"),
                Map.of("chunk_id", "z", "text", "same", "filename", "\uE000.md"),
                Map.of("chunk_id", "y", "text", "same", "filename", "a.md"));
        assertEquals(List.of("y", "z", "a"), Retrieval.rankChunks("same", candidates, 10).stream()
                .map(row -> row.get("chunk_id")).toList());
        assertTrue(Retrieval.CODE_POINT_ORDER.compare("😀", "😀a") < 0);
    }

    @Test
    void chunkOffsetsAreCodePointsPreserveNormalizationAndOverlap() {
        var extraction = Ingest.extract("원문 😀 e\u0301\r\n".repeat(400).getBytes(StandardCharsets.UTF_8), "md");
        var chunks = Retrieval.chunkContent(extraction.content(), extraction.pages());
        assertTrue(chunks.size() > 1);
        assertFalse(extraction.content().contains("\r"));
        assertTrue(extraction.content().contains("é"));
        assertEquals(0, chunks.getFirst().startOffset());
        assertEquals(Ingest.codePointLength(extraction.content()), chunks.getLast().endOffset());
        for (int i = 0; i < chunks.size(); i++) {
            var chunk = chunks.get(i);
            assertEquals(slice(extraction.content(), chunk.startOffset(), chunk.endOffset()), chunk.text());
            assertEquals(i, chunk.ordinal());
            assertTrue(Ingest.codePointLength(chunk.text()) <= 1000);
            if (i > 0) assertEquals(chunks.get(i - 1).endOffset() - 150, chunk.startOffset());
        }
    }

    @Test
    void chunkBoundariesIncludeLastDelimiterAndNeverCrossPages() {
        String page1 = "😀".repeat(700) + " " + "가".repeat(400);
        String page2 = "x".repeat(1100);
        String content = page1 + "\n" + page2;
        var chunks = Retrieval.chunkContent(content,
                List.of(new Ingest.Page(0, 1101, 1), new Ingest.Page(1102, 2202, 2)));
        assertEquals(List.of(0, 551, 1102, 1952), chunks.stream().map(Retrieval.Chunk::startOffset).toList());
        assertEquals(List.of(701, 1101, 2102, 2202), chunks.stream().map(Retrieval.Chunk::endOffset).toList());
        assertEquals(List.of(1, 1, 2, 2), chunks.stream().map(Retrieval.Chunk::page).toList());
        assertTrue(chunks.getFirst().text().endsWith(" "));
        String blank = "\u0085\u00A0\u001C\u202F";
        assertEquals(List.of(), Retrieval.chunkContent(blank, List.of(new Ingest.Page(0, 4, null))));
    }

    private static Map<String, Object> candidate(String id, String text) {
        return Map.of("chunk_id", id, "text", text);
    }

    private static String slice(String text, int start, int end) {
        return text.substring(text.offsetByCodePoints(0, start), text.offsetByCodePoints(0, end));
    }
}
