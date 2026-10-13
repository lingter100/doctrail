package io.doctrail;

import com.fasterxml.jackson.databind.*;
import com.sun.net.httpserver.HttpServer;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockHttpServletRequest;
import java.net.InetSocketAddress;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;

/** Synthetic HTTP worker and invented vectors: contract/security checks, not model quality. */
class LearnedSearchTest {
    @TempDir Path temporary;
    ObjectMapper json=new ObjectMapper();HttpServer worker;ExecutorService executor;
    Store store;Auth auth;DocumentService docs=new DocumentService();MockHttpServletRequest request;
    String owner="owner",user="member",workspace="workspace",session="synthetic-session",token="synthetic-local-worker-token-1234567890";
    List<JsonNode> received=new CopyOnWriteArrayList<>();String mode="ready";volatile Runnable duringPassage=()->{};
    volatile String workerEmbedding=InferenceClient.EMBEDDING,workerRevision=InferenceClient.EMBEDDING_REVISION;
    volatile Runnable duringQuery=()->{};
    String configuredProfile="base";
    @BeforeEach void setup()throws Exception{
        store=new Store(temporary.resolve("test.sqlite3").toString());auth=new Auth("0");
        store.write(c->{for(String id:List.of(owner,user))execute(c,"INSERT INTO users VALUES (?,?,?,?)",id,id+"@example.test",id,"unused");execute(c,"INSERT INTO workspaces VALUES (?,?)",workspace,"synthetic");for(String id:List.of(owner,user))execute(c,"INSERT INTO memberships VALUES (?,?,?)",workspace,id,id.equals(owner)?"owner":"member");execute(c,"INSERT INTO sessions VALUES (?,?,?)",Auth.hash(session),user,System.currentTimeMillis()/1000.0+60);return null;});
        request=new MockHttpServletRequest();request.setCookies(new Cookie(Auth.COOKIE,session));
        worker=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);executor=Executors.newCachedThreadPool();worker.setExecutor(executor);
        worker.createContext("/",exchange->{
            try{
                if(!("Bearer "+token).equals(exchange.getRequestHeaders().getFirst("Authorization"))){exchange.sendResponseHeaders(401,-1);return;}
                Object output;
                if(exchange.getRequestURI().getPath().equals("/health"))output=Map.of("schema_version",1,"status","ready","embedding",Map.of("model",workerEmbedding,"revision",workerRevision,"dimension",384,"max_length",512),"reranker",Map.of("model",InferenceClient.RERANKER,"revision",InferenceClient.RERANKER_REVISION,"max_length",512),"limits",Map.of("max_embed_items",64,"max_rerank_items",50));
                else{
                    JsonNode input=json.readTree(exchange.getRequestBody());received.add(input);
                    if(input.path("kind").asText().equals("query"))duringQuery.run();
                    if(input.path("kind").asText().equals("passage"))duringPassage.run();
                    if(mode.startsWith("error_")){
                        int status=switch(mode){case "error_query_too_long","error_invalid_request","error_unknown","error_malformed"->422;case "error_unauthorized"->401;default->503;};
                        String code=switch(mode){case "error_query_too_long","error_wrong_status"->"query_too_long";case "error_model_busy","error_unauthorized"->"model_busy";case "error_invalid_request"->"invalid_request";default->"PRIVATE_UPSTREAM_ERROR";};
                        byte[] bytes=mode.equals("error_malformed")?"PRIVATE_NOT_JSON".getBytes():json.writeValueAsBytes(Map.of("error",code,"request_id","synthetic-request"));
                        exchange.sendResponseHeaders(status,bytes.length);exchange.getResponseBody().write(bytes);return;
                    }
                    if(mode.equals("unavailable")){exchange.sendResponseHeaders(503,-1);return;}
                    if(mode.equals("oversized")){byte[] huge=new byte[InferenceClient.MAX_RESPONSE+1];exchange.sendResponseHeaders(200,huge.length);exchange.getResponseBody().write(huge);return;}
                    List<Map<String,Object>> items=new ArrayList<>();boolean rerank=exchange.getRequestURI().getPath().equals("/rerank");
                    for(JsonNode item:input.path("items")){
                        var result=new LinkedHashMap<String,Object>();result.put("id",mode.equals("unknown_id")?"wrong-id":item.path("id").asText());
                        if(rerank)result.put("score",mode.equals("bad_score")?"NaN":-2.75);
                        else{Double[] vector=new Double[mode.equals("dimension")?383:384];Arrays.fill(vector,0.0);vector[0]=mode.equals("zero")?0.0:1.0;result.put("vector",vector);}
                        items.add(result);
                    }
                    output=Map.of("schema_version",mode.equals("huge_schema")?4294967297L:mode.equals("schema")?2:1,"model",rerank?InferenceClient.RERANKER:workerEmbedding,"revision",mode.equals("revision")?"wrong-revision":rerank?InferenceClient.RERANKER_REVISION:workerRevision,"dimension",384,"items",items);
                }
                byte[] bytes=json.writeValueAsBytes(output);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);
            }catch(Exception ignored){}finally{exchange.close();}
        });worker.start();
    }
    @AfterEach void stop(){worker.stop(0);executor.shutdownNow();}
    InferenceClient client(long timeout){return new InferenceClient("http://127.0.0.1:"+worker.getAddress().getPort(),token,timeout,configuredProfile,json);}
    LearnedSearch service(){return new LearnedSearch(store,auth,docs,client(5000));}
    InferenceClient profileClient(String profile){return new InferenceClient("http://127.0.0.1:"+worker.getAddress().getPort(),token,5000,profile,json);}
    LearnedSearch profileService(String profile){return new LearnedSearch(store,auth,docs,profileClient(profile));}
    void terminalWorker(){workerEmbedding=InferenceClient.TERMINAL_EMBEDDING;workerRevision=InferenceClient.TERMINAL_REVISION;}
    void selectProfile(String profile){configuredProfile=profile;if(profile.equals("m4-terminal-v1"))terminalWorker();}
    String document(String content,String visibility){return store.write(c->(String)docs.upload(c,workspace,owner,"guide.txt",content.getBytes(java.nio.charset.StandardCharsets.UTF_8),null,visibility).get("id"));}
    int historyCount(){return store.read(c->((Number)one(c,"SELECT COUNT(*) AS n FROM searches").get("n")).intValue());}
    @ParameterizedTest @ValueSource(strings={"base","m4-terminal-v1"})
    void aclPrefilterPersistsMethodsAndOnlyPublicResultFields(String profile){
        selectProfile(profile);
        String visible=document("refund visible evidence","workspace");document("PRIVATE_NEVER_SEND","private");
        var service=service();assertThat(service.capabilities(request)).containsEntry("status","ready").containsEntry("model_enabled",true);
        for(String method:List.of("dense","hybrid","hybrid_rerank")){
            var result=service.search(workspace,"refund",10,method,request);assertThat(result.get("method")).isEqualTo(method);
            var hits=(List<Map<String,Object>>)result.get("results");assertThat(hits).hasSize(1);assertThat(hits.getFirst()).containsEntry("document_id",visible).doesNotContainKeys("owner_id","visibility","ordinal","updated_at");
            assertThat((Object)store.read(c->one(c,"SELECT method FROM search_metadata WHERE search_id=?",result.get("search_id")).get("method"))).isEqualTo(method);
            if(method.equals("hybrid_rerank"))assertThat(hits.getFirst().get("score")).isEqualTo(-2.75);
        }
        assertThat(received.toString()).contains("refund visible evidence").doesNotContain("PRIVATE_NEVER_SEND");assertThat(historyCount()).isEqualTo(3);
    }
    @ParameterizedTest @ValueSource(strings={"dimension","zero","unknown_id","schema","huge_schema","revision","bad_score","unavailable","oversized"})
    void invalidOrUnavailableWorkerNeverFallsBackOrWritesHistory(String fault){
        document("refund evidence","workspace");mode=fault;
        assertThatThrownBy(()->service().search(workspace,"refund",10,"hybrid_rerank",request)).isInstanceOfSatisfying(ApiError.class,e->assertThat(e.status).isEqualTo(503));
        assertThat(historyCount()).isZero();
    }
    @ParameterizedTest @ValueSource(strings={"error_query_too_long","error_model_busy","error_unknown","error_malformed","error_wrong_status","error_invalid_request","error_unauthorized"})
    void onlyWhitelistedWorkerStatusAndCodePairsReachPublicErrors(String fault){
        document("refund evidence","workspace");mode=fault;
        assertThatThrownBy(()->service().search(workspace,"refund",10,"dense",request)).isInstanceOfSatisfying(ApiError.class,e->{
            assertThat(e.status).isEqualTo(fault.equals("error_query_too_long")?422:503);
            assertThat(e.getMessage()).isEqualTo(switch(fault){case "error_query_too_long"->"query_too_long";case "error_model_busy"->"inference_busy";default->"inference_unavailable";});
        });assertThat(historyCount()).isZero();
    }
    static java.util.stream.Stream<Arguments> mutationProfiles(){
        return List.of("base","m4-terminal-v1").stream().flatMap(profile->List.of("edit","delete","private","new_document","new_visible","membership","logout").stream().map(change->Arguments.of(profile,change)));
    }
    @ParameterizedTest @MethodSource("mutationProfiles")
    void mutationDuringInferenceFinishesWithoutLockAndRejectsStaleSearch(String profile,String change)throws Exception{
        selectProfile(profile);
        String id=document("refund original","workspace"),privateId=document("private prior","private");
        CountDownLatch arrived=new CountDownLatch(1),release=new CountDownLatch(1);
        duringPassage=()->{arrived.countDown();try{if(!release.await(5,TimeUnit.SECONDS))throw new IllegalStateException();}catch(InterruptedException e){Thread.currentThread().interrupt();}};
        Future<?> future=executor.submit(()->service().search(workspace,"refund",10,"hybrid_rerank",request));
        assertThat(arrived.await(5,TimeUnit.SECONDS)).isTrue();
        try{
            store.write(c->{switch(change){
                case "edit"->docs.edit(c,id,owner,"edited","refund revision two","workspace");
                case "delete"->execute(c,"DELETE FROM documents WHERE id=?",id);
                case "private"->execute(c,"UPDATE documents SET visibility='private' WHERE id=?",id);
                case "new_document"->docs.upload(c,workspace,owner,"new.txt","refund newly visible".getBytes(),null,"workspace");
                case "new_visible"->execute(c,"UPDATE documents SET visibility='workspace' WHERE id=?",privateId);
                case "membership"->execute(c,"DELETE FROM memberships WHERE workspace_id=? AND user_id=?",workspace,user);
                case "logout"->execute(c,"DELETE FROM sessions WHERE token_hash=?",Auth.hash(session));
                default->throw new IllegalStateException();
            }return null;});
        }finally{release.countDown();}
        assertThatThrownBy(()->future.get(5,TimeUnit.SECONDS)).isInstanceOf(ExecutionException.class).cause().isInstanceOfSatisfying(ApiError.class,e->{assertThat(e.status).isEqualTo(change.equals("logout")?401:409);assertThat(e.getMessage()).isEqualTo(change.equals("logout")?"authentication_required":"search_context_changed");});
        assertThat(historyCount()).isZero();
    }
    @ParameterizedTest @ValueSource(strings={"base","m4-terminal-v1"})
    void totalDeadlineAndWorkerDownHaveSafeErrors(String profile){
        selectProfile(profile);
        document("refund evidence","workspace");duringPassage=()->{try{Thread.sleep(700);}catch(InterruptedException e){Thread.currentThread().interrupt();}};
        var shortService=new LearnedSearch(store,auth,docs,client(250));
        assertThatThrownBy(()->shortService.search(workspace,"refund",10,"dense",request)).isInstanceOfSatisfying(ApiError.class,e->assertThat(e.status).isEqualTo(504));
        assertThat(historyCount()).isZero();worker.stop(0);
        assertThat(service().capabilities(request)).containsEntry("status","unavailable").containsEntry("available_methods",List.of("bm25"));
        assertThatThrownBy(()->service().search(workspace,"refund",10,"dense",request)).isInstanceOfSatisfying(ApiError.class,e->assertThat(e.status).isEqualTo(503));
        assertThat(historyCount()).isZero();
    }
    @Test void batchingCapAndSchemaOneCompatibility(){
        String id=document("refund evidence","workspace");
        store.write(c->{execute(c,"DELETE FROM chunks WHERE document_id=?",id);for(int i=0;i<129;i++)execute(c,"INSERT INTO chunks VALUES (?,?,?,?,?,?,?)","chunk"+i,id,"refund passage "+i,null,i*10,i*10+5,i);return null;});
        service().search(workspace,"refund",10,"dense",request);
        assertThat(received.stream().filter(r->r.path("kind").asText().equals("passage")).map(r->r.path("items").size()).toList()).containsExactly(64,64,1);
        received.clear();store.write(c->{for(int i=129;i<4097;i++)execute(c,"INSERT INTO chunks VALUES (?,?,?,?,?,?,?)","chunk"+i,id,"refund",null,i*10,i*10+5,i);return null;});
        assertThatThrownBy(()->service().search(workspace,"refund",10,"dense",request)).isInstanceOfSatisfying(ApiError.class,e->assertThat(e.status).isEqualTo(422));assertThat(received).isEmpty();
        Store reopened=new Store(temporary.resolve("test.sqlite3").toString());assertThat((Object)reopened.read(c->one(c,"PRAGMA user_version").get("user_version"))).isEqualTo(1);
        store.write(c->{execute(c,"INSERT INTO searches VALUES ('legacy',?,?,?,?)",workspace,user,"old query",Auth.now());return null;});
        assertThat((Object)store.read(c->one(c,"SELECT COALESCE(m.method,'bm25') AS method FROM searches s LEFT JOIN search_metadata m ON m.search_id=s.id WHERE s.id='legacy'").get("method"))).isEqualTo("bm25");
    }
    @Test void disabledAndUnauthenticatedCapabilities(){
        var disabled=new LearnedSearch(store,auth,docs,new InferenceClient("","",120000,json));
        assertThat(disabled.capabilities(request)).containsEntry("status","disabled").containsEntry("available_methods",List.of("bm25"));
        request.setCookies();assertThatThrownBy(()->disabled.capabilities(request)).isInstanceOfSatisfying(ApiError.class,e->assertThat(e.status).isEqualTo(401));
    }
    @ParameterizedTest @ValueSource(strings={"http://localhost:8091","http://127.0.0.2:8091","https://127.0.0.1:8091","http://127.0.0.1","http://user@127.0.0.1:8091","http://127.0.0.1:8091/path","http://127.0.0.1:8091/?secret=x","http://127.0.0.1:8091/#x"})
    void rejectsUnsafeUrls(String url){assertThatThrownBy(()->new InferenceClient(url,token,120000,json)).isInstanceOf(IllegalArgumentException.class).hasMessage("invalid_inference_configuration");}
    @Test void balancedPolicyProtectsTopTwentyFiveAndRanksFullBranchRrf(){
        List<Map<String,Object>> corpus=new ArrayList<>();for(int i=0;i<100;i++)corpus.add(Map.of("document_id",String.format("d%03d",i),"chunk_id","c"+i,"ordinal",i));
        var bm25=corpus.subList(0,50);var dense=corpus.subList(50,100);var fused=LearnedSearch.fuse(bm25,dense,corpus);var selected=LearnedSearch.balanced(bm25,dense,fused);
        assertThat(selected).hasSize(50);assertThat(selected.stream().map(r->r.get("chunk_id")).toList()).containsAll(bm25.subList(0,25).stream().map(r->r.get("chunk_id")).toList()).containsAll(dense.subList(0,25).stream().map(r->r.get("chunk_id")).toList());
        assertThat(selected.getFirst()).containsEntry("chunk_id","c0").containsEntry("score",1.0/61);
    }
    @Test void rerankerTiesPreserveRrfOrder(){
        var first=Map.<String,Object>of("document_id","z","chunk_id","first","ordinal",0);
        var second=Map.<String,Object>of("document_id","a","chunk_id","second","ordinal",0);
        assertThat(LearnedSearch.rerankScores(List.of(first,second),Map.of("first",-2.0,"second",-2.0),10).stream().map(r->r.get("chunk_id"))).containsExactly("first","second");
    }
    @ParameterizedTest @ValueSource(strings={"base","m4-terminal-v1"})
    void singleFlightRejectsConcurrentSearchAndReleasesAfterCompletion(String profile)throws Exception{
        selectProfile(profile);
        document("refund evidence","workspace");var service=service();CountDownLatch arrived=new CountDownLatch(1),release=new CountDownLatch(1);
        duringPassage=()->{arrived.countDown();try{release.await(5,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}};
        Future<?> active=executor.submit(()->service.search(workspace,"refund",10,"dense",request));assertThat(arrived.await(5,TimeUnit.SECONDS)).isTrue();
        try{assertThatThrownBy(()->service.search(workspace,"refund",10,"dense",request)).isInstanceOfSatisfying(ApiError.class,e->{assertThat(e.status).isEqualTo(503);assertThat(e.getMessage()).isEqualTo("inference_busy");});}
        finally{release.countDown();}
        active.get(5,TimeUnit.SECONDS);service.search(workspace,"refund",10,"dense",request);assertThat(historyCount()).isEqualTo(2);
    }
    @ParameterizedTest @ValueSource(strings={"base","m4-terminal-v1"})
    void expectedProfileRejectsOppositeWorkerAtHealthWithoutHistory(String profile){
        document("synthetic evidence","workspace");
        if(profile.equals("base"))terminalWorker();
        var service=profileService(profile);
        assertThat(service.capabilities(request)).containsEntry("status","unavailable").containsEntry("embedding_profile",profileClient(profile).embeddingProfile());
        assertThatThrownBy(()->service.search(workspace,"evidence",10,"dense",request)).isInstanceOfSatisfying(ApiError.class,e->{assertThat(e.status).isEqualTo(503);assertThat(e.getMessage()).isEqualTo("inference_invalid_response");});
        assertThat(received).isEmpty();assertThat(historyCount()).isZero();
    }
    @ParameterizedTest @ValueSource(strings={"query","first_passage","later_passage"})
    void terminalIdentityDriftAtEveryEmbeddingResponseFailsClosed(String stage){
        terminalWorker();String id=document("synthetic evidence","workspace");
        store.write(c->{for(int i=1;i<66;i++)execute(c,"INSERT INTO chunks VALUES (?,?,?,?,?,?,?)","extra"+i,id,"synthetic evidence",null,i*10,i*10+5,i);return null;});
        Runnable drift=()->{workerEmbedding=InferenceClient.EMBEDDING;workerRevision=InferenceClient.EMBEDDING_REVISION;};
        if(stage.equals("query"))duringQuery=drift;
        else duringPassage=()->{if(stage.equals("first_passage")||received.stream().filter(r->r.path("kind").asText().equals("passage")).count()==2)drift.run();};
        assertThatThrownBy(()->profileService("m4-terminal-v1").search(workspace,"evidence",10,"hybrid_rerank",request)).isInstanceOfSatisfying(ApiError.class,e->assertThat(e.getMessage()).isEqualTo("inference_invalid_response"));
        assertThat(historyCount()).isZero();
        assertThat(received).hasSize(stage.equals("query")?1:stage.equals("first_passage")?2:3);
    }
    @Test void successfulTerminalProfileSurvivesRestartAndBaseRollbackWithoutRelabelingLegacy(){
        terminalWorker();document("synthetic evidence","workspace");var terminal=profileService("m4-terminal-v1");
        var result=terminal.search(workspace,"evidence",10,"hybrid_rerank","m4-terminal-v1",request);
        assertThat(result.get("embedding_profile")).isEqualTo(profileClient("m4-terminal-v1").embeddingProfile());
        store.write(c->{
            execute(c,"INSERT INTO searches VALUES ('legacy-learned',?,?,?,?)",workspace,user,"legacy learned",Auth.now());
            execute(c,"INSERT INTO search_metadata VALUES ('legacy-learned','dense')");
            execute(c,"INSERT INTO searches VALUES ('legacy-bm25',?,?,?,?)",workspace,user,"legacy lexical",Auth.now());return null;
        });
        store=new Store(temporary.resolve("test.sqlite3").toString());
        workerEmbedding=InferenceClient.EMBEDDING;workerRevision=InferenceClient.EMBEDDING_REVISION;
        var base=service();var controller=new ApiController(store,auth,docs,base);
        assertThat(base.capabilities(request)).containsEntry("embedding_profile",client(5000).embeddingProfile());
        var history=(List<Map<String,Object>>)controller.history(workspace,request).get("items");
        assertThat(history.stream().filter(h->h.get("id").equals(result.get("search_id"))).findFirst().orElseThrow()).containsEntry("embedding_profile",result.get("embedding_profile"));
        assertThat(history.stream().filter(h->h.get("id").toString().startsWith("legacy")).toList()).hasSize(2).allSatisfy(h->assertThat(h).containsEntry("embedding_profile",null));
        received.clear();
        assertThatThrownBy(()->controller.search(workspace,"evidence",10,"dense","m4-terminal-v1",request)).isInstanceOfSatisfying(ApiError.class,e->{assertThat(e.status).isEqualTo(409);assertThat(e.getMessage()).isEqualTo("embedding_profile_changed");});
        assertThat(historyCount()).isEqualTo(3);assertThat(received).isEmpty();
        var lexical=controller.search(workspace,"evidence",10,"bm25",null,request);assertThat(lexical).doesNotContainKey("embedding_profile");
        assertThat((List<Map<String,Object>>)controller.history(workspace,request).get("items")).filteredOn(h->h.get("id").equals(lexical.get("search_id"))).allSatisfy(h->assertThat(h).containsEntry("embedding_profile",null));
        var fresh=base.search(workspace,"evidence",10,"dense","base",request);assertThat(fresh.get("embedding_profile")).isEqualTo(client(5000).embeddingProfile());
    }
    @Test void profileMigrationIsAdditiveAndPreservesExistingLearnedRows(){
        store.write(c->{execute(c,"DROP TABLE search_model_metadata");execute(c,"INSERT INTO searches VALUES ('prior',?,?,?,?)",workspace,user,"synthetic prior",Auth.now());execute(c,"INSERT INTO search_metadata VALUES ('prior','dense')");return null;});
        store=new Store(temporary.resolve("test.sqlite3").toString());
        assertThat((Object)store.read(c->one(c,"SELECT COUNT(*) AS n FROM search_model_metadata").get("n"))).isEqualTo(0);
        var history=(List<Map<String,Object>>)new ApiController(store,auth,docs,service()).history(workspace,request).get("items");
        assertThat(history).hasSize(1);assertThat(history.getFirst()).containsEntry("method","dense").containsEntry("embedding_profile",null);
    }
    @ParameterizedTest @ValueSource(strings={"","terminal","BASE","../checkpoint","arbitrary/model"})
    void onlyAllowlistedServerProfilesCanStart(String profile){assertThatThrownBy(()->profileClient(profile)).isInstanceOf(IllegalArgumentException.class).hasMessage("invalid_embedding_profile");}
    @Test void expectedProfileGuardStillAuthenticatesBeforeDisclosingMismatch(){
        request.setCookies();assertThatThrownBy(()->service().search(workspace,"evidence",10,"dense","m4-terminal-v1",request)).isInstanceOfSatisfying(ApiError.class,e->assertThat(e.status).isEqualTo(401));
        assertThat(historyCount()).isZero();
    }
}
