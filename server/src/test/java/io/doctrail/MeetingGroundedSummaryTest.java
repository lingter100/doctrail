package io.doctrail;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import com.sun.net.httpserver.HttpServer;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.*;
import org.springframework.mock.web.MockHttpServletRequest;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;

/** Invented local fixtures verify contracts and custody, never model semantics. */
class MeetingGroundedSummaryTest {
    static final ObjectMapper JSON=new ObjectMapper();
    static final String SOURCE="😀 원문\n반복\n반복\n끝";

    static ObjectNode span(String source,int start,int end){
        return JSON.createObjectNode().put("quote",source.substring(source.offsetByCodePoints(0,start),source.offsetByCodePoints(0,end)))
                .put("start_offset",start).put("end_offset",end);
    }
    static ObjectNode sample(){
        ObjectNode a=MeetingAnalysis.empty(JSON);a.put("summary_version",2);
        ArrayNode claims=a.putArray("summary_claims");
        claims.addObject().put("id",0).put("text","뒤쪽 반복을 확인한다.").putArray("citations").add(span(SOURCE,8,10));
        claims.addObject().put("id",1).put("text","앞쪽 원문과 반복을 연결한다.").putArray("citations").add(span(SOURCE,0,4)).add(span(SOURCE,5,7));
        a.put("summary","뒤쪽 반복을 확인한다.\n앞쪽 원문과 반복을 연결한다.");
        a.putArray("summary_evidence").add(span(SOURCE,0,4)).add(span(SOURCE,5,7)).add(span(SOURCE,8,10));
        return a;
    }
    static ObjectNode single(String source,String text){
        ObjectNode a=MeetingAnalysis.empty(JSON);a.put("summary_version",2).put("summary",text);
        ObjectNode citation=span(source,0,DocumentService.length(source));
        a.putArray("summary_claims").addObject().put("id",0).put("text",text).putArray("citations").add(citation);
        a.putArray("summary_evidence").add(citation.deepCopy());return a;
    }
    static ObjectNode claim(ObjectNode a,int index){return (ObjectNode)a.get("summary_claims").get(index);}
    static ObjectNode citation(ObjectNode a){return (ObjectNode)claim(a,0).get("citations").get(0);}
    static void rejected(ObjectNode a,String source){assertThatThrownBy(()->MeetingAnalysis.validate(a,source,true)).isInstanceOf(ApiError.class).hasMessage("invalid_analysis");}

    @Test void legacyEmptyAndStrictFieldsRemainUnchanged(){
        ObjectNode empty=MeetingAnalysis.empty(JSON);
        assertThat(MeetingAnalysis.validate(empty,SOURCE,true)).isEqualTo(empty);
        ObjectNode old=MeetingAnalysis.empty(JSON);old.put("summary",SOURCE);old.withArray("summary_evidence").add(span(SOURCE,0,12));
        assertThat(MeetingAnalysis.validate(old,SOURCE,false)).isEqualTo(old);
        old.put("summary_version",1);rejected(old,SOURCE);
        empty.put("extra",true);rejected(empty,SOURCE);
    }
    @Test void repeatedQuotesKeepDistinctCodepointLocationsAndClaimOrder(){
        ObjectNode a=sample(),before=a.deepCopy();JsonNode validated=MeetingAnalysis.validate(a,SOURCE,true);
        assertThat(validated).isEqualTo(before).isNotSameAs(a);
        assertThat(validated.at("/summary_claims/0/citations/0/start_offset").asInt()).isEqualTo(8);
        assertThat(validated.at("/summary_evidence/1/quote")).isEqualTo(validated.at("/summary_evidence/2/quote"));
        assertThat(validated.at("/summary_evidence/1/start_offset").asInt()).isEqualTo(5);
        assertThat(validated.at("/summary_evidence/2/start_offset").asInt()).isEqualTo(8);
    }
    @ParameterizedTest
    @ValueSource(strings={"missing_version","missing_claims","null_version","string_version","float_version","unknown_version",
            "zero_claims","seven_claims","unknown_field","claim_field","null_text","blank_text","english_ai",
            "boolean_id","float_id","duplicate_id","wrong_order","empty_citations","five_citations","duplicate_citation",
            "unsorted_citations","wrong_quote","wrong_offset","boolean_offset","float_offset","outside_source","empty_span",
            "citation_field","summary_mismatch","evidence_mismatch","evidence_duplicate","evidence_unsorted","review_inside"})
    void malformedV2FailsClosed(String mutation){
        ObjectNode a=sample();
        switch(mutation){
            case "missing_version"->a.remove("summary_version");
            case "missing_claims"->a.remove("summary_claims");
            case "null_version"->a.putNull("summary_version");
            case "string_version"->a.put("summary_version","2");
            case "float_version"->a.put("summary_version",2.0);
            case "unknown_version"->a.put("summary_version",3);
            case "zero_claims"->a.putArray("summary_claims");
            case "seven_claims"->{var rows=a.withArray("summary_claims");while(rows.size()<7)rows.add(claim(a,0).deepCopy());}
            case "unknown_field"->a.put("confidence",1);
            case "claim_field"->claim(a,0).put("confidence",1);
            case "null_text"->claim(a,0).putNull("text");
            case "blank_text"->claim(a,0).put("text","\u00a0\u0085");
            case "english_ai"->{claim(a,0).put("text","English claim");a.put("summary","English claim\n앞쪽 원문과 반복을 연결한다.");}
            case "boolean_id"->claim(a,0).put("id",false);
            case "float_id"->claim(a,0).put("id",0.0);
            case "duplicate_id"->claim(a,1).put("id",0);
            case "wrong_order"->{claim(a,0).put("id",1);claim(a,1).put("id",0);}
            case "empty_citations"->claim(a,0).putArray("citations");
            case "five_citations"->{var rows=claim(a,0).withArray("citations");while(rows.size()<5)rows.add(span(SOURCE,8,10));}
            case "duplicate_citation"->claim(a,0).withArray("citations").add(span(SOURCE,8,10));
            case "unsorted_citations"->claim(a,0).withArray("citations").add(span(SOURCE,0,4));
            case "wrong_quote"->citation(a).put("quote","invented");
            case "wrong_offset"->citation(a).put("start_offset",7);
            case "boolean_offset"->citation(a).put("start_offset",false);
            case "float_offset"->citation(a).put("start_offset",8.0);
            case "outside_source"->citation(a).put("end_offset",999);
            case "empty_span"->citation(a).put("end_offset",8);
            case "citation_field"->citation(a).put("unit_id",2);
            case "summary_mismatch"->a.put("summary","다른 요약");
            case "evidence_mismatch"->a.withArray("summary_evidence").remove(0);
            case "evidence_duplicate"->a.withArray("summary_evidence").add(span(SOURCE,8,10));
            case "evidence_unsorted"->a.putArray("summary_evidence").add(span(SOURCE,8,10)).add(span(SOURCE,0,4)).add(span(SOURCE,5,7));
            case "review_inside"->a.putObject("summary_review").put("status","accepted");
            default->throw new AssertionError(mutation);
        }
        rejected(a,SOURCE);
    }
    @ParameterizedTest @ValueSource(ints={10,13,11,12,28,29,30,133,8232,8233})
    void everyPythonSplitlinesBoundaryIsRejected(int separator){rejected(single(SOURCE,"가"+(char)separator+"나"),SOURCE);}
    @Test void unicodeScalarAndWhitespaceParityWithoutRestrictingHumanLanguage(){
        assertThat(MeetingAnalysis.validate(single(SOURCE,"English human edit"),SOURCE,false)).isNotNull();
        assertThat(MeetingAnalysis.validate(single(SOURCE,"가"+"😀".repeat(239)),SOURCE,true)).isNotNull();
        rejected(single(SOURCE,"가"+"😀".repeat(240)),SOURCE);
        for(String text:List.of("가\ud800","가\udc00","\u00a0","\u0085","\u001f"))
            assertThatThrownBy(()->MeetingAnalysis.validate(single(SOURCE,text),SOURCE,false)).hasMessage("invalid_analysis");
        for(String source:List.of("가\ud800","가\udc00","\u00a0","\u0085"))
            assertThatThrownBy(()->MeetingAnalysis.validate(single(source,"근거가 있다."),source,false)).hasMessage("invalid_analysis");
    }
    @Test void sixClaimsTwentyFourReferencesAndTwelveHundredCodepointsAreExactLimits(){
        ObjectNode a=sample();ArrayNode claims=a.putArray("summary_claims");List<String> texts=new ArrayList<>();
        for(int i=0;i<6;i++){String text="가".repeat(200);texts.add(text);claims.addObject().put("id",i).put("text",text).putArray("citations")
            .add(span(SOURCE,0,4)).add(span(SOURCE,5,7)).add(span(SOURCE,8,10)).add(span(SOURCE,11,12));}
        a.put("summary",String.join("\n",texts));a.withArray("summary_evidence").add(span(SOURCE,11,12));
        assertThat(MeetingAnalysis.validate(a,SOURCE,true)).isEqualTo(a);
        claim(a,5).put("text","가".repeat(201));texts.set(5,"가".repeat(201));a.put("summary",String.join("\n",texts));rejected(a,SOURCE);
        String longSource="😀".repeat(12000);assertThat(MeetingAnalysis.validate(single(longSource,"긴 원문 근거다."),longSource,true)).isNotNull();
        rejected(single(longSource+"😀","긴 원문 근거다."),longSource+"😀");
    }

    @Nested class Persistence {
        @TempDir Path temp;Store store;MeetingService service;Auth auth;DocumentService docs=new DocumentService();MockHttpServletRequest request;FakeGeneration generation;
        String user="owner",workspace="workspace",session="synthetic-session";
        class FakeGeneration extends GenerationClient {
            volatile ObjectNode output;volatile Runnable during=()->{};
            FakeGeneration(){super("","",1000,JSON);reset(true);}
            void reset(boolean grounded){output=JSON.createObjectNode().put("schema_version",1).put("model","synthetic-not-llm").put("revision","fixture");output.set("analysis",grounded?sample():MeetingAnalysis.empty(JSON));if(grounded)output.putObject("summary_review").put("policy","grounded-review-v1").put("status","accepted");}
            @Override JsonNode call(String path,Object payload){during.run();return output.deepCopy();}
        }
        @BeforeEach void setup(){
            store=new Store(temp.resolve("synthetic.sqlite3").toString());auth=new Auth("0");
            store.write(c->{execute(c,"INSERT INTO users VALUES (?,?,?,?)",user,"owner@example.test","Owner","unused");execute(c,"INSERT INTO workspaces VALUES (?,?)",workspace,"Synthetic");execute(c,"INSERT INTO memberships VALUES (?,?,'owner')",workspace,user);execute(c,"INSERT INTO sessions VALUES (?,?,?)",Auth.hash(session),user,System.currentTimeMillis()/1000.0+60);return null;});
            request=new MockHttpServletRequest();request.setCookies(new Cookie(Auth.COOKIE,session));generation=new FakeGeneration();service=new MeetingService(store,auth,docs,JSON,generation);
        }
        @AfterEach void stop(){service.close();}
        @SuppressWarnings("unchecked") String create(){return (String)((Map<String,Object>)store.write(c->service.upload(c,workspace,user,"synthetic.txt",SOURCE.getBytes(StandardCharsets.UTF_8),"Synthetic","workspace")).get("document")).get("id");}
        Map<String,Object> state(String id){return store.read(c->service.state(c,id));}
        void analyze(String id)throws Exception{
            service.analyze(id,JSON.createObjectNode().put("expected_revision",1),request);
            long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(4);
            while(Set.of("queued","running").contains(state(id).get("analysis_status"))&&System.nanoTime()<end)Thread.sleep(10);
            assertThat(state(id).get("analysis_status")).isNotIn("queued","running");
        }
        ObjectNode edit(String id,JsonNode a){return JSON.createObjectNode().put("expected_revision",1).put("expected_version",((Number)state(id).get("version")).intValue()).set("analysis",a);}
        ObjectNode saved(String id)throws Exception{return (ObjectNode)service.analysis(state(id));}
        void update(String id,ObjectNode body){store.write(c->service.update(c,id,user,body));}

        @Test void acceptedAiPersistsClaimsAndRunButNotReviewBadgeAndHumanEditsRemainSeparate()throws Exception{
            String id=create();analyze(id);assertThat(state(id).get("analysis_status")).isEqualTo("ready");
            ObjectNode original=saved(id);assertThat(original).isEqualTo(sample());assertThat(original.has("summary_review")).isFalse();
            assertThat(store.read(c->one(c,"SELECT analysis FROM meeting_runs WHERE document_id=?",id)).get("analysis")).isEqualTo(original.toString());
            ObjectNode human=original.deepCopy();claim(human,0).put("text","Human-written summary");human.put("summary","Human-written summary\n앞쪽 원문과 반복을 연결한다.");
            ObjectNode body=edit(id,human);update(id,body);assertThat(saved(id)).isEqualTo(human);assertThat(state(id).get("provenance")).isEqualTo("user_edited");
            assertThat(JSON.readTree((String)state(id).get("ai_analysis"))).isEqualTo(original);
            assertThat(store.read(c->one(c,"SELECT analysis FROM meeting_edits WHERE document_id=?",id)).get("analysis")).isEqualTo(human.toString());
            assertThatThrownBy(()->update(id,body)).hasMessage("meeting_context_changed");
            ObjectNode outer=edit(id,human);outer.putObject("summary_review").put("status","accepted");assertThatThrownBy(()->update(id,outer)).hasMessage("invalid_analysis");
        }
        @ParameterizedTest @ValueSource(strings={"missing","wrong_policy","wrong_status","extra","null","array","numeric_status"})
        void missingOrMalformedReviewNeverPublishesAndRetryKeepsPriorDraft(String mode)throws Exception{
            String id=create();analyze(id);ObjectNode human=saved(id);claim(human,0).put("text","수정한 요약이다.");human.put("summary","수정한 요약이다.\n앞쪽 원문과 반복을 연결한다.");update(id,edit(id,human));
            String ai=(String)state(id).get("ai_analysis");int version=((Number)state(id).get("version")).intValue();
            switch(mode){case "missing"->generation.output.remove("summary_review");case "wrong_policy"->((ObjectNode)generation.output.get("summary_review")).put("policy","other");case "wrong_status"->((ObjectNode)generation.output.get("summary_review")).put("status","rejected");case "extra"->((ObjectNode)generation.output.get("summary_review")).put("confidence",1);case "null"->generation.output.putNull("summary_review");case "array"->generation.output.putArray("summary_review");case "numeric_status"->((ObjectNode)generation.output.get("summary_review")).put("status",1);}
            analyze(id);assertThat(state(id).get("analysis_status")).isEqualTo("ready");assertThat(state(id).get("analysis_error")).isEqualTo("generation_invalid_response");
            assertThat(saved(id)).isEqualTo(human);assertThat(state(id).get("ai_analysis")).isEqualTo(ai);assertThat(state(id).get("version")).isEqualTo(version);
            assertThat(store.read(c->one(c,"SELECT analysis FROM meeting_runs WHERE document_id=? AND status='failed'",id)).get("analysis")).isNull();
        }
        @Test void initialMissingReviewIsFailureWithoutAnyAiDraft()throws Exception{
            String id=create();generation.output.remove("summary_review");analyze(id);
            assertThat(state(id).get("analysis_status")).isEqualTo("failed");assertThat(state(id).get("ai_analysis")).isNull();assertThat(saved(id)).isEqualTo(MeetingAnalysis.empty(JSON));
        }
        @Test void existingMetadataItemsAndEditedStatusesSurviveFailedV2Reanalysis()throws Exception{
            ObjectNode a=(ObjectNode)generation.output.get("analysis");a.put("meeting_title","원문").put("purpose","반복");a.withArray("participants").add("반복");
            for(String field:List.of("meeting_title","purpose","participants")){
                ObjectNode evidence=span(SOURCE,field.equals("meeting_title")?0:8,field.equals("meeting_title")?4:10);evidence.put("field",field);a.withArray("metadata_evidence").add(evidence);
            }
            for(String type:List.of("decision","action")){
                ObjectNode item=span(SOURCE,8,10);item.put("id","").put("type",type).put("text","반복 내용을 확인한다.").put("status",type.equals("action")?"todo":"needs_confirmation").putNull("assignee").putNull("due_date").putNull("priority");a.withArray("items").add(item);
            }
            String id=create();analyze(id);ObjectNode original=saved(id);
            assertThat(original.get("metadata_evidence")).isEqualTo(a.get("metadata_evidence"));assertThat(original.get("participants")).isEqualTo(a.get("participants"));
            assertThat(original.at("/items/0/id").asText()).matches("[0-9a-f]{32}");assertThat(original.at("/items/1/id")).isNotEqualTo(original.at("/items/0/id"));
            ObjectNode human=original.deepCopy();((ObjectNode)human.at("/items/0")).put("status","confirmed");((ObjectNode)human.at("/items/1")).put("status","done");update(id,edit(id,human));
            generation.output.with("analysis").put("summary","projection mismatch");analyze(id);
            assertThat(state(id).get("analysis_error")).isEqualTo("invalid_analysis");assertThat(saved(id)).isEqualTo(human);assertThat(JSON.readTree((String)state(id).get("ai_analysis"))).isEqualTo(original);
            List<Map<String,Object>> tasks=store.read(c->service.tasks(c,user,null,null,"done"));assertThat(tasks).hasSize(1);
        }
        @Test void ordinaryLegacyEditCannotInventAV2Upgrade()throws Exception{
            generation.reset(false);String id=create();analyze(id);
            assertThatThrownBy(()->update(id,edit(id,sample()))).hasMessage("invalid_analysis");assertThat(saved(id)).isEqualTo(MeetingAnalysis.empty(JSON));
        }
        @ParameterizedTest @ValueSource(booleans={true,false})
        void onlyExactSavedAiDraftMayCrossVersionsInEitherDirection(boolean startGrounded)throws Exception{
            generation.reset(startGrounded);String id=create();analyze(id);update(id,edit(id,saved(id)));ObjectNode current=saved(id);
            generation.reset(!startGrounded);analyze(id);assertThat(saved(id)).isEqualTo(current);
            ObjectNode latest=(ObjectNode)JSON.readTree((String)state(id).get("ai_analysis"));ObjectNode changed=latest.deepCopy();changed.put("purpose","human change");
            assertThatThrownBy(()->update(id,edit(id,changed))).hasMessage("invalid_analysis");assertThat(saved(id)).isEqualTo(current);
            update(id,edit(id,latest));assertThat(saved(id)).isEqualTo(latest);assertThat(state(id).get("provenance")).isEqualTo("user_edited");
        }
        @Test void removingV2FieldsCannotDowngradeAndCasAndOwnershipStillApply()throws Exception{
            String id=create();analyze(id);ObjectNode downgrade=saved(id);downgrade.remove(List.of("summary_version","summary_claims"));
            assertThatThrownBy(()->update(id,edit(id,downgrade))).hasMessage("invalid_analysis");
            ObjectNode stale=edit(id,saved(id));stale.put("expected_revision",2);assertThatThrownBy(()->update(id,stale)).hasMessage("meeting_context_changed");
            store.write(c->{execute(c,"UPDATE memberships SET role='member' WHERE user_id=?",user);return null;});
            // The document owner still edits as a member; another user cannot impersonate ownership.
            assertThatThrownBy(()->store.write(c->service.update(c,id,"not-a-member",edit(id,sample())))).isInstanceOf(ApiError.class);
        }
        @ParameterizedTest @ValueSource(strings={"logout","membership","revision","version"})
        void inFlightV2StillRevalidatesContextBeforePublishing(String mutation)throws Exception{
            String id=create();generation.during=()->store.write(c->{switch(mutation){case "logout"->execute(c,"DELETE FROM sessions");case "membership"->execute(c,"DELETE FROM memberships");case "revision"->docs.edit(c,id,user,"Changed",SOURCE+" changed","workspace");case "version"->execute(c,"UPDATE meetings SET version=version+1 WHERE document_id=?",id);}return null;});
            analyze(id);assertThat(state(id).get("ai_analysis")).isNull();assertThat(state(id).get("analysis_status")).isIn("failed","stale");
        }
    }

    @ParameterizedTest @CsvSource({"502,generation_summary_insufficient,generation_summary_insufficient","502,generation_summary_review_rejected,generation_summary_review_rejected","503,generation_summary_review_rejected,generation_unavailable","502,private_unknown_summary_error,generation_unavailable"})
    void onlyTwoNewWorkerCodesCrossExistingErrorBoundary(int status,String code,String expected)throws Exception{
        HttpServer worker=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        byte[] body=("{\"error\":\""+code+"\",\"detail\":\"PRIVATE_SYNTHETIC_TEXT\"}").getBytes(StandardCharsets.UTF_8);
        worker.createContext("/analyze",exchange->{try{exchange.sendResponseHeaders(status,body.length);exchange.getResponseBody().write(body);}finally{exchange.close();}});worker.start();
        try{var client=new GenerationClient("http://127.0.0.1:"+worker.getAddress().getPort(),"synthetic-grounded-test-token-123456",2000,JSON);
            var error=catchThrowableOfType(()->client.call("/analyze",Map.of()),ApiError.class);
            assertThat(error).hasMessage(expected).hasMessageNotContaining("PRIVATE_SYNTHETIC_TEXT");assertThat(error.status).isEqualTo(503);
        }finally{worker.stop(0);}
    }
}
