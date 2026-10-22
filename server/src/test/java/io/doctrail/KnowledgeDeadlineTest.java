package io.doctrail;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.web.MockHttpServletRequest;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.IntConsumer;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;

/** Real isolated SQLite/auth/citation checks with a controllable clock and fake transport only. */
class KnowledgeDeadlineTest {
    @TempDir Path temp;
    ObjectMapper json=new ObjectMapper();
    DocumentService docs=new DocumentService();
    Auth auth=new Auth("0");
    Store store;MeetingService meetings;MockHttpServletRequest request;
    final String user="owner",workspace="workspace",session="synthetic-session";
    final String content="Synthetic release policy with exact source evidence.";
    String documentId;
    AtomicLong clock=new AtomicLong(System.nanoTime());
    int reads;IntConsumer afterRead=ignored->{};
    Runnable duringRank=()->{},duringGeneration=()->{};
    IntConsumer duringSnapshot=ignored->{};
    Runnable duringValidation=()->{};
    long healthDeadline,rankDeadline,existingInferenceDeadline;
    List<Map<String,Object>> rankedCorpus;
    FakeGeneration generation;
    InferenceClient inference;LearnedSearch learned;

    class FakeGeneration extends GenerationClient {
        int legacyCalls,sharedCalls;AnswerDeadline receivedBudget;JsonNode payload;
        FakeGeneration(){super("","",120000,json);}
        @Override JsonNode call(String path,Object body){legacyCalls++;return result(body);}
        @Override JsonNode call(String path,Object body,AnswerDeadline budget){
            sharedCalls++;receivedBudget=budget;return result(body);
        }
        JsonNode result(Object body){
            payload=json.valueToTree(body);duringGeneration.run();
            JsonNode source=payload.path("contexts").get(0);
            ObjectNode out=json.createObjectNode().put("schema_version",1).put("model","synthetic").put("revision","fixture").put("status","answered").putNull("reason");
            out.putArray("claims").addObject().put("text","Synthetic cited response").putArray("citations").addObject()
                    .put("chunk_id",source.path("chunk_id").asText()).put("quote",source.path("text").asText())
                    .put("start_offset",source.path("start_offset").asInt()).put("end_offset",source.path("end_offset").asInt());
            return out;
        }
        int calls(){return legacyCalls+sharedCalls;}
    }
    class TestKnowledge extends KnowledgeService {
        int deadlines,snapshots,validations;
        TestKnowledge(boolean enabled){super(KnowledgeDeadlineTest.this.store,KnowledgeDeadlineTest.this.auth,KnowledgeDeadlineTest.this.docs,KnowledgeDeadlineTest.this.meetings,KnowledgeDeadlineTest.this.learned,KnowledgeDeadlineTest.this.inference,KnowledgeDeadlineTest.this.generation,KnowledgeDeadlineTest.this.json,enabled);}
        @Override AnswerDeadline answerDeadline(long started){deadlines++;return new AnswerDeadline(clock.get(),clock::get);}
        @Override Snapshot snapshot(Connection connection,HttpServletRequest req,Filter filter)throws Exception{
            Snapshot result=super.snapshot(connection,req,filter);duringSnapshot.accept(++snapshots);return result;
        }
        @Override Map<String,Object> validateAnswer(JsonNode value,List<Map<String,Object>> contexts){
            validations++;Map<String,Object> result=super.validateAnswer(value,contexts);duringValidation.run();return result;
        }
    }
    @BeforeEach void setup(){
        store=new Store(temp.resolve("deadline.sqlite3").toString()){
            @Override <T>T read(Work<T> work){T result=super.read(work);afterRead.accept(++reads);return result;}
        };
        store.write(c->{
            for(String id:List.of(user,"other"))execute(c,"INSERT INTO users VALUES (?,?,?,?)",id,id+"@example.test",id,"unused");
            execute(c,"INSERT INTO workspaces VALUES (?,?)",workspace,"Synthetic deadline workspace");
            execute(c,"INSERT INTO memberships VALUES (?,?,'owner')",workspace,user);
            execute(c,"INSERT INTO sessions VALUES (?,?,?)",Auth.hash(session),user,System.currentTimeMillis()/1000.0+120);
            return null;
        });
        request=new MockHttpServletRequest();request.setCookies(new Cookie(Auth.COOKIE,session));
        generation=new FakeGeneration();meetings=new MeetingService(store,auth,docs,json,generation);
        documentId=store.write(c->docs.upload(c,workspace,user,"fixture.txt",content.getBytes(java.nio.charset.StandardCharsets.UTF_8),"Synthetic policy","workspace")).get("id").toString();
        existingInferenceDeadline=clock.get()+TimeUnit.SECONDS.toNanos(120);
        inference=new InferenceClient("","",120000,json){
            @Override long deadline(){return existingInferenceDeadline;}
            @Override void health(long deadline){healthDeadline=deadline;}
        };
        learned=new LearnedSearch(store,auth,docs,inference){
            @Override List<Map<String,Object>> rank(String query,List<Map<String,Object>> rows,int limit,String method,long deadline){
                rankDeadline=deadline;rankedCorpus=rows;duringRank.run();
                return rows.stream().limit(limit).map(row->new LinkedHashMap<String,Object>(row)).map(row->(Map<String,Object>)row).toList();
            }
        };
        reads=0;
    }
    @AfterEach void close(){meetings.close();}
    ObjectNode body(String method){return json.createObjectNode().put("query","release").put("method",method).put("limit",5);}
    void expire(){clock.addAndGet(TimeUnit.SECONDS.toNanos(90));}
    void timeout(Runnable work){assertThatThrownBy(work::run).isInstanceOfSatisfying(ApiError.class,e->{assertThat(e.status).isEqualTo(504);assertThat(e).hasMessage("generation_timeout");});}

    @Test void retrievalUsesOneSharedDeadlineAndOnlyRemainingBudgetReachesGeneration(){
        var service=new TestKnowledge(true);long start=clock.get();
        duringRank=()->clock.addAndGet(TimeUnit.SECONDS.toNanos(17));
        var result=service.execute(body("hybrid_rerank"),request,true);
        assertThat(healthDeadline).isEqualTo(start+TimeUnit.SECONDS.toNanos(90));
        assertThat(rankDeadline).isEqualTo(healthDeadline);
        assertThat(generation.receivedBudget.remainingNanos()).isEqualTo(TimeUnit.SECONDS.toNanos(73));
        assertThat(service.deadlines).isEqualTo(1);assertThat(service.snapshots).isEqualTo(3);
        assertThat(generation.sharedCalls).isEqualTo(1);assertThat(generation.legacyCalls).isZero();
        assertThat(json.valueToTree(result).at("/claims/0/citations/0/document_id").asText()).isEqualTo(documentId);
        assertThat(json.valueToTree(result).at("/claims/0/citations/0/quote").asText()).isEqualTo(content);
    }
    @Test void shorterExistingRetrievalTimeoutIsNotExtended(){
        existingInferenceDeadline=clock.get()+TimeUnit.SECONDS.toNanos(2);
        new TestKnowledge(true).execute(body("dense"),request,true);
        assertThat(healthDeadline).isEqualTo(existingInferenceDeadline);
        assertThat(rankDeadline).isEqualTo(existingInferenceDeadline);
    }
    @Test void delayedRetrievalExpiresBeforeAnyGenerationAndReleasesAdmission(){
        var service=new TestKnowledge(true);duringRank=this::expire;
        timeout(()->service.execute(body("dense"),request,true));
        assertThat(generation.calls()).isZero();assertThat(service.snapshots).isEqualTo(1);
        duringRank=()->{};service.execute(body("dense"),request,true);
        assertThat(generation.sharedCalls).isEqualTo(1);
    }
    @ParameterizedTest @ValueSource(ints={1,2})
    void initialAndPreSendSnapshotsAreInsideBudget(int snapshot){
        var service=new TestKnowledge(true);duringSnapshot=count->{if(count==snapshot)expire();};
        timeout(()->service.execute(body("dense"),request,true));
        assertThat(generation.calls()).isZero();
    }
    @Test void lateWorkerOutputIsRejectedBeforeCitationValidation(){
        var service=new TestKnowledge(true);duringGeneration=this::expire;
        timeout(()->service.execute(body("bm25"),request,true));
        assertThat(generation.sharedCalls).isEqualTo(1);assertThat(service.validations).isZero();
    }
    @Test void citationValidationIsInsideBudget(){
        var service=new TestKnowledge(true);duringValidation=this::expire;
        timeout(()->service.execute(body("bm25"),request,true));
        assertThat(service.validations).isEqualTo(1);
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void finalAuthorizationAndItsTransactionCompletionAreInsideBudget(boolean afterCommit){
        var service=new TestKnowledge(true);
        if(afterCommit)afterRead=count->{if(count==3)expire();};
        else duringSnapshot=count->{if(count==3)expire();};
        timeout(()->service.execute(body("bm25"),request,true));
        assertThat(service.snapshots).isEqualTo(3);assertThat(generation.sharedCalls).isEqualTo(1);
    }
    @Test void emptyEvidenceStillChecksFinalBudgetWithoutCallingGeneration(){
        var service=new TestKnowledge(true);duringSnapshot=count->{if(count==2)expire();};
        timeout(()->service.execute(body("bm25").put("query","absentkeyword"),request,true));
        assertThat(generation.calls()).isZero();assertThat(service.snapshots).isEqualTo(2);
    }
    @ParameterizedTest @ValueSource(strings={"logout","membership","revision","delete"})
    void authorizationAndRevisionAreRecheckedBeforeAndAfterGeneration(String change){
        Runnable mutate=()->store.write(c->{
            switch(change){
                case "logout"->execute(c,"DELETE FROM sessions");
                case "membership"->execute(c,"DELETE FROM memberships WHERE user_id=?",user);
                case "revision"->docs.edit(c,documentId,user,"Edited policy",content+" changed","workspace");
                case "delete"->execute(c,"DELETE FROM documents WHERE id=?",documentId);
            }
            return null;
        });
        duringRank=mutate;
        assertThatThrownBy(()->new TestKnowledge(true).execute(body("dense"),request,true)).isInstanceOf(ApiError.class);
        assertThat(generation.calls()).isZero();
    }
    @ParameterizedTest @ValueSource(strings={"logout","membership","revision","delete"})
    void finalAuthorizationRejectsChangedContextEvenWithTimeRemaining(String change){
        duringGeneration=()->store.write(c->{
            switch(change){
                case "logout"->execute(c,"DELETE FROM sessions");
                case "membership"->execute(c,"DELETE FROM memberships WHERE user_id=?",user);
                case "revision"->docs.edit(c,documentId,user,"Edited policy",content+" changed","workspace");
                case "delete"->execute(c,"DELETE FROM documents WHERE id=?",documentId);
            }
            return null;
        });
        assertThatThrownBy(()->new TestKnowledge(true).execute(body("bm25"),request,true)).isInstanceOf(ApiError.class);
        assertThat(generation.sharedCalls).isEqualTo(1);
    }
    @Test void privateAndNonMemberDocumentsNeverReachRankingOrGeneration(){
        store.write(c->{
            execute(c,"INSERT INTO memberships VALUES (?,?,'member')",workspace,"other");
            docs.upload(c,workspace,"other","private.txt","PRIVATE synthetic release".getBytes(),"private","private");
            execute(c,"INSERT INTO workspaces VALUES ('unrelated','unrelated')");
            execute(c,"INSERT INTO memberships VALUES ('unrelated','other','owner')");
            docs.upload(c,"unrelated","other","unrelated.txt","UNRELATED synthetic release".getBytes(),"unrelated","workspace");
            return null;
        });
        new TestKnowledge(true).execute(body("hybrid_rerank"),request,true);
        assertThat(rankedCorpus).hasSize(1);assertThat(rankedCorpus.getFirst().get("document_id")).isEqualTo(documentId);
        assertThat(generation.payload.path("contexts").size()).isEqualTo(1);
        assertThat(generation.payload.toString()).doesNotContain("PRIVATE","UNRELATED");
    }
    @Test void incomingHeaderCannotIncreaseBudgetAndBodyBudgetFieldsAreRejected(){
        request.addHeader("X-DocTrail-Request-Budget-Ms","900000000");
        var service=new TestKnowledge(true);service.execute(body("bm25"),request,true);
        assertThat(generation.receivedBudget.remainingNanos()).isEqualTo(TimeUnit.SECONDS.toNanos(90));
        assertThat(generation.payload.has("request_budget_ms")).isFalse();
        assertThatThrownBy(()->service.execute(body("bm25").put("request_budget_ms",900000000),request,true)).hasMessage("invalid_request");
        assertThat(generation.calls()).isEqualTo(1);
    }
    @Test void defaultConstructorAndOrdinarySearchRetainExistingPath(){
        var legacy=new KnowledgeService(store,auth,docs,meetings,learned,inference,generation,json);
        legacy.execute(body("bm25"),request,true);
        assertThat(generation.legacyCalls).isEqualTo(1);assertThat(generation.sharedCalls).isZero();
        var service=new TestKnowledge(true);duringRank=this::expire;
        assertThat(service.execute(body("dense"),request,false).get("results")).isInstanceOf(List.class);
        assertThat(service.deadlines).isZero();assertThat(healthDeadline).isEqualTo(existingInferenceDeadline);
        assertThat(generation.calls()).isEqualTo(1);
    }

    @ParameterizedTest @ValueSource(strings={"no_evidence","insufficient_evidence","conflicting_evidence","unsupported_question","unknown_worker_reason"})
    void workerAbstentionReasonIsPreservedOrRejectedWithoutRetry(String reason){
        generation=new FakeGeneration(){
            @Override JsonNode result(Object body){
                var output=json.createObjectNode().put("schema_version",1).put("model","synthetic").put("revision","fixture")
                        .put("status","abstained").put("reason",reason);
                output.putArray("claims");return output;
            }
        };
        var service=new TestKnowledge(true);
        if(reason.equals("unknown_worker_reason")){
            assertThatThrownBy(()->service.execute(body("bm25"),request,true)).isInstanceOfSatisfying(ApiError.class,error->{
                assertThat(error.status).isEqualTo(503);assertThat(error).hasMessage("generation_invalid_response");
            });
        }else{
            var result=service.execute(body("bm25"),request,true);
            assertThat(result).containsEntry("status","abstained").containsEntry("reason",reason);
            assertThat((List<?>)result.get("claims")).isEmpty();
        }
        assertThat(generation.calls()).isEqualTo(1);
    }
}
