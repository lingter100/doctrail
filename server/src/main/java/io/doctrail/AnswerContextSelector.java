package io.doctrail;

import java.util.*;

/** One-hop expansion of canonical, already-authorized snapshot chunks for answers only. */
final class AnswerContextSelector {
    static final String POLICY = "ranked-neighbors-v1";
    private static final int LIMIT = 10;
    private static final List<String> PROOF = List.of("document_id", "revision", "chunk_id",
            "title", "meeting_date", "page", "start_offset", "end_offset", "text");
    private record Slot(Object document, int revision, Object page, long ordinal) {}

    private AnswerContextSelector() {}

    static List<Map<String,Object>> select(List<Map<String,Object>> corpus,
                                            List<Map<String,Object>> ranked) {
        if (ranked.size() > LIMIT) throw invalid();
        Map<String,Map<String,Object>> byId = new HashMap<>();
        Map<Slot,Map<String,Object>> bySlot = new HashMap<>();
        for (var row : corpus) {
            String id = identity(row, "chunk_id");
            identity(row, "document_id");
            int start = integer(row, "start_offset", 0), end = integer(row, "end_offset", 1);
            if (!(row.get("text") instanceof String text) || text.isBlank()
                    || text.codePointCount(0, text.length()) != end - start
                    || end - start > 24000) throw invalid();
            if (row.get("page") != null) integer(row, "page", 1);
            if (byId.putIfAbsent(id, row) != null || bySlot.putIfAbsent(slot(row, 0), row) != null)
                throw invalid();
        }
        List<Map<String,Object>> anchors = new ArrayList<>(), selected = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (var anchor : ranked) {
            String id = identity(anchor, "chunk_id");
            var canonical = byId.get(id);
            if (canonical == null || !seen.add(id)) throw invalid();
            for (String field : PROOF)
                if (!anchor.containsKey(field) || !Objects.equals(anchor.get(field), canonical.get(field)))
                    throw invalid();
            // LearnedSearch strips ordinal from ranked rows; resolve it from the snapshot.
            if (anchor.containsKey("ordinal") && !Objects.equals(anchor.get("ordinal"), canonical.get("ordinal")))
                throw invalid();
            anchors.add(canonical);
            selected.add(canonical);
        }
        for (var anchor : anchors) {
            for (int delta : new int[]{-1, 1}) {
                if (selected.size() == LIMIT) return List.copyOf(selected);
                var neighbor = bySlot.get(slot(anchor, delta));
                if (neighbor != null && seen.add((String)neighbor.get("chunk_id"))) selected.add(neighbor);
            }
        }
        return List.copyOf(selected);
    }

    private static Slot slot(Map<String,Object> row, int delta) {
        int ordinal = integer(row, "ordinal", 0);
        return new Slot(row.get("document_id"), integer(row, "revision", 1), row.get("page"),
                (long)ordinal + delta);
    }

    private static String identity(Map<String,Object> row, String key) {
        if (!(row.get(key) instanceof String value) || value.isBlank() || value.length() > 128)
            throw invalid();
        return value;
    }

    private static int integer(Map<String,Object> row, String key, int minimum) {
        if (!(row.get(key) instanceof Number value) || value.doubleValue() < minimum
                || value.doubleValue() > Integer.MAX_VALUE || value.doubleValue() != value.intValue())
            throw invalid();
        return value.intValue();
    }

    private static ApiError invalid() { return new ApiError(409, "search_context_changed"); }
}
