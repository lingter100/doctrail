package io.doctrail;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.web.MockHttpServletRequest;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;

/** Real SQLite and service operations; only generation transport is synthetic. */
class KnowledgeHistoryTest {
    @TempDir Path temp;
    ObjectMapper json=new ObjectMapper();DocumentService docs=new DocumentService();Auth auth=new Auth("0");
    Store store;MeetingService meetings;KnowledgeService knowledge;MockHttpServletRequest request,otherRequest;
    String document,second,meeting;Runnable during=()->{};String mode="answered";
    @BeforeEach void setup(){
        store=new Store(temp.resolve("history.sqlite3").toString());
        store.write(c->{
            for(String id:List.of("owner","other")){execute(c,"INSERT INTO users VALUES (?,?,?,?)",id,id+"@example.test",id,"unused");execute(c,"INSERT INTO sessions VALUES (?,?,?)",Auth.hash(id),id,System.currentTimeMillis()/1000.0+300);}
            for(String id:List.of("one","two")){execute(c,"INSERT INTO workspaces VALUES (?,?)",id,id);execute(c,"INSERT INTO memberships VALUES (?,?,'owner')",id,"owner");}
            execute(c,"INSERT INTO memberships VALUES ('one','other','member')");return null;
        });
        request=req("owner");otherRequest=req("other");
        GenerationClient generation=new GenerationClient("","",1000,json){@Override JsonNode call(String path,Object body){
            during.run();if(mode.equals("error"))throw new ApiError(503,"generation_unavailable");
            var out=json.createObjectNode().put("schema_version",1).put("model","synthetic").put("revision","fixture").put("status",mode);
            var claims=out.putArray("claims");if(mode.equals("abstained"))out.put("reason","insufficient_evidence");
            else{var source=json.valueToTree(body).at("/contexts/0");claims.addObject().put("text","Synthetic claim").putArray("citations").addObject().put("chunk_id",source.path("chunk_id").asText()).put("quote",source.path("text").asText()).put("start_offset",source.path("start_offset").asInt()).put("end_offset",source.path("end_offset").asInt());}
            return out;
        }};
        meetings=new MeetingService(store,auth,docs,json,generation);var inference=new InferenceClient("","",1000,json);
        knowledge=new KnowledgeService(store,auth,docs,meetings,new LearnedSearch(store,auth,docs,inference),inference,generation,json);
        document=upload("one","owner","workspace","release evidence 😀");second=upload("two","owner","workspace","release second evidence");
        upload("one","other","private","release private secret");
        meeting=store.write(c->{var detail=meetings.upload(c,"one","owner","meeting.txt","release meeting evidence".getBytes(StandardCharsets.UTF_8),"meeting title","workspace");return ((Map<?,?>)detail.get("document")).get("id").toString();});
    }
    @AfterEach void close(){meetings.close();}
    MockHttpServletRequest req(String token){var r=new MockHttpServletRequest();r.setCookies(new Cookie(Auth.COOKIE,token));return r;}
    String upload(String workspace,String user,String visibility,String text){return store.write(c->docs.upload(c,workspace,user,"fixture.txt",text.getBytes(StandardCharsets.UTF_8),"source title",visibility)).get("id").toString();}
    ObjectNode body(){return json.createObjectNode().put("query","release").put("limit",7);}
    JsonNode run(ObjectNode body,boolean answer){return json.valueToTree(knowledge.execute(body,request,answer));}
    JsonNode list(){return json.valueToTree(knowledge.history.list(request)).get("items");}
    long count(String table){return store.read(c->((Number)one(c,"SELECT count(*) AS n FROM "+table).get("n")).longValue());}
    JsonNode feedback(JsonNode response,boolean relevant){return json.createObjectNode().put("result_id",response.at("/results/0/result_id").asText()).put("relevant",relevant);}
    void error(int status,String message,Runnable work){assertThatThrownBy(work::run).isInstanceOfSatisfying(ApiError.class,e->{assertThat(e.status).isEqualTo(status);assertThat(e).hasMessage(message);});}

    @Test void completedSearchAnswerAndAbstentionsSaveOnlyIdentityMetadataAndSurviveRestart(){
        var search=run(body(),false);assertThat(search.get("results")).hasSize(3);assertThat(search.toString()).doesNotContain("private secret");
        run(body(),true);mode="abstained";run(body(),true);run(body().put("query","absentword"),true);run(body().put("query","absentword"),false);
        var items=list();assertThat(items).hasSize(5);assertThat(items.get(0).path("status").asText()).isEqualTo("searched");
        assertThat(items.get(1).path("model_called").asBoolean()).isFalse();assertThat(items.get(1).path("generation_model").isNull()).isTrue();
        assertThat(items.get(2).path("generation_model").path("model").asText()).isEqualTo("synthetic");
        assertThat(items.get(3).path("status").asText()).isEqualTo("answered");assertThat(items.get(4).path("workspace_id").isNull()).isTrue();
        assertThat(items.toString()).doesNotContain("source title","Synthetic claim","release evidence","text","citations");
        assertThat(items.get(4).at("/filters/limit").asInt()).isEqualTo(7);assertThat(items.get(4).path("embedding_profile").isNull()).isTrue();
        Store restarted=new Store(temp.resolve("history.sqlite3").toString());new Store(temp.resolve("history.sqlite3").toString());
        assertThat((List<?>)restarted.read(c->rows(c,"SELECT * FROM knowledge_history"))).hasSize(5);
        var columns=store.read(c->rows(c,"PRAGMA table_info(knowledge_history_results)"));assertThat(columns.stream().map(r->r.get("name"))).containsExactly("id","history_id","document_id","revision","chunk_id","start_offset","end_offset","evidence_sha256");
    }
    @Test void feedbackUpsertsAndRejectsForgedOwnershipAndMalformedInput(){
        var first=run(body(),false);var next=run(body(),false);String id=first.path("history_id").asText();
        knowledge.history.feedback(id,feedback(first,true),request);knowledge.history.feedback(id,feedback(first,false),request);
        assertThat(count("knowledge_feedback")).isEqualTo(1);assertThat((Object)store.read(c->one(c,"SELECT relevant FROM knowledge_feedback").get("relevant"))).isEqualTo(0);
        error(404,"knowledge_result_not_found",()->knowledge.history.feedback(id,feedback(first,true),otherRequest));
        error(404,"knowledge_result_not_found",()->knowledge.history.feedback(next.path("history_id").asText(),feedback(first,true),request));
        error(422,"invalid_request",()->knowledge.history.feedback(id,json.createObjectNode().put("result_id","x").put("relevant","true"),request));
        error(422,"invalid_request",()->knowledge.history.feedback(id,((ObjectNode)feedback(first,true)).put("user_id","owner"),request));
        assertThat(json.valueToTree(knowledge.history.list(otherRequest)).get("items")).isEmpty();
    }
    @ParameterizedTest @ValueSource(strings={"revision","chunk","offset","hash","status","delete","membership","private"})
    void feedbackAndCountsUseCurrentEvidenceAndAcl(String mutation){
        var response=run(body().put("workspace_id","one").put("kind","document"),false);String id=response.path("history_id").asText();
        store.write(c->{switch(mutation){
            case "revision"->execute(c,"UPDATE documents SET revision=revision+1 WHERE id=?",document);
            case "chunk"->execute(c,"DELETE FROM chunks WHERE document_id=?",document);
            case "offset"->execute(c,"UPDATE chunks SET end_offset=end_offset+1 WHERE document_id=?",document);
            case "hash"->execute(c,"UPDATE chunks SET text='changed' WHERE document_id=?",document);
            case "status"->execute(c,"UPDATE documents SET status='failed' WHERE id=?",document);
            case "delete"->execute(c,"DELETE FROM documents WHERE id=?",document);
            case "membership"->execute(c,"DELETE FROM memberships WHERE user_id='owner' AND workspace_id='one'");
            case "private"->execute(c,"UPDATE documents SET visibility='private',owner_id='other' WHERE id=?",document);
        }return null;});
        boolean hidden=Set.of("delete","membership","private").contains(mutation);
        error(hidden?404:409,hidden?"knowledge_result_not_found":"knowledge_result_stale",()->knowledge.history.feedback(id,feedback(response,true),request));
        if(mutation.equals("membership"))assertThat(list()).isEmpty();else assertThat(list().get(0).path("result_count").asInt()).isZero();
        assertThat(count("knowledge_feedback")).isZero();
    }
    @ParameterizedTest @ValueSource(strings={"revision","membership","logout","metadata","new_corpus","delete"})
    void finalTransactionRejectsMutationDuringGenerationAndRollsBack(String mutation){
        during=()->store.write(c->{switch(mutation){
            case "revision"->execute(c,"UPDATE documents SET revision=revision+1 WHERE id=?",document);
            case "membership"->execute(c,"DELETE FROM memberships WHERE user_id='owner' AND workspace_id='two'");
            case "logout"->execute(c,"DELETE FROM sessions WHERE user_id='owner'");
            case "metadata"->execute(c,"UPDATE meetings SET version=version+1 WHERE document_id=?",meeting);
            case "new_corpus"->docs.upload(c,"one","owner","new.txt","release new".getBytes(),"new","workspace");
            case "delete"->execute(c,"DELETE FROM documents WHERE id=?",document);
        }return null;});
        assertThatThrownBy(()->run(body(),true)).isInstanceOf(ApiError.class);assertThat(count("knowledge_history")).isZero();assertThat(count("knowledge_history_results")).isZero();
    }
    @Test void errorsAndBusyNeverSaveWhileIndependentWritesProceedDuringTransport()throws Exception{
        mode="error";error(503,"generation_unavailable",()->run(body(),true));assertThat(count("knowledge_history")).isZero();mode="answered";
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        during=()->{entered.countDown();try{if(!release.await(5,TimeUnit.SECONDS))throw new AssertionError("release timeout");}catch(InterruptedException e){throw new RuntimeException(e);}};
        try(var executor=Executors.newSingleThreadExecutor()){
            var future=executor.submit(()->run(body(),true));try{
                assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();error(503,"inference_busy",()->run(body(),false));
                store.write(c->{execute(c,"INSERT INTO workspaces VALUES ('independent','independent')");return null;});assertThat(count("knowledge_history")).isZero();
            }finally{release.countDown();}assertThat(future.get(3,TimeUnit.SECONDS).path("status").asText()).isEqualTo("answered");
        }
        assertThat(count("knowledge_history")).isEqualTo(1);
    }
    @Test void scopeRevocationHidesScopedHistoryButAllScopeRetainsQuestionAndCountsOnlyAccessibleEvidence(){
        run(body(),false);run(body().put("workspace_id","two"),false);run(body().put("meeting_id",meeting),false);
        store.write(c->{execute(c,"DELETE FROM memberships WHERE user_id='owner' AND workspace_id='two'");execute(c,"DELETE FROM documents WHERE id=?",meeting);return null;});
        var items=list();assertThat(items).hasSize(1);assertThat(items.get(0).path("workspace_id").isNull()).isTrue();assertThat(items.get(0).path("result_count").asInt()).isEqualTo(1);
    }
    @Test void historyReturnsNewestHundredAccessibleRecords(){
        for(int i=0;i<103;i++)run(body().put("query","absent"+i),false);
        var items=list();assertThat(items).hasSize(100);assertThat(items.get(0).path("query").asText()).isEqualTo("absent102");assertThat(items.get(99).path("query").asText()).isEqualTo("absent3");
    }
    @Test void additiveMigrationPreservesLegacySearchAndFeedbackAcrossRepeatedStarts(){
        store.write(c->{
            execute(c,"INSERT INTO searches VALUES ('legacy','one','owner','legacy query',?)",Auth.now());
            var chunk=one(c,"SELECT id FROM chunks WHERE document_id=?",document);
            execute(c,"INSERT INTO search_results VALUES ('legacy',?,?,1)",document,chunk.get("id"));
            execute(c,"INSERT INTO feedback VALUES ('legacy',?,1,?)",document,Auth.now());
            execute(c,"DROP TABLE knowledge_feedback");execute(c,"DROP TABLE knowledge_history_results");execute(c,"DROP TABLE knowledge_history");return null;
        });
        for(int i=0;i<2;i++)new Store(temp.resolve("history.sqlite3").toString());
        assertThat(count("searches")).isEqualTo(1);assertThat(count("search_results")).isEqualTo(1);assertThat(count("feedback")).isEqualTo(1);
        assertThat(count("knowledge_history")).isZero();assertThat((Object)store.read(c->one(c,"PRAGMA user_version").get("user_version"))).isEqualTo(1);
        run(body(),false);assertThat(count("knowledge_history")).isEqualTo(1);
    }
    @Test void storageErrorRollsBackHistoryAndAllResults(){
        store.write(c->{execute(c,"CREATE TRIGGER reject_history_result BEFORE INSERT ON knowledge_history_results BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END");return null;});
        assertThatThrownBy(()->run(body(),false)).isInstanceOf(IllegalStateException.class).hasMessage("database_operation_failed");
        assertThat(count("knowledge_history")).isZero();assertThat(count("knowledge_history_results")).isZero();
    }
    @Test void finalSnapshotAndInsertShareWriteLockAgainstConcurrentRevocation()throws Exception{
        var inference=new InferenceClient("","",1000,json);CountDownLatch attempting=new CountDownLatch(1);
        try(var executor=Executors.newSingleThreadExecutor()){
            List<Future<?>> mutation=new ArrayList<>();
            var service=new KnowledgeService(store,auth,docs,meetings,new LearnedSearch(store,auth,docs,inference),inference,new GenerationClient("","",1000,json),json){
                int snapshots;
                @Override Snapshot snapshot(java.sql.Connection c,jakarta.servlet.http.HttpServletRequest req,Filter f)throws Exception{
                    var value=super.snapshot(c,req,f);
                    if(++snapshots==2){
                        mutation.add(executor.submit(()->{attempting.countDown();store.write(connection->{Store.execute(connection,"DELETE FROM memberships WHERE workspace_id='one' AND user_id='owner'");return null;});}));
                        assertThat(attempting.await(2,TimeUnit.SECONDS)).isTrue();
                        assertThatThrownBy(()->mutation.getFirst().get(150,TimeUnit.MILLISECONDS)).isInstanceOf(TimeoutException.class);
                    }
                    return value;
                }
            };
            var response=service.execute(body().put("workspace_id","one"),request,false);
            assertThat(response.get("history_id")).isNotNull();mutation.getFirst().get(3,TimeUnit.SECONDS);
            assertThat(count("knowledge_history")).isEqualTo(1);assertThat(list()).isEmpty();
        }
    }
    @Test void normalizedFiltersAndDistinctResultRatingsArePreserved(){
        var query=body().put("meeting_id",meeting).put("workspace_id","one").put("kind","meeting")
                .put("date_from","2026-10-01").put("date_to","2026-10-31").put("participant","Alice").put("assignee","Alice").put("item_type","action");
        run(query,false);var filters=list().get(0).get("filters");
        for(String key:List.of("meeting_id","date_from","date_to","participant","assignee","item_type","limit"))assertThat(filters.get(key)).isEqualTo(query.get(key));
        var response=run(body(),false);String id=response.path("history_id").asText();
        for(var result:response.get("results"))knowledge.history.feedback(id,json.createObjectNode().put("result_id",result.path("result_id").asText()).put("relevant",true),request);
        assertThat(count("knowledge_feedback")).isEqualTo(3);
    }
}
