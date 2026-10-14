package io.doctrail;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

/** Synthetic worker failures exercise HTTP transport, not model quality. */
class GenerationLanguageBoundaryTest {
    @ParameterizedTest
    @CsvSource({
        "502,generation_language_mismatch,generation_language_mismatch",
        "503,generation_language_mismatch,generation_unavailable",
        "502,unknown_private_error,generation_unavailable",
        "502,generation_semantic_rejected,generation_unavailable"
    })
    void onlyRecognizedLanguageFailureCrossesTheBoundary(int workerStatus, String code, String safeCode) throws Exception {
        var worker = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var body = ("{\"error\":\"" + code + "\",\"detail\":\"SYNTHETIC_PRIVATE_SOURCE\"}")
                .getBytes(StandardCharsets.UTF_8);
        worker.createContext("/answer", exchange -> {
            try {
                exchange.sendResponseHeaders(workerStatus, body.length);
                exchange.getResponseBody().write(body);
            } finally { exchange.close(); }
        });
        worker.start();
        try {
            var client = new GenerationClient("http://127.0.0.1:" + worker.getAddress().getPort(),
                    "synthetic-language-boundary-token-123456", 2000, new ObjectMapper());
            var error = catchThrowableOfType(() -> client.call("/answer", Map.of()), ApiError.class);
            assertThat(error).hasMessage(safeCode).hasMessageNotContaining("SYNTHETIC_PRIVATE_SOURCE")
                    .hasMessageNotContaining("insufficient_evidence");
            assertThat(error.status).isEqualTo(503);
        } finally { worker.stop(0); }
    }
}
