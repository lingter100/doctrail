package io.doctrail;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.web.MockHttpServletRequest;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;

/** Invented fixtures and fake generation outputs test service boundaries, never model quality. */
class MeetingServiceTest {
    @TempDir Path temp;Store store;Auth auth;DocumentService docs=new DocumentService();ObjectMapper json=new ObjectMapper();MeetingService meetings;KnowledgeService knowledge;MockHttpServletRequest request;FakeGeneration generation;
    String user="owner",workspace="workspace",session="synthetic-session";String content="😀 회의 2026-10-13. Alice confirms the release. Alice will test on 2026-10-14.";
    class FakeGeneration extends GenerationClient {
        AtomicInteger calls=new AtomicInteger();volatile Runnable during=()->{};volatile String mode="ready";
        FakeGeneration(){super("","",1000,json);}
        @Override JsonNode call(String path,Object payload){calls.incrementAndGet();during.run();if(mode.equals("unavailable"))throw new ApiError(503,"generation_unavailable");JsonNode input=json.valueToTree(payload);ObjectNode out=json.createObjectNode().put("schema_version",1).put("model","synthetic-fake").put("revision","fixture");
            if(path.equals("/analyze")){ObjectNode a=sample(input.path("content").asText());if(mode.equals("bad_quote"))((ObjectNode)a.withArray("items").get(0)).put("quote","invented");out.set("analysis",a);}
            else{JsonNode c=input.withArray("contexts").get(0);out.put("status","answered").putNull("reason");ObjectNode claim=out.putArray("claims").addObject().put("text","Synthetic boundary check");ObjectNode citation=claim.putArray("citations").addObject().put("chunk_id",c.get("chunk_id").asText()).put("quote",c.get("text").asText()).put("start_offset",c.get("start_offset").intValue()).put("end_offset",c.get("end_offset").intValue());if(mode.equals("bad_quote"))citation.put("quote","invented");}
            return out;
        }
    }
    @BeforeEach void setup(){store=new Store(temp.resolve("test.sqlite3").toString());auth=new Auth("0");store.write(c->{for(String id:List.of(user,"other"))execute(c,"INSERT INTO users VALUES (?,?,?,?)",id,id+"@example.test",id,"unused");execute(c,"INSERT INTO workspaces VALUES (?,?)",workspace,"workspace");execute(c,"INSERT INTO memberships VALUES (?,?,'owner')",workspace,user);execute(c,"INSERT INTO sessions VALUES (?,?,?)",Auth.hash(session),user,System.currentTimeMillis()/1000.0+60);return null;});request=new MockHttpServletRequest();request.setCookies(new Cookie(Auth.COOKIE,session));generation=new FakeGeneration();meetings=new MeetingService(store,auth,docs,json,generation);var inference=new InferenceClient("","",1000,json);knowledge=new KnowledgeService(store,auth,docs,meetings,new LearnedSearch(store,auth,docs,inference),inference,generation,json);}
    @AfterEach void close(){meetings.close();}
    ObjectNode sample(String source){ObjectNode a=MeetingAnalysis.empty(json);a.put("summary",source);a.withArray("summary_evidence").addObject().put("quote",source).put("start_offset",0).put("end_offset",DocumentService.length(source));for(String type:List.of("decision","action")){var i=a.withArray("items").addObject().put("id","").put("type",type).put("text",source).put("quote",source).put("start_offset",0).put("end_offset",DocumentService.length(source)).putNull("assignee").putNull("due_date").putNull("priority").put("status",type.equals("action")?"todo":"needs_confirmation");}return a;}
    @SuppressWarnings("unchecked") String create(String visibility){return (String)((Map<String,Object>)store.write(c->meetings.upload(c,workspace,user,"meeting.txt",content.getBytes(java.nio.charset.StandardCharsets.UTF_8),"meeting",visibility)).get("document")).get("id");}
    Map<String,Object> state(String id){return store.read(c->meetings.state(c,id));}
    void analyze(String id)throws Exception{meetings.analyze(id,json.valueToTree(Map.of("expected_revision",1)),request);await(id);}
    void await(String id)throws Exception{long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(4);while(Set.of("queued","running").contains(state(id).get("analysis_status"))&&System.nanoTime()<end)Thread.sleep(10);assertThat(state(id).get("analysis_status")).isNotIn("queued","running");}
    ObjectNode editBody(String id)throws Exception{var m=state(id);return json.createObjectNode().put("expected_revision",((Number)m.get("source_revision")).intValue()).put("expected_version",((Number)m.get("version")).intValue()).set("analysis",meetings.analysis(m));}
    @Test void migrationIsIdempotentAndAnalysisHasSeparateImmutableRunAndEditedSnapshot()throws Exception{
        String id=create("workspace");analyze(id);assertThat(state(id).get("analysis_status")).isEqualTo("ready");ObjectNode b=editBody(id);((ObjectNode)b.at("/analysis/items/0")).put("status","confirmed");((ObjectNode)b.at("/analysis/items/1")).put("status","done");store.write(c->meetings.update(c,id,user,b));assertThat(state(id).get("provenance")).isEqualTo("user_edited");assertThat((List<Map<String,Object>>)store.read(c->meetings.tasks(c,user,null,null,"done"))).hasSize(1);assertThatThrownBy(()->store.write(c->meetings.update(c,id,user,b))).isInstanceOf(ApiError.class).hasMessage("meeting_context_changed");analyze(id);assertThat(meetings.analysis(state(id)).at("/items/1/status").asText()).isEqualTo("done");assertThat((List<Map<String,Object>>)store.read(c->rows(c,"SELECT * FROM meeting_runs WHERE document_id=?",id))).hasSize(2);assertThat((List<Map<String,Object>>)new Store(temp.resolve("test.sqlite3").toString()).read(c->rows(c,"SELECT * FROM meeting_edits"))).hasSize(1);
    }
    @Test void failedQuoteNeverPublishesAndManualRetryGetsNewRun()throws Exception{String id=create("workspace");generation.mode="bad_quote";analyze(id);assertThat(state(id).get("analysis_status")).isEqualTo("failed");assertThat(state(id).get("ai_analysis")).isNull();generation.mode="ready";analyze(id);assertThat(state(id).get("analysis_status")).isEqualTo("ready");assertThat((List<Map<String,Object>>)store.read(c->rows(c,"SELECT * FROM meeting_runs WHERE document_id=?",id))).hasSize(2);}
    @ParameterizedTest @ValueSource(strings={"edit","delete","logout","membership","visibility"}) void inFlightAnalysisInvalidationNeverPublishes(String mutation)throws Exception{
        String id=create("workspace");generation.during=()->store.write(c->{switch(mutation){case "edit"->docs.edit(c,id,user,"edited",content+" changed","workspace");case "delete"->execute(c,"DELETE FROM documents WHERE id=?",id);case "logout"->execute(c,"DELETE FROM sessions");case "membership"->execute(c,"DELETE FROM memberships WHERE user_id=?",user);case "visibility"->execute(c,"UPDATE documents SET visibility='private' WHERE id=?",id);}return null;});meetings.analyze(id,json.valueToTree(Map.of("expected_revision",1)),request);if(mutation.equals("delete")){long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(4);while(store.read(c->one(c,"SELECT id FROM documents WHERE id=?",id))!=null&&System.nanoTime()<end)Thread.sleep(10);assertThat((List<Map<String,Object>>)store.read(c->rows(c,"SELECT * FROM meeting_runs WHERE document_id=?",id))).isEmpty();}else{await(id);assertThat(state(id).get("analysis_status")).isIn("failed","stale");assertThat(state(id).get("ai_analysis")).isNull();}
    }
    @Test void duplicateAnalysisBlockedAndRestartInterruptsPersistedJobs()throws Exception{String id=create("workspace");CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);generation.during=()->{entered.countDown();try{release.await(3,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}};meetings.analyze(id,json.valueToTree(Map.of("expected_revision",1)),request);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();assertThatThrownBy(()->meetings.analyze(id,json.valueToTree(Map.of("expected_revision",1)),request)).hasMessage("analysis_running");release.countDown();await(id);store.write(c->{execute(c,"UPDATE meetings SET analysis_status='running' WHERE document_id=?",id);return null;});MeetingService restarted=new MeetingService(store,auth,docs,json,generation);try{assertThat(state(id).get("analysis_error")).isEqualTo("generation_interrupted");}finally{restarted.close();}}
    @Test void crossWorkspaceAndPrivateAclAreAppliedBeforeWorkerAndMetadataBeforeRanking()throws Exception{
        String id=create("workspace");analyze(id);store.write(c->{execute(c,"INSERT INTO workspaces VALUES ('other-workspace','other')");execute(c,"INSERT INTO memberships VALUES ('other-workspace',?,'owner')",user);docs.upload(c,"other-workspace",user,"extra.txt","Alice extra authorized document".getBytes(),"extra","workspace");execute(c,"INSERT INTO memberships VALUES (?,? ,'member')",workspace,"other");docs.upload(c,workspace,"other","secret.txt","Alice private secret".getBytes(),"secret","private");return null;});
        var hits=json.valueToTree(knowledge.execute(json.valueToTree(Map.of("query","Alice")),request,false)).get("results");assertThat(hits.size()).isEqualTo(2);assertThat(hits.toString()).doesNotContain("private secret");var answer=json.valueToTree(knowledge.execute(json.valueToTree(Map.of("query","Alice","kind","document")),request,true));assertThat(answer.at("/claims/0/citations/0/title").asText()).isEqualTo("extra");
    }
    @Test void knowledgeSearchScopesKindsAndEmptyAnswerMakesNoModelCall()throws Exception{String id=create("workspace");store.write(c->{docs.upload(c,workspace,user,"doc.txt","ordinary policy document".getBytes(),"ordinary","workspace");return null;});var search=knowledge.execute(json.valueToTree(Map.of("query","policy","kind","document")),request,false);assertThat((List<?>)search.get("results")).hasSize(1);int calls=generation.calls.get();var answer=knowledge.execute(json.valueToTree(Map.of("query","notpresent","kind","all")),request,true);assertThat(answer.get("status")).isEqualTo("abstained");assertThat(generation.calls.get()).isEqualTo(calls);assertThat((List<?>)knowledge.execute(json.valueToTree(Map.of("query","Alice","date_from","2026-10-01")),request,false).get("results")).isEmpty();}
    @ParameterizedTest @ValueSource(strings={"edit","delete","logout","membership","metadata"}) void inFlightAnswerNeverReturnsChangedContext(String mutation)throws Exception{
        String id=create("workspace");analyze(id);generation.during=()->store.write(c->{switch(mutation){case "edit"->docs.edit(c,id,user,"edited",content+" edit","workspace");case "delete"->execute(c,"DELETE FROM documents WHERE id=?",id);case "logout"->execute(c,"DELETE FROM sessions");case "membership"->execute(c,"DELETE FROM memberships WHERE user_id=?",user);case "metadata"->execute(c,"UPDATE meetings SET version=version+1 WHERE document_id=?",id);}return null;});assertThatThrownBy(()->knowledge.execute(json.valueToTree(Map.of("query","Alice")),request,true)).isInstanceOf(ApiError.class);
    }
    @Test void codePointCitationsRebuildIdentityAndRejectFabricatedQuotes()throws Exception{String id=create("workspace");var response=knowledge.execute(json.valueToTree(Map.of("query","Alice")),request,true);var tree=json.valueToTree(response);assertThat(tree.at("/claims/0/citations/0/document_id").asText()).isEqualTo(id);assertThat(tree.at("/claims/0/citations/0/end_offset").asInt()).isEqualTo(DocumentService.length(content));assertThat(tree.at("/claims/0/citations/0/quote").asText()).isEqualTo(content);generation.mode="bad_quote";assertThatThrownBy(()->knowledge.execute(json.valueToTree(Map.of("query","Alice")),request,true)).hasMessage("generation_invalid_response");}
    @Test void decisionLinksNeedConfirmedItemsBothAclsAndCurrentRevisions()throws Exception{
        String first=create("workspace"),second=create("private");analyze(first);analyze(second);ObjectNode firstEdit=editBody(first),secondEdit=editBody(second);((ObjectNode)firstEdit.at("/analysis/items/0")).put("status","confirmed");((ObjectNode)secondEdit.at("/analysis/items/0")).put("status","confirmed");store.write(c->meetings.update(c,first,user,firstEdit));store.write(c->meetings.update(c,second,user,secondEdit));ObjectNode link=json.createObjectNode().put("target_meeting_id",second).put("source_item_id",firstEdit.at("/analysis/items/0/id").asText()).put("target_item_id",secondEdit.at("/analysis/items/0/id").asText()).put("relation","supersedes").put("expected_revision",1).put("expected_version",2).put("target_expected_revision",1).put("target_expected_version",2).put("quote",content).put("start_offset",0).put("end_offset",DocumentService.length(content));store.write(c->meetings.link(c,first,user,link));assertThat((List<Map<String,Object>>)store.read(c->meetings.links(c,first,user))).hasSize(1);var taskEdit=editBody(first);((ObjectNode)taskEdit.at("/analysis/items/1")).put("status","done").put("assignee","New human assignment");store.write(c->meetings.update(c,first,user,taskEdit));assertThat((List<Map<String,Object>>)store.read(c->meetings.links(c,first,user))).hasSize(1);store.write(c->{execute(c,"INSERT INTO memberships VALUES (?,?,'member')",workspace,"other");return null;});assertThat((List<Map<String,Object>>)store.read(c->meetings.links(c,first,"other"))).isEmpty();store.write(c->docs.edit(c,second,user,"edited",content+" new","private"));assertThat((List<Map<String,Object>>)store.read(c->meetings.links(c,first,user))).isEmpty();assertThat((List<Map<String,Object>>)store.read(c->meetings.tasks(c,user,null,null,null))).hasSize(1);
    }
    @Test void queueIsBoundedAndRejectedJobIsPersistedAsFailure()throws Exception{
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);generation.during=()->{entered.countDown();try{release.await(4,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}};List<String> ids=new ArrayList<>();for(int i=0;i<10;i++)ids.add(create("workspace"));meetings.analyze(ids.getFirst(),json.valueToTree(Map.of("expected_revision",1)),request);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();for(int i=1;i<9;i++)meetings.analyze(ids.get(i),json.valueToTree(Map.of("expected_revision",1)),request);assertThatThrownBy(()->meetings.analyze(ids.get(9),json.valueToTree(Map.of("expected_revision",1)),request)).hasMessage("generation_queue_full");assertThat(state(ids.get(9)).get("analysis_error")).isEqualTo("generation_queue_full");release.countDown();for(int i=0;i<9;i++)await(ids.get(i));
    }    @Test void inventedAiMetadataRejectedButUserAuthoredFieldsAreMarkedSeparately(){
        var a=sample(content);int index=0;for(var item:a.withArray("items"))((ObjectNode)item).put("id","stable-"+(index++));a.put("meeting_date","2027-01-01");a.withArray("metadata_evidence").addObject().put("field","meeting_date").put("quote",content).put("start_offset",0).put("end_offset",DocumentService.length(content));assertThatThrownBy(()->MeetingAnalysis.validate(a,content,true)).hasMessage("invalid_analysis");assertThat(MeetingAnalysis.validate(a,content,false)).isNotNull();a.putNull("meeting_date");a.withArray("participants").add("Invented person");a.withArray("metadata_evidence").addObject().put("field","participants").put("quote",content).put("start_offset",0).put("end_offset",DocumentService.length(content));assertThatThrownBy(()->MeetingAnalysis.validate(a,content,true)).hasMessage("invalid_analysis");
    }    @Test void learnedKnowledgeFiltersMetadataAndAclBeforeEmbedding()throws Exception{
        String id=create("workspace");analyze(id);var edit=editBody(id);((ObjectNode)edit.get("analysis")).put("meeting_date","2026-10-13");store.write(c->meetings.update(c,id,user,edit));store.write(c->{execute(c,"INSERT INTO memberships VALUES (?,?,'member')",workspace,"other");meetings.upload(c,workspace,"other","secret.txt","Alice private classified".getBytes(),"secret","private");docs.upload(c,workspace,user,"ordinary.txt","Alice ordinary unrelated".getBytes(),"ordinary","workspace");return null;});List<String> embedded=new ArrayList<>();var inference=new InferenceClient("","",1000,json){@Override void health(long deadline){}@Override Map<String,double[]> embed(String kind,List<Map<String,String>> items,long deadline){Map<String,double[]> vectors=new HashMap<>();for(var item:items){if(kind.equals("passage"))embedded.add(item.get("text"));double[] v=new double[384];v[0]=1;vectors.put(item.get("id"),v);}return vectors;}};var service=new KnowledgeService(store,auth,docs,meetings,new LearnedSearch(store,auth,docs,inference),inference,generation,json);var results=json.valueToTree(service.execute(json.valueToTree(Map.of("query","Alice","method","dense","date_from","2026-10-01","item_type","action")),request,false));assertThat(results.at("/results/0/document_id").asText()).isEqualTo(id);assertThat(results.get("results").size()).isEqualTo(1);assertThat(embedded).containsExactly(content);
    }

    @ParameterizedTest
    @ValueSource(strings={"membership","logout","edit","metadata"})
    void retrievalChangesContextBeforeGeneration(String mutation) throws Exception {
        String id=create("workspace");
        analyze(id);
        int originalCalls=generation.calls.get();
        var inference=new InferenceClient("","",1000,json) {
            @Override void health(long deadline) {}
            @Override Map<String,double[]> embed(String kind,List<Map<String,String>> items,long deadline) {
                if(kind.equals("passage"))store.write(c->{
                    switch(mutation) {
                        case "membership" -> execute(c,"DELETE FROM memberships WHERE user_id=?",user);
                        case "logout" -> execute(c,"DELETE FROM sessions");
                        case "edit" -> docs.edit(c,id,user,"edited",content+" changed","workspace");
                        case "metadata" -> execute(c,"UPDATE meetings SET version=version+1 WHERE document_id=?",id);
                    }
                    return null;
                });
                Map<String,double[]> vectors=new HashMap<>();
                for(var item:items){double[] vector=new double[384];vector[0]=1;vectors.put(item.get("id"),vector);}
                return vectors;
            }
        };
        var service=new KnowledgeService(store,auth,docs,meetings,
                new LearnedSearch(store,auth,docs,inference),inference,generation,json);
        assertThatThrownBy(()->service.execute(json.valueToTree(
                Map.of("query","Alice","method","dense")),request,true)).isInstanceOf(ApiError.class);
        assertThat(generation.calls.get()).isEqualTo(originalCalls);
    }

    @Test
    void failedReanalysisKeepsCurrentUserTasksEditable() throws Exception {
        String id=create("workspace");
        analyze(id);
        ObjectNode edit=editBody(id);
        ((ObjectNode)edit.at("/analysis/items/1")).put("status","doing").put("assignee","New owner");
        store.write(c->meetings.update(c,id,user,edit));
        generation.mode="unavailable";
        analyze(id);
        assertThat(state(id).get("analysis_status")).isEqualTo("ready");
        assertThat(state(id).get("analysis_error")).isEqualTo("generation_unavailable");
        assertThat(state(id).get("provenance")).isEqualTo("user_edited");
        assertThat((List<Map<String,Object>>)store.read(c->meetings.tasks(c,user,null,"New owner","doing"))).hasSize(1);
        var secondEdit=editBody(id);
        ((ObjectNode)secondEdit.at("/analysis/items/1")).put("status","done");
        store.write(c->meetings.update(c,id,user,secondEdit));
        assertThat((List<Map<String,Object>>)store.read(c->meetings.tasks(c,user,null,"New owner","done"))).hasSize(1);
        assertThat(store.read(c->one(c,"SELECT status FROM meeting_runs WHERE document_id=? ORDER BY created_at DESC,id DESC LIMIT 1",id)).get("status")).isEqualTo("failed");
    }

    @Test void restartDuringRetryKeepsCurrentUserAnalysis() throws Exception {
        String id=create("workspace");analyze(id);
        var edit=editBody(id);((ObjectNode)edit.at("/analysis/items/1")).put("status","done");
        store.write(c->meetings.update(c,id,user,edit));
        store.write(c->{execute(c,"UPDATE meetings SET analysis_status='running' WHERE document_id=?",id);return null;});
        MeetingService restarted=new MeetingService(store,auth,docs,json,generation);
        try {
            assertThat(state(id).get("analysis_status")).isEqualTo("ready");
            assertThat(state(id).get("analysis_error")).isEqualTo("generation_interrupted");
            assertThat((List<Map<String,Object>>)store.read(c->meetings.tasks(c,user,null,null,"done"))).hasSize(1);
        } finally {restarted.close();}
    }

    @Test void answerContextLimitRejectedBeforeModelCall() {
        create("workspace");int calls=generation.calls.get();
        assertThatThrownBy(()->knowledge.execute(json.valueToTree(
            Map.of("query","Alice","limit",11)),request,true)).hasMessage("answer_context_limit");
        assertThat(generation.calls.get()).isEqualTo(calls);
        assertThat((List<?>)knowledge.execute(json.valueToTree(
            Map.of("query","Alice","limit",50)),request,false).get("results")).hasSize(1);
    }
}
