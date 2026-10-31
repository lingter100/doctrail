package io.doctrail;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/** Optional real-corpus parity check. Never emits document contents to test logs. */
class MeetingSourceParityTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Test
    void unicodeCoordinatesAndNormalizationHaveExplicitExpectedValues() {
        var shortText = Ingest.extract("\uFEFFCafé\r\n가🙂\rfin".getBytes(StandardCharsets.UTF_8), "md");
        assertEquals("Café\n가🙂\nfin", shortText.content());
        assertEquals(11, shortText.pages().getFirst().endOffset());
        String source = "a".repeat(600) + "🙂".repeat(350) + " " + "가".repeat(300);
        var extraction = Ingest.extract(source.getBytes(StandardCharsets.UTF_8), "md");
        var chunks = Retrieval.chunkContent(extraction.content(), extraction.pages());
        assertEquals(1251, Ingest.codePointLength(extraction.content()));
        assertEquals(2, chunks.size());
        assertEquals(new Retrieval.Chunk("a".repeat(600) + "🙂".repeat(350) + " ", null, 0, 951, 0), chunks.get(0));
        assertEquals(new Retrieval.Chunk("🙂".repeat(149) + " " + "가".repeat(300), null, 801, 1251, 1), chunks.get(1));
    }

    @Test
    void registeredInventoryMatchesActualJavaExtractionAndChunks() throws Exception {
        String inputArg = System.getProperty("doctrail.sourceInventory");
        assumeTrue(inputArg != null, "Explicit source inventory required; normal CI does not fetch corpora");
        Path root = Path.of(System.getProperty("doctrail.sourceRoot", "..")).toRealPath();
        Path input = contained(root, Path.of(inputArg));
        String receiptArg = System.getProperty("doctrail.sourceParityReceipt");
        assertNotNull(receiptArg, "A new receipt path is required");
        Path receipt = Path.of(receiptArg).toAbsolutePath().normalize();
        assertTrue(receipt.startsWith(root.resolve(".local")), "Receipt must stay in ignored local workspace");
        assertTrue(receipt.getParent().toRealPath().startsWith(root), "Receipt parent must stay in workspace");
        assertTrue(receipt.getParent().toRealPath().startsWith(root.resolve(".local").toRealPath()));
        assertFalse(Files.exists(receipt), "Refuse to overwrite prior parity evidence");
        byte[] inputBytes = bounded(input, 16 * 1024 * 1024);
        JsonNode inventory = JSON.readTree(inputBytes);
        assertEquals(1, inventory.path("schema_version").asInt());
        assertTrue(inventory.path("documents").isArray());
        assertFalse(inventory.path("documents").isEmpty(), "Inventory must contain adopted documents");
        var rows = new ArrayList<Map<String, Object>>();
        int totalChunks = 0;
        for (JsonNode doc : inventory.path("documents")) {
            String id = doc.path("document_id").asText();
            assertFalse(id.isBlank());
            Path raw = contained(root, Path.of(doc.path("raw_snapshot").asText()));
            byte[] bytes = bounded(raw, Ingest.MAX_FILE_BYTES);
            assertEquals(bytes.length, doc.path("raw_size_bytes").asInt(-1), "Raw byte count: " + id);
            assertEquals(doc.path("raw_sha256").asText(), sha(bytes), "Raw hash: " + id);
            String kind = raw.getFileName().toString().endsWith(".md") ? "md" : "txt";
            var actual = Ingest.extract(bytes, kind);
            assertEquals(Ingest.codePointLength(actual.content()), doc.path("processed_codepoints").asInt(-1), "Codepoint count: " + id);
            assertEquals(sha(actual.content().getBytes(StandardCharsets.UTF_8)), doc.path("processed_sha256").asText(), "Processed hash: " + id);
            assertTrue(actual.content().equals(doc.path("content").asText()), "Normalized content: " + id);
            assertEquals(actual.pages().size(), doc.path("pages").size(), "Page count: " + id);
            for (int i = 0; i < actual.pages().size(); i++) {
                var page = actual.pages().get(i);
                JsonNode expected = doc.path("pages").get(i);
                assertEquals(page.startOffset(), expected.path("start_offset").asInt(-1), "Page start: " + id);
                assertEquals(page.endOffset(), expected.path("end_offset").asInt(-1), "Page end: " + id);
                assertEquals(page.page(), nullableInt(expected.path("page")), "Page number: " + id);
            }
            var chunks = Retrieval.chunkContent(actual.content(), actual.pages());
            assertEquals(chunks.size(), doc.path("chunks").size(), "Chunk count: " + id);
            for (int i = 0; i < chunks.size(); i++) {
                var chunk = chunks.get(i);
                JsonNode expected = doc.path("chunks").get(i);
                String label = id + ":" + i;
                assertTrue(chunk.text().equals(expected.path("text").asText()), "Exact chunk text: " + label);
                assertEquals(chunk.ordinal(), expected.path("ordinal").asInt(-1), "Ordinal: " + label);
                assertEquals(chunk.startOffset(), expected.path("start_offset").asInt(-1), "Start: " + label);
                assertEquals(chunk.endOffset(), expected.path("end_offset").asInt(-1), "End: " + label);
                assertEquals(chunk.page(), nullableInt(expected.path("page")), "Page: " + label);
                assertEquals(sha(chunk.text().getBytes(StandardCharsets.UTF_8)), expected.path("text_sha256").asText(), "Text hash: " + label);
                assertEquals(id + "-r" + doc.path("revision").asInt() + "-c" + String.format(java.util.Locale.ROOT, "%04d", i), expected.path("chunk_id").asText(), "Chunk ID: " + label);
            }
            rows.add(Map.of("document_id", id, "raw_sha256", sha(bytes), "processed_sha256", sha(actual.content().getBytes(StandardCharsets.UTF_8)), "codepoints", Ingest.codePointLength(actual.content()), "chunks", chunks.size()));
            totalChunks += chunks.size();
        }
        var sources = new LinkedHashMap<String, String>();
        for (String relative : List.of("server/src/main/java/io/doctrail/Ingest.java", "server/src/main/java/io/doctrail/Retrieval.java", "server/src/test/java/io/doctrail/MeetingSourceParityTest.java")) sources.put(relative, sha(Files.readAllBytes(root.resolve(relative))));
        var result = new LinkedHashMap<String, Object>();
        result.put("schema_version", 1);
        result.put("kind", "actual_java_python_document_chunk_parity");
        result.put("inventory_sha256", sha(inputBytes));
        result.put("java_version", System.getProperty("java.version"));
        result.put("bound_files", sources);
        result.put("documents", rows);
        result.put("document_count", rows.size());
        result.put("chunk_count", totalChunks);
        result.put("exact_content_pages_chunk_text_offsets_ordinals_ids", true);
        result.put("model_calls", 0);
        result.put("semantic_quality_measured", false);
        Files.write(receipt, JSON.writerWithDefaultPrettyPrinter().writeValueAsBytes(result), StandardOpenOption.CREATE_NEW);
    }

    private static Integer nullableInt(JsonNode value) {
        assertTrue(value.isNull() || value.isIntegralNumber(), "Page must be null or integer");
        return value.isNull() ? null : value.asInt();
    }

    private static Path contained(Path root, Path path) throws Exception {
        Path resolved = (path.isAbsolute() ? path : root.resolve(path)).toRealPath();
        assertTrue(resolved.startsWith(root), "Source path must stay in workspace");
        return resolved;
    }

    private static byte[] bounded(Path path, int limit) throws Exception {
        try (var stream = Files.newInputStream(path)) {
            byte[] bytes = stream.readNBytes(limit + 1);
            assertTrue(bytes.length <= limit, "Parity input too large");
            return bytes;
        }
    }

    private static String sha(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
}
