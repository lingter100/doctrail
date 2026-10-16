package io.doctrail;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

/** Synthetic local HTTP boundary checks, not real generation quality measurements. */
class GenerationClientTest {
    HttpServer worker;ExecutorService executor;String token="synthetic-local-generation-token-123456";volatile String response="{\"schema_version\":1,\"model\":\"fake\",\"revision\":\"fixture\"}";volatile int status=200;volatile long delay;volatile String authorization;
    @BeforeEach void setup()throws Exception{worker=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);executor=Executors.newCachedThreadPool();worker.setExecutor(executor);worker.createContext("/",exchange->{authorization=exchange.getRequestHeaders().getFirst("Authorization");try{if(delay>0)Thread.sleep(delay);byte[] bytes=response.getBytes(StandardCharsets.UTF_8);exchange.sendResponseHeaders(status,bytes.length);exchange.getResponseBody().write(bytes);}catch(Exception ignored){}finally{exchange.close();}});worker.start();}
    @AfterEach void close(){worker.stop(0);executor.shutdownNow();}
    GenerationClient client(long timeout){return new GenerationClient("http://127.0.0.1:"+worker.getAddress().getPort(),token,timeout,new ObjectMapper());}
    @Test void authenticatedLoopbackContract(){assertThat(client(2000).call("/analyze",Map.of("schema_version",1)).path("model").asText()).isEqualTo("fake");assertThat(authorization).isEqualTo("Bearer "+token);}
    @ParameterizedTest @ValueSource(strings={"https://127.0.0.1:9000","http://localhost:9000","http://example.test:9000","http://127.0.0.1:9000/path","http://user@127.0.0.1:9000","http://127.0.0.1:9000/?secret=x"}) void externalOrAmbiguousTargetsRejected(String url){assertThatThrownBy(()->new GenerationClient(url,token,1000,new ObjectMapper())).hasMessage("invalid_generation_configuration");}
    @ParameterizedTest @ValueSource(strings={"{}","[]","{\"schema_version\":1,\"schema_version\":1,\"model\":\"fake\",\"revision\":\"fixture\"}","{\"schema_version\":1,\"model\":\"fake\",\"revision\":\"fixture\"} {}","{\"schema_version\":4294967297,\"model\":\"fake\",\"revision\":\"fixture\"}"}) void malformedResponsesFailClosedWithoutBody(String body){response=body;assertThatThrownBy(()->client(2000).call("/answer",Map.of())).isInstanceOf(ApiError.class).hasMessageNotContaining(body);}
    @Test void limitsTimeoutAndUnknownErrors(){response="x".repeat(InferenceClient.MAX_RESPONSE+1);assertThatThrownBy(()->client(2000).call("/analyze",Map.of())).isInstanceOf(ApiError.class);response="PRIVATE SOURCE CONTENT";status=500;assertThatThrownBy(()->client(2000).call("/analyze",Map.of())).hasMessage("generation_unavailable");status=200;delay=300;assertThatThrownBy(()->client(50).call("/analyze",Map.of())).hasMessage("generation_timeout");}
    @Test void disabledDoesNotCallWorker(){assertThatThrownBy(()->new GenerationClient("","",1000,new ObjectMapper()).call("/analyze",Map.of())).hasMessage("generation_disabled");assertThat(authorization).isNull();}
}
