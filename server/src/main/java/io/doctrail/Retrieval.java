package io.doctrail;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeSet;
import java.util.regex.Pattern;

/** Permission-filtered BM25 baseline; Korean bigrams are not morphological analysis. */
public final class Retrieval {
    private static final Pattern WORD = Pattern.compile("[a-z0-9]+|[가-힣]+");
    public static final Comparator<String> CODE_POINT_ORDER = Retrieval::compareCodePoints;

    private Retrieval() {}

    public record Chunk(String text, Integer page, int startOffset, int endOffset, int ordinal) {}

    public static List<String> tokenize(String text) {
        var result = new ArrayList<String>();
        var matcher = WORD.matcher(text.toLowerCase(Locale.ROOT));
        while (matcher.find()) {
            String word = matcher.group();
            if (word.charAt(0) >= '가' && word.charAt(0) <= '힣' && word.length() > 1) {
                for (int i = 0; i < word.length() - 1; i++) result.add(word.substring(i, i + 2));
            } else result.add(word);
        }
        return result;
    }

    /** All offsets are Unicode code points, never UTF-16 indices. */
    public static List<Chunk> chunkContent(String content, List<Ingest.Page> pages) {
        int[] points = content.codePoints().toArray();
        var chunks = new ArrayList<Chunk>();
        for (var page : pages) {
            int start = page.startOffset();
            while (start < page.endOffset()) {
                int end = Math.min(start + 1000, page.endOffset());
                if (end < page.endOffset()) {
                    for (int boundary = end - 1; boundary >= start + 500; boundary--) {
                        if (points[boundary] == '\n' || points[boundary] == ' ') {
                            end = boundary + 1;
                            break;
                        }
                    }
                }
                String text = new String(points, start, end - start);
                if (!Ingest.isBlank(text)) {
                    chunks.add(new Chunk(text, page.page(), start, end, chunks.size()));
                }
                if (end == page.endOffset()) break;
                start = Math.max(start + 1, end - 150);
            }
        }
        return chunks;
    }

    /** Caller MUST provide only currently visible chunks: IDF uses this corpus only. */
    public static List<Map<String, Object>> rankChunks(
            String query, List<Map<String, Object>> candidates, int limit) {
        var terms = new TreeSet<String>(CODE_POINT_ORDER);
        terms.addAll(tokenize(query));
        if (candidates.isEmpty() || terms.isEmpty()) return List.of();
        var frequencies = new ArrayList<Map<String, Integer>>();
        var documentFrequency = new HashMap<String, Integer>();
        int[] lengths = new int[candidates.size()];
        long totalLength = 0;
        for (int i = 0; i < candidates.size(); i++) {
            var frequency = new HashMap<String, Integer>();
            for (String term : tokenize((String) candidates.get(i).get("text"))) {
                frequency.merge(term, 1, Integer::sum);
                lengths[i]++;
            }
            frequencies.add(frequency);
            totalLength += lengths[i];
            for (String term : frequency.keySet()) documentFrequency.merge(term, 1, Integer::sum);
        }
        double averageLength = totalLength == 0 ? 1.0 : (double) totalLength / candidates.size();
        var scored = new ArrayList<Map<String, Object>>();
        for (int i = 0; i < candidates.size(); i++) {
            double score = 0;
            for (String term : terms) {
                int tf = frequencies.get(i).getOrDefault(term, 0);
                if (tf == 0) continue;
                int df = documentFrequency.get(term);
                double idf = Math.log(1 + (candidates.size() - df + 0.5) / (df + 0.5));
                score += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * lengths[i] / averageLength));
            }
            if (score > 0) {
                var hit = new LinkedHashMap<>(candidates.get(i));
                // Match Python round(double, 8), including ties against the actual binary value.
                hit.put("score", new BigDecimal(score).setScale(8, RoundingMode.HALF_EVEN).doubleValue());
                scored.add(hit);
            }
        }
        scored.sort(Comparator.<Map<String, Object>>comparingDouble(row -> -((Number) row.get("score")).doubleValue())
                .thenComparing(row -> (String) row.getOrDefault("filename", ""), CODE_POINT_ORDER)
                .thenComparing(row -> (String) row.getOrDefault("title", ""), CODE_POINT_ORDER)
                .thenComparingInt(row -> ((Number) row.getOrDefault("start_offset", 0)).intValue())
                .thenComparing(row -> (String) row.get("text"), CODE_POINT_ORDER)
                .thenComparing(row -> (String) row.get("chunk_id"), CODE_POINT_ORDER));
        int count = limit < 0 ? Math.max(0, scored.size() + limit) : Math.min(limit, scored.size());
        return new ArrayList<>(scored.subList(0, count));
    }

    private static int compareCodePoints(String left, String right) {
        int a = 0, b = 0;
        while (a < left.length() && b < right.length()) {
            int x = left.codePointAt(a), y = right.codePointAt(b);
            if (x != y) return Integer.compare(x, y);
            a += Character.charCount(x);
            b += Character.charCount(y);
        }
        return Integer.compare(left.length() - a, right.length() - b);
    }
}
