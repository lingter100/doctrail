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
class MeetingManualCorrectionTest {
    @TempDir Path temp;Store store;Auth auth;DocumentService docs=new DocumentService();ObjectMapper json=new ObjectMapper();MeetingService meetings;KnowledgeService knowledge;MockHttpServletRequest request;FakeGeneration generation;
    String user="owner",workspace="workspace",session="synthetic-session";String content="😀 회의 2026-10-13. Alice confirms the release. Alice will test on 2026-10-14.";
    class FakeGeneration extends GenerationClient {
        AtomicInteger calls=new AtomicInteger();volatile Runnable during=()->{};volatile String mode="ready";
        FakeGeneration(){super("","",1000,json);}
        @Override JsonNode call(String path,Object payload){calls.incrementAndGet();during.run();if(mode.equals("unavailable"))throw new ApiError(503,"generation_unavailable");JsonNode input=json.valueToTree(payload);ObjectNode out=json.createObjectNode().put("schema_version",1).put("model","synthetic-fake").put("revision","fixture");
            if(path.equals("/analyze")){ObjectNode a=sample(input.path("content").asText());if(mode.equals("bad_quote"))((ObjectNode)a.withArray("items").get(0)).put("quote","invented");if(mode.equals("grounded")){ObjectNode wrapper=json.createObjectNode().set("analysis",a);contract(wrapper,2);out.putObject("summary_review").put("policy","grounded-review-v1").put("status","accepted");}out.set("analysis",a);}
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

    void contract(ObjectNode body, int version) {
        if(version==2){ObjectNode a=(ObjectNode)body.get("analysis");ObjectNode citation=json.createObjectNode().put("quote",content).put("start_offset",0).put("end_offset",DocumentService.length(content));a.put("summary_version",2).put("summary","사람이 확인한 요약");a.putArray("summary_claims").addObject().put("id",0).put("text","사람이 확인한 요약").putArray("citations").add(citation);a.putArray("summary_evidence").add(citation);}
    }
    @ParameterizedTest @ValueSource(ints={1,2}) void manualAddReplaceDeleteKeepsSourceAndAiAndUpdatesTasks(int version)throws Exception {
        String id=create("workspace");if(version==2)generation.mode="grounded";analyze(id);var original=state(id).get("ai_analysis");var body=editBody(id);contract(body,version);ObjectNode a=(ObjectNode)body.get("analysis");ObjectNode item=((ObjectNode)a.withArray("items").get(1)).deepCopy();item.put("id","manual-stable-uuid").put("text","Human missing task").put("status","doing").put("assignee","Human assignment").put("due_date","2026-12-31").put("priority","high");a.withArray("items").add(item);store.write(c->meetings.update(c,id,user,body));
        assertThat((List<?>)store.read(c->meetings.tasks(c,user,workspace,"Human assignment","doing"))).hasSize(1);assertThat(state(id).get("ai_analysis")).isEqualTo(original);assertThat(store.read(c->one(c,"SELECT content FROM documents WHERE id=?",id)).get("content")).isEqualTo(content);
        var edit=editBody(id);ObjectNode changed=(ObjectNode)edit.at("/analysis/items/2");String quote="Alice confirms the release.";int start=DocumentService.length(content.substring(0,content.indexOf(quote)));changed.put("quote",quote).put("start_offset",start).put("end_offset",start+DocumentService.length(quote));store.write(c->meetings.update(c,id,user,edit));assertThat(meetings.analysis(state(id)).at("/items/2/id").asText()).isEqualTo("manual-stable-uuid");
        var deleted=editBody(id);((ObjectNode)deleted.get("analysis")).putArray("items");store.write(c->meetings.update(c,id,user,deleted));assertThat((List<?>)store.read(c->meetings.tasks(c,user,workspace,null,null))).isEmpty();assertThat(meetings.analysis(state(id)).path("items")).isEmpty();assertThat((List<?>)store.read(c->rows(c,"SELECT * FROM meeting_edits WHERE document_id=?",id))).hasSize(3);assertThatThrownBy(()->store.write(c->meetings.update(c,id,user,deleted))).hasMessage("meeting_context_changed");
    }
    @ParameterizedTest @ValueSource(ints={0,150,151}) void itemCountBoundaries(int count)throws Exception {
        String id=create("workspace");analyze(id);var body=editBody(id);ObjectNode template=((ObjectNode)body.at("/analysis/items/0")).deepCopy();ArrayNode items=((ObjectNode)body.get("analysis")).putArray("items");for(int i=0;i<count;i++)items.add(template.deepCopy().put("id","manual-"+i));if(count<=150){store.write(c->meetings.update(c,id,user,body));assertThat(meetings.analysis(state(id)).get("items").size()).isEqualTo(count);}else assertThatThrownBy(()->store.write(c->meetings.update(c,id,user,body))).isInstanceOf(ApiError.class);
    }
    @ParameterizedTest @ValueSource(strings={"duplicate","missing","type","status","date","quote","offset","length"}) void invalidManualItemsNeverPersist(String mode)throws Exception {
        String id=create("workspace");analyze(id);var body=editBody(id);ObjectNode item=(ObjectNode)body.at("/analysis/items/1");switch(mode){case "duplicate"->item.put("id",body.at("/analysis/items/0/id").asText());case "missing"->item.remove("text");case "type"->item.put("type","invented");case "status"->item.put("status","confirmed");case "date"->item.put("due_date","2026-02-30");case "quote"->item.put("quote","forged");case "offset"->item.put("start_offset",1);case "length"->item.put("text","a".repeat(3001));}assertThatThrownBy(()->store.write(c->meetings.update(c,id,user,body))).isInstanceOf(ApiError.class);assertThat(state(id).get("provenance")).isEqualTo("ai");assertThat((List<?>)store.read(c->rows(c,"SELECT * FROM meeting_edits WHERE document_id=?",id))).isEmpty();
    }
    @ParameterizedTest @ValueSource(strings={"delete","text","quote","status","task"}) void onlyDecisionSnapshotChangesInvalidateLinks(String kind)throws Exception {
        String first=create("workspace"),second=create("workspace");analyze(first);analyze(second);var a=editBody(first);var b=editBody(second);((ObjectNode)a.at("/analysis/items/0")).put("status","confirmed");((ObjectNode)b.at("/analysis/items/0")).put("status","confirmed");store.write(c->meetings.update(c,first,user,a));store.write(c->meetings.update(c,second,user,b));
        ObjectNode link=json.createObjectNode().put("target_meeting_id",second).put("source_item_id",a.at("/analysis/items/0/id").asText()).put("target_item_id",b.at("/analysis/items/0/id").asText()).put("relation","related").put("expected_revision",1).put("expected_version",2).put("target_expected_revision",1).put("target_expected_version",2).put("quote",content).put("start_offset",0).put("end_offset",DocumentService.length(content));store.write(c->meetings.link(c,first,user,link));var edit=editBody(first);ObjectNode decision=(ObjectNode)edit.at("/analysis/items/0");switch(kind){case "delete"->((ArrayNode)edit.at("/analysis/items")).remove(0);case "text"->decision.put("text","Human correction");case "quote"->decision.put("quote","😀").put("start_offset",0).put("end_offset",1);case "status"->decision.put("status","needs_confirmation");case "task"->((ObjectNode)edit.at("/analysis/items/1")).put("assignee","Manual owner");}store.write(c->meetings.update(c,first,user,edit));assertThat((List<?>)store.read(c->meetings.links(c,first,user))).hasSize(kind.equals("task")?1:0);
    }
}
