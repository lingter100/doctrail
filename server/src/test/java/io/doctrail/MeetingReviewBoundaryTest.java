package io.doctrail;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

/** Synthetic HTTP transport only: rejection is an error, never a successful abstention. */
class MeetingReviewBoundaryTest {
    @Test void semanticRejectionRemainsASafeFailureAcrossTheExistingJavaBoundary() throws Exception {
        var worker = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var body = "{\"error\":\"generation_semantic_rejected\",\"detail\":\"SYNTHETIC_PRIVATE_SOURCE\"}"
                .getBytes(StandardCharsets.UTF_8);
        worker.createContext("/answer", exchange -> {
            try {
                exchange.sendResponseHeaders(502, body.length);
                exchange.getResponseBody().write(body);
            } finally {
                exchange.close();
            }
        });
        worker.start();
        try {
            var client = new GenerationClient("http://127.0.0.1:" + worker.getAddress().getPort(),
                    "synthetic-review-boundary-token-123456", 2000, new ObjectMapper());
            var error = catchThrowableOfType(() -> client.call("/answer", Map.of()), ApiError.class);
            assertThat(error).hasMessage("generation_unavailable")
                    .hasMessageNotContaining("SYNTHETIC_PRIVATE_SOURCE")
                    .hasMessageNotContaining("insufficient_evidence");
            assertThat(error.status).isEqualTo(503);
        } finally {
            worker.stop(0);
        }
    }
}
