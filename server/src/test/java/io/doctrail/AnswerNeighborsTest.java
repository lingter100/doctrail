package io.doctrail;

import com.fasterxml.jackson.databind.*;
import jakarta.servlet.http.Cookie;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.*;
import java.util.function.IntConsumer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.mock.web.MockHttpServletRequest;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;

/** SQLite authorization and actual BM25; generation is a synthetic in-memory transport. */
class AnswerNeighborsTest {
    @TempDir Path temp;
    final ObjectMapper json=new ObjectMapper();final DocumentService docs=new DocumentService();
    final Auth auth=new Auth("0");Store store;MeetingService meetings;InferenceClient inference;
    MockHttpServletRequest request;GenerationClient generation;String document;
    int calls,reads;JsonNode payload;Runnable during=()->{};IntConsumer afterRead=n->{};

    @BeforeEach void setup() {
        store=new Store(temp.resolve("neighbors.sqlite3").toString()) {
            @Override <T>T read(Work<T> work){T value=super.read(work);afterRead.accept(++reads);return value;}
        };
        store.write(c->{
            for(String user:List.of("owner","other"))execute(c,"INSERT INTO users VALUES (?,?,?,?)",user,user+"@example.test",user,"unused");
            execute(c,"INSERT INTO workspaces VALUES ('scope','Synthetic')");
            execute(c,"INSERT INTO workspaces VALUES ('outside','Not authorized')");
            execute(c,"INSERT INTO memberships VALUES ('scope','owner','owner')");
            execute(c,"INSERT INTO memberships VALUES ('scope','other','member')");
            execute(c,"INSERT INTO memberships VALUES ('outside','other','owner')");
            execute(c,"INSERT INTO sessions VALUES (?,?,?)",Auth.hash("session"),"owner",System.currentTimeMillis()/1000.0+120);return null;
        });
        request=new MockHttpServletRequest();request.setCookies(new Cookie(Auth.COOKIE,"session"));
        generation=new GenerationClient("","",1000,json) {
            @Override JsonNode call(String path,Object body) {
                calls++;payload=json.valueToTree(body);during.run();
                var contexts=payload.path("contexts");var source=contexts.get(contexts.size()-1);
                var out=json.createObjectNode().put("schema_version",1).put("model","synthetic").put("revision","fixture").put("status","answered");
                out.putArray("claims").addObject().put("text","Synthetic claim").putArray("citations").addObject()
                        .put("chunk_id",source.path("chunk_id").asText()).put("quote",source.path("text").asText())
                        .put("start_offset",source.path("start_offset").asInt()).put("end_offset",source.path("end_offset").asInt());
                return out;
            }
        };
        meetings=new MeetingService(store,auth,docs,json,generation);inference=new InferenceClient("","",1000,json);
        List<String> pieces=List.of("Left context. ","release anchor. ","Right evidence 😀. ","Unvisited tail.");
        document=upload("scope","owner","workspace",String.join("",pieces));
        store.write(c->{execute(c,"DELETE FROM chunks WHERE document_id=?",document);int offset=0;
            for(int i=0;i<pieces.size();i++){String text=pieces.get(i);int end=offset+text.codePointCount(0,text.length());
                execute(c,"INSERT INTO chunks VALUES (?,?,?,?,?,?,?)","c"+i,document,text,1,offset,end,i);offset=end;}return null;
        });
        upload("scope","other","private","release PRIVATE");upload("outside","other","workspace","release OUTSIDE");reads=0;
    }
    String upload(String workspace,String owner,String visibility,String content) {
        return store.write(c->docs.upload(c,workspace,owner,"fixture.txt",content.getBytes(StandardCharsets.UTF_8),"Synthetic",visibility)).get("id").toString();
    }
    KnowledgeService service(boolean enabled) {
        return new KnowledgeService(store,auth,docs,meetings,new LearnedSearch(store,auth,docs,inference),inference,generation,json,false,enabled);
    }
    JsonNode run(KnowledgeService service,boolean answer) {
        return json.valueToTree(service.execute(json.createObjectNode().put("query","release").put("limit",5),request,answer));
    }
    @AfterEach void close(){if(meetings!=null)meetings.close();}

    @Test void optInExpandsOnlyAnswerWhileResultsAndHistoryKeepOriginalRanking() {
        var response=run(service(true),true);
        assertThat(payload.path("contexts").findValuesAsText("chunk_id")).containsExactly("c1","c0","c2");
        assertThat(payload.toString()).doesNotContain("PRIVATE","OUTSIDE","Unvisited tail");
        assertThat(response.path("results").findValuesAsText("chunk_id")).containsExactly("c1");
        assertThat(response.at("/claims/0/citations/0/chunk_id").asText()).isEqualTo("c2");
        assertThat(response.at("/claims/0/citations/0/quote").asText()).isEqualTo("Right evidence 😀. ");
        assertThat(store.read(c->rows(c,"SELECT chunk_id FROM knowledge_history_results")).stream().map(r->r.get("chunk_id")))
                .containsExactly("c1");
    }
    @Test void defaultOffAndSearchKeepExistingContextAndRanking() {
        var defaultService=new KnowledgeService(store,auth,docs,meetings,new LearnedSearch(store,auth,docs,inference),inference,generation,json);
        run(defaultService,true);assertThat(payload.path("contexts").findValuesAsText("chunk_id")).containsExactly("c1");
        var search=run(service(true),false);
        assertThat(search.path("results").findValuesAsText("chunk_id")).containsExactly("c1");
        assertThat(calls).isEqualTo(1);
    }
    @ParameterizedTest @CsvSource({"before,revision","before,membership","before,session","after,revision","after,membership","after,session"})
    void authorizationAndRevisionChangesRejectBeforePayloadOrFinalSave(String when,String mutation) {
        Runnable change=()->store.write(c->{switch(mutation){
            case "revision"->execute(c,"UPDATE documents SET revision=revision+1 WHERE id=?",document);
            case "membership"->execute(c,"DELETE FROM memberships WHERE workspace_id='scope' AND user_id='owner'");
            case "session"->execute(c,"DELETE FROM sessions");
        }return null;});
        if(when.equals("before"))afterRead=n->{if(n==1)change.run();};else during=change;
        assertThatThrownBy(()->run(service(true),true)).isInstanceOf(ApiError.class);
        assertThat(calls).isEqualTo(when.equals("before")?0:1);
        assertThat((List<?>)store.read(c->rows(c,"SELECT * FROM knowledge_history"))).isEmpty();
        assertThat((List<?>)store.read(c->rows(c,"SELECT * FROM knowledge_history_results"))).isEmpty();
    }
}
