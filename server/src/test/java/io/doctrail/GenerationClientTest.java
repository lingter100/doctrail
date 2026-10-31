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
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;

/** Synthetic local HTTP boundary checks, not real generation quality measurements. */
class GenerationClientTest {
    HttpServer worker;ExecutorService executor;String token="synthetic-local-generation-token-123456";volatile String response="{\"schema_version\":1,\"model\":\"fake\",\"revision\":\"fixture\"}";volatile int status=200;volatile long delay;volatile String authorization;volatile String budgetHeader;volatile Runnable beforeResponse=()->{};AtomicInteger requests=new AtomicInteger();
    @BeforeEach void setup()throws Exception{worker=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);executor=Executors.newCachedThreadPool();worker.setExecutor(executor);worker.createContext("/",exchange->{requests.incrementAndGet();authorization=exchange.getRequestHeaders().getFirst("Authorization");budgetHeader=exchange.getRequestHeaders().getFirst("X-DocTrail-Request-Budget-Ms");try{if(delay>0)Thread.sleep(delay);beforeResponse.run();byte[] bytes=response.getBytes(StandardCharsets.UTF_8);exchange.sendResponseHeaders(status,bytes.length);exchange.getResponseBody().write(bytes);}catch(Exception ignored){}finally{exchange.close();}});worker.start();}
    @AfterEach void close(){worker.stop(0);executor.shutdownNow();}
    GenerationClient client(long timeout){return new GenerationClient("http://127.0.0.1:"+worker.getAddress().getPort(),token,timeout,new ObjectMapper());}
    @Test void authenticatedLoopbackContract(){assertThat(client(2000).call("/analyze",Map.of("schema_version",1)).path("model").asText()).isEqualTo("fake");assertThat(authorization).isEqualTo("Bearer "+token);}
    @ParameterizedTest @ValueSource(strings={"https://127.0.0.1:9000","http://localhost:9000","http://example.test:9000","http://127.0.0.1:9000/path","http://user@127.0.0.1:9000","http://127.0.0.1:9000/?secret=x"}) void externalOrAmbiguousTargetsRejected(String url){assertThatThrownBy(()->new GenerationClient(url,token,1000,new ObjectMapper())).hasMessage("invalid_generation_configuration");}
    @ParameterizedTest @ValueSource(strings={"{}","[]","{\"schema_version\":1,\"schema_version\":1,\"model\":\"fake\",\"revision\":\"fixture\"}","{\"schema_version\":1,\"model\":\"fake\",\"revision\":\"fixture\"} {}","{\"schema_version\":4294967297,\"model\":\"fake\",\"revision\":\"fixture\"}"}) void malformedResponsesFailClosedWithoutBody(String body){response=body;assertThatThrownBy(()->client(2000).call("/answer",Map.of())).isInstanceOf(ApiError.class).hasMessageNotContaining(body);}
    @Test void limitsTimeoutAndUnknownErrors(){response="x".repeat(InferenceClient.MAX_RESPONSE+1);assertThatThrownBy(()->client(2000).call("/analyze",Map.of())).isInstanceOf(ApiError.class);response="PRIVATE SOURCE CONTENT";status=500;assertThatThrownBy(()->client(2000).call("/analyze",Map.of())).hasMessage("generation_unavailable");status=200;delay=300;assertThatThrownBy(()->client(50).call("/analyze",Map.of())).hasMessage("generation_timeout");}
    @Test void disabledDoesNotCallWorker(){assertThatThrownBy(()->new GenerationClient("","",1000,new ObjectMapper()).call("/analyze",Map.of())).hasMessage("generation_disabled");assertThat(authorization).isNull();}
    @Test void reasoningTimeoutRequiresExplicitProfileAndDoesNotChangeLegacyConstructor(){
        assertThatThrownBy(()->client(120001)).hasMessage("invalid_generation_configuration");
        assertThatThrownBy(()->new GenerationClient("","",150000,new ObjectMapper(),"legacy")).hasMessage("invalid_generation_configuration");
        assertThat(new GenerationClient("","",120000,new ObjectMapper()).enabled()).isFalse();
        assertThat(new GenerationClient("","",150000,new ObjectMapper(),GenerationClient.REASONING_TIMEOUT_PROFILE).enabled()).isFalse();
        assertThatThrownBy(()->new GenerationClient("","",150001,new ObjectMapper(),GenerationClient.REASONING_TIMEOUT_PROFILE)).hasMessage("invalid_generation_configuration");
        for(String profile:new String[]{"other","",null})assertThatThrownBy(()->new GenerationClient("","",1000,new ObjectMapper(),profile)).hasMessage("invalid_generation_configuration");
    }
    @Test void reasoningDirectTransportKeepsOldRagBudgetSeparate(){
        var client=new GenerationClient("http://127.0.0.1:"+worker.getAddress().getPort(),token,150000,new ObjectMapper(),GenerationClient.REASONING_TIMEOUT_PROFILE);
        assertThat(client.call("/answer",Map.of()).path("model").asText()).isEqualTo("fake");
        assertThat(budgetHeader).isNull();
        assertThatThrownBy(()->client.call("/answer",Map.of(),new AnswerDeadline(System.nanoTime()-TimeUnit.SECONDS.toNanos(90)))).hasMessage("generation_timeout");
        assertThat(requests).hasValue(1);
    }
    @Test void legacyAnswerAndAnalysisDoNotSendBudgetHeader(){
        var client=client(2000);
        client.call("/answer",Map.of());assertThat(budgetHeader).isNull();
        client.call("/analyze",Map.of());assertThat(budgetHeader).isNull();
    }
    @Test void budgetHeaderUsesRemainingTimeAndConfiguredTransportCap(){
        client(120000).call("/answer",Map.of(),new AnswerDeadline(System.nanoTime()-TimeUnit.SECONDS.toNanos(30)));
        assertThat(Long.parseLong(budgetHeader)).isBetween(1L,60000L);
        client(2000).call("/answer",Map.of(),new AnswerDeadline(System.nanoTime()));
        assertThat(Long.parseLong(budgetHeader)).isBetween(1L,2000L);
    }
    @Test void expiredAndSubMillisecondBudgetsDoNotDispatch(){
        var client=client(2000);
        assertThatThrownBy(()->client.call("/answer",Map.of(),new AnswerDeadline(System.nanoTime()-TimeUnit.SECONDS.toNanos(90)))).hasMessage("generation_timeout");
        assertThatThrownBy(()->client.call("/answer",Map.of(),new AnswerDeadline(0,()->TimeUnit.SECONDS.toNanos(90)-100))).hasMessage("generation_timeout");
        assertThat(requests).hasValue(0);
    }
    @Test void sharedTransportTimeoutDoesNotRestartAtDispatch(){
        var client=client(2000);delay=300;
        assertThatThrownBy(()->client.call("/answer",Map.of(),new AnswerDeadline(System.nanoTime()-TimeUnit.MILLISECONDS.toNanos(89900)))).isInstanceOfSatisfying(ApiError.class,error->{assertThat(error.status).isEqualTo(504);assertThat(error).hasMessage("generation_timeout");});
    }
    @Test void responseArrivingAfterSharedDeadlineIsRejected(){
        AtomicLong clock=new AtomicLong();
        beforeResponse=()->clock.set(TimeUnit.SECONDS.toNanos(90));
        assertThatThrownBy(()->client(2000).call("/answer",Map.of(),new AnswerDeadline(0,clock::get))).hasMessage("generation_timeout");
        assertThat(requests).hasValue(1);
    }
    @Test void safeNewWorkerErrorsStayDistinctAndUnknownBodiesStayPrivate(){
        status=422;response="{\"error\":\"context_budget_exceeded\"}";
        assertThatThrownBy(()->client(2000).call("/answer",Map.of())).isInstanceOfSatisfying(ApiError.class,e->{assertThat(e.status).isEqualTo(422);assertThat(e).hasMessage("context_budget_exceeded");});
        status=503;response="{\"error\":\"generation_cleanup_failed\"}";
        assertThatThrownBy(()->client(2000).call("/answer",Map.of())).hasMessage("generation_cleanup_failed");
        response="{\"error\":\"private native detail\"}";
        assertThatThrownBy(()->client(2000).call("/answer",Map.of())).hasMessage("generation_unavailable");
    }
}
