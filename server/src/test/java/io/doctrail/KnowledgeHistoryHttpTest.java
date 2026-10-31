package io.doctrail;

import com.fasterxml.jackson.databind.*;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;

/** Actual loopback HTTP + Spring + isolated SQLite. Only model HTTP output is synthetic. */
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT)
class KnowledgeHistoryHttpTest {
    static final ObjectMapper JSON=new ObjectMapper();
    static final Path DATABASE=database();
    static final HttpServer MODEL=model();
    static Path database(){try{return Files.createTempDirectory("doctrail-knowledge-http-").resolve("isolated.sqlite3");}catch(Exception e){throw new RuntimeException(e);}}
    static HttpServer model(){try{
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/answer",exchange->{
            var input=JSON.readTree(exchange.getRequestBody());var source=input.at("/contexts/0");
            var output=JSON.createObjectNode().put("schema_version",1).put("model","synthetic-http").put("revision","fixture-v1").put("status","answered");
            output.putArray("claims").addObject().put("text","Synthetic HTTP evidence response").putArray("citations").addObject()
                    .put("chunk_id",source.path("chunk_id").asText()).put("quote",source.path("text").asText())
                    .put("start_offset",source.path("start_offset").asInt()).put("end_offset",source.path("end_offset").asInt());
            byte[] body=JSON.writeValueAsBytes(output);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);exchange.close();
        });server.start();return server;
    }catch(Exception e){throw new RuntimeException(e);}}
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r){
        r.add("doctrail.db",DATABASE::toString);r.add("doctrail.generation-url",()->"http://127.0.0.1:"+MODEL.getAddress().getPort());
        r.add("doctrail.generation-token",()->"synthetic-local-token-1234567890123456");r.add("doctrail.rag-answer-enabled",()->true);
    }
    @AfterAll static void closeModel(){MODEL.stop(0);}
    @LocalServerPort int port;@Autowired Store store;@Autowired DocumentService docs;
    HttpResponse<String> send(String method,String path,Object body,String cookie)throws Exception{
        try(var http=HttpClient.newBuilder().proxy(ProxySelector.of(null)).connectTimeout(Duration.ofSeconds(3)).build()){
            var request=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+path)).timeout(Duration.ofSeconds(8));
            if(cookie!=null)request.header("Cookie",cookie);request.header("Content-Type","application/json");
            request.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body)));
            return http.send(request.build(),HttpResponse.BodyHandlers.ofString());
        }
    }
    JsonNode ok(HttpResponse<String> r,int status)throws Exception{assertThat(r.statusCode()).isEqualTo(status);return JSON.readTree(r.body());}
    @Test void realHttpHistoryFeedbackReauthenticationAndLegacyFlow()throws Exception{
        String email=Auth.uid()+"@example.test";var registration=send("POST","/auth/register",Map.of("email",email,"password","synthetic-password","name","Synthetic","workspace_name","HTTP fixture"),null);
        var account=ok(registration,201);String cookie=registration.headers().firstValue("set-cookie").orElseThrow().split(";",2)[0];
        String user=account.at("/user/id").asText(),workspace=account.at("/workspaces/0/id").asText();
        String document=store.write(c->docs.upload(c,workspace,user,"http.txt","release HTTP exact evidence".getBytes(),"HTTP source","workspace")).get("id").toString();
        var query=Map.of("query","release","workspace_id",workspace,"kind","document","limit",6);
        var search=ok(send("POST","/knowledge/search",query,cookie),200);String history=search.path("history_id").asText(),result=search.at("/results/0/result_id").asText();assertThat(history).isNotBlank();assertThat(result).isNotBlank();
        ok(send("POST","/knowledge/history/"+history+"/feedback",Map.of("result_id",result,"relevant",true),cookie),200);
        ok(send("POST","/knowledge/history/"+history+"/feedback",Map.of("result_id",result,"relevant",false),cookie),200);
        var answer=ok(send("POST","/knowledge/answer",query,cookie),200);assertThat(answer.path("status").asText()).isEqualTo("answered");
        var items=ok(send("GET","/knowledge/history",null,cookie),200).path("items");assertThat(items).hasSize(2);assertThat(items.at("/0/generation_model/model").asText()).isEqualTo("synthetic-http");
        var legacy=ok(send("GET","/workspaces/"+workspace+"/search?q=release",null,cookie),200);
        ok(send("POST","/searches/"+legacy.path("search_id").asText()+"/feedback",Map.of("document_id",document,"relevant",true),cookie),200);
        assertThat(ok(send("GET","/workspaces/"+workspace+"/history",null,cookie),200).path("items")).hasSize(1);
        var login=send("POST","/auth/login",Map.of("email",email,"password","synthetic-password"),cookie);ok(login,200);String rotated=login.headers().firstValue("set-cookie").orElseThrow().split(";",2)[0];
        ok(send("GET","/knowledge/history",null,cookie),401);assertThat(ok(send("GET","/knowledge/history",null,rotated),200).path("items")).hasSize(2);
        store.write(c->{execute(c,"UPDATE documents SET revision=revision+1 WHERE id=?",document);return null;});
        assertThat(ok(send("POST","/knowledge/history/"+history+"/feedback",Map.of("result_id",result,"relevant",true),rotated),409).path("detail").asText()).isEqualTo("knowledge_result_stale");
        assertThat(ok(send("GET","/knowledge/history",null,rotated),200).at("/items/0/result_count").asInt()).isZero();
    }
}
