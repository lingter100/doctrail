package io.doctrail;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.web.servlet.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import static io.doctrail.Store.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.doThrow;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Synthetic automated service checks; no human review or retrieval quality claim. */
@SpringBootTest @AutoConfigureMockMvc @ExtendWith(OutputCaptureExtension.class)
class ApiIntegrationTest {
    static final Path DATABASE=tempDatabase();
    static Path tempDatabase(){try{return Files.createTempDirectory("doctrail-java-test-").resolve("test.sqlite3");}catch(Exception e){throw new RuntimeException(e);}}
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry){registry.add("doctrail.db",DATABASE::toString);}
    @Autowired MockMvc mvc; @Autowired ObjectMapper json; @Autowired Store store;
    @MockitoSpyBean DocumentService docs;
    record Account(String email,String user,String workspace,Cookie cookie){}
    Account register() throws Exception {
        String email=Auth.uid()+"@example.test";
        MvcResult result=mvc.perform(post("/api/auth/register").with(r->{r.setRemoteAddr(email);return r;}).contentType("application/json").content(json.writeValueAsBytes(Map.of("email",email,"password","synthetic-password","name","Synthetic","workspace_name","Synthetic workspace"))))
            .andExpect(status().isCreated()).andReturn();
        JsonNode body=tree(result);return new Account(email,body.at("/user/id").asText(),body.at("/workspaces/0/id").asText(),result.getResponse().getCookie(Auth.COOKIE));
    }
    JsonNode tree(MvcResult result)throws Exception{return json.readTree(result.getResponse().getContentAsByteArray());}
    JsonNode upload(Account account,String content,String visibility)throws Exception{return tree(mvc.perform(multipart("/api/workspaces/"+account.workspace+"/documents").file(new MockMultipartFile("file","guide.md","text/markdown",content.getBytes(java.nio.charset.StandardCharsets.UTF_8))).param("visibility",visibility).cookie(account.cookie)).andExpect(status().isCreated()).andReturn());}
    JsonNode search(Account account,String workspace,String query)throws Exception{return tree(mvc.perform(get("/api/workspaces/"+workspace+"/search").param("q",query).cookie(account.cookie)).andExpect(status().isOk()).andReturn());}
    JsonNode edit(Account account,String id,String content,String visibility)throws Exception{return tree(mvc.perform(put("/api/documents/"+id).cookie(account.cookie).contentType("application/json").content(json.writeValueAsBytes(Map.of("title","edited","content",content,"visibility",visibility)))).andExpect(status().isOk()).andReturn());}
    void member(Account owner,Account member)throws Exception{mvc.perform(post("/api/workspaces/"+owner.workspace+"/members").cookie(owner.cookie).contentType("application/json").content(json.writeValueAsBytes(Map.of("email",member.email)))).andExpect(status().isCreated());}
    @Test void sessionsPersistAreOpaqueAndRotate()throws Exception{
        Account account=register();
        assertThat(account.cookie.isHttpOnly()).isTrue();assertThat(account.cookie.getAttribute("SameSite")).isEqualTo("Strict");
        Store restarted=new Store(DATABASE.toString());
        assertThat(restarted.read(c->one(c,"SELECT token_hash FROM sessions WHERE user_id=?",account.user).get("token_hash")).toString()).isEqualTo(Auth.hash(account.cookie.getValue()));
        mvc.perform(get("/api/auth/me").header("X-User-ID",account.user)).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/auth/me").cookie(new Cookie(Auth.COOKIE,"forged"))).andExpect(status().isUnauthorized());
        MvcResult login=mvc.perform(post("/api/auth/login").cookie(account.cookie).contentType("application/json").content(json.writeValueAsBytes(Map.of("email",account.email,"password","synthetic-password")))).andExpect(status().isOk()).andReturn();
        mvc.perform(get("/api/auth/me").cookie(account.cookie)).andExpect(status().isUnauthorized());
        Cookie current=login.getResponse().getCookie(Auth.COOKIE);mvc.perform(get("/api/auth/me").cookie(current)).andExpect(status().isOk());
        mvc.perform(post("/api/auth/logout").cookie(current)).andExpect(status().isNoContent());mvc.perform(get("/api/auth/me").cookie(current)).andExpect(status().isUnauthorized());
    }
    @Test void aclFiltersCandidatesBeforeStatisticsAndRevocationApplies()throws Exception{
        Account owner=register(),member=register();JsonNode shared=upload(owner,"refund policy","workspace"),hidden=upload(owner,"hiddenunique refund","private");
        mvc.perform(get("/api/documents/"+shared.get("id").asText()).cookie(member.cookie)).andExpect(status().isNotFound());member(owner,member);
        JsonNode before=search(member,owner.workspace,"refund");assertThat(before.get("results").size()).isEqualTo(1);
        upload(owner,"refund ".repeat(300),"private");assertThat(search(member,owner.workspace,"refund").get("results")).isEqualTo(before.get("results"));
        mvc.perform(get("/api/documents/"+hidden.get("id").asText()).cookie(member.cookie)).andExpect(status().isNotFound());
        mvc.perform(delete("/api/documents/"+shared.get("id").asText()).cookie(member.cookie)).andExpect(status().isForbidden());
        store.write(c->{execute(c,"DELETE FROM memberships WHERE workspace_id=? AND user_id=?",owner.workspace,member.user);return null;});
        mvc.perform(get("/api/workspaces/"+owner.workspace+"/history").cookie(member.cookie)).andExpect(status().isNotFound());
        mvc.perform(post("/api/searches/"+before.get("search_id").asText()+"/feedback").cookie(member.cookie).contentType("application/json").content(json.writeValueAsBytes(Map.of("document_id",shared.get("id").asText(),"relevant",true)))).andExpect(status().isNotFound());
    }
    @Test void revisionsHistoryFeedbackAndDeleteStayConsistent()throws Exception{
        Account owner=register(),member=register();member(owner,member);JsonNode doc=upload(owner,"refund original 😀\r\n".repeat(80),"workspace");String id=doc.get("id").asText();
        JsonNode found=search(member,owner.workspace,"refund");String feedback="/api/searches/"+found.get("search_id").asText()+"/feedback";byte[] body=json.writeValueAsBytes(Map.of("document_id",id,"relevant",true));
        mvc.perform(post(feedback).cookie(member.cookie).contentType("application/json").content(body)).andExpect(status().isOk());
        mvc.perform(post(feedback).cookie(owner.cookie).contentType("application/json").content(body)).andExpect(status().isNotFound());
        JsonNode updated=edit(owner,id,"newword evidence","private");assertThat(updated.get("revision").asInt()).isEqualTo(2);
        assertThat(updated.at("/chunks/0/id").asText()).isNotEqualTo(doc.at("/chunks/0/id").asText());
        mvc.perform(post(feedback).cookie(member.cookie).contentType("application/json").content(body)).andExpect(status().isNotFound());
        mvc.perform(get("/api/workspaces/"+owner.workspace+"/history").cookie(member.cookie)).andExpect(jsonPath("$.items[0].result_count").value(0));
        edit(owner,id,"newword evidence","workspace");mvc.perform(post(feedback).cookie(member.cookie).contentType("application/json").content(body)).andExpect(status().isConflict());
        mvc.perform(post("/api/documents/"+id+"/reprocess").cookie(owner.cookie)).andExpect(status().isOk()).andExpect(jsonPath("$.revision").value(4));
        mvc.perform(delete("/api/documents/"+id).cookie(owner.cookie)).andExpect(status().isNoContent());assertThat(search(owner,owner.workspace,"newword").get("results").size()).isZero();
        int remainingChunks=store.read(c->((Number)one(c,"SELECT COUNT(*) AS n FROM chunks WHERE document_id=?",id).get("n")).intValue());
        assertThat(remainingChunks).isZero();
    }
    @Test void failedPdfCanBeRepairedAndHtmlStaysJsonText()throws Exception{
        Account account=register();JsonNode failed=tree(mvc.perform(multipart("/api/workspaces/"+account.workspace+"/documents").file(new MockMultipartFile("file","broken.pdf","application/pdf","bad".getBytes())).cookie(account.cookie)).andExpect(status().isCreated()).andReturn());
        assertThat(failed.get("error").asText()).isEqualTo("pdf_parse_failed");assertThat(failed.get("chunks").size()).isZero();String id=failed.get("id").asText();
        mvc.perform(post("/api/documents/"+id+"/reprocess").cookie(account.cookie)).andExpect(jsonPath("$.status").value("failed"));
        String content="<script>alert('synthetic')</script> evidence";assertThat(edit(account,id,content,"workspace").get("content").asText()).isEqualTo(content);
    }
    @Test void failedChunkReplacementRollsBackDocumentAndChunks()throws Exception{
        Account account=register();JsonNode doc=upload(account,"originalword evidence","workspace");String id=doc.get("id").asText();
        doThrow(new RuntimeException("PRIVATE_INJECTED_DETAIL")).when(docs).replaceChunks(any(),eq(id),any());
        mvc.perform(put("/api/documents/"+id).cookie(account.cookie).contentType("application/json").content(json.writeValueAsBytes(Map.of("title","new","content","replacement","visibility","workspace")))).andExpect(status().isInternalServerError()).andExpect(content().json("{\"detail\":\"internal_error\"}"));
        assertThat(tree(mvc.perform(get("/api/documents/"+id).cookie(account.cookie)).andExpect(status().isOk()).andReturn())).isEqualTo(doc);
    }
    @Test void errorsGuardsAndLogsNeverEchoInputs(CapturedOutput output)throws Exception{
        Account account=register();upload(account,"SECRET_DOCUMENT_PAYLOAD","workspace");search(account,account.workspace,"SECRET_QUERY_PAYLOAD");
        mvc.perform(post("/api/auth/logout").cookie(account.cookie).header("Origin","https://evil.invalid")).andExpect(status().isForbidden());
        mvc.perform(post("/api/auth/logout").cookie(account.cookie).header("Sec-Fetch-Site","cross-site")).andExpect(status().isForbidden());
        mvc.perform(post("/api/auth/login").contentType("application/json").content("{\"email\":\"no\",\"password\":\"SECRET_PASSWORD\",\"user_id\":\"bad\"}")).andExpect(status().isUnprocessableEntity()).andExpect(content().json("{\"detail\":\"invalid_request\"}"));
        mvc.perform(post("/api/workspaces").cookie(account.cookie).contentType("application/json").content(new byte[RequestGuard.MAX_REQUEST_BYTES+1])).andExpect(status().isPayloadTooLarge());
        mvc.perform(get("/api/missing")).andExpect(status().isNotFound()).andExpect(header().exists("X-Request-ID")).andExpect(header().string("Cache-Control","no-store"));
        assertThat(output.getAll()).doesNotContain("SECRET_DOCUMENT_PAYLOAD","SECRET_QUERY_PAYLOAD","SECRET_PASSWORD","PRIVATE_INJECTED_DETAIL");
    }
    @Test void concurrentSearchesOwnSeparateConnections()throws Exception{
        Account account=register();upload(account,"refund evidence","workspace");
        try(ExecutorService executor=Executors.newFixedThreadPool(4)){
            List<Future<JsonNode>> futures=new ArrayList<>();for(int i=0;i<8;i++)futures.add(executor.submit(()->search(account,account.workspace,"refund")));
            for(Future<JsonNode> future:futures)assertThat(future.get(20,TimeUnit.SECONDS).get("results").size()).isEqualTo(1);
        }
    }
    @Test void expiryAndRateLimitAreEnforced()throws Exception{
        Account account=register();store.write(c->{execute(c,"UPDATE sessions SET expires_at=0 WHERE user_id=?",account.user);return null;});mvc.perform(get("/api/auth/me").cookie(account.cookie)).andExpect(status().isUnauthorized());
        String address=Auth.uid();for(int i=0;i<20;i++)mvc.perform(post("/api/auth/login").with(r->{r.setRemoteAddr(address);return r;}).contentType("application/json").content("{\"email\":\"none@example.test\",\"password\":\"bad\"}")).andExpect(status().isUnauthorized());
        mvc.perform(post("/api/auth/login").with(r->{r.setRemoteAddr(address);return r;}).contentType("application/json").content("{\"email\":\"none@example.test\",\"password\":\"bad\"}")).andExpect(status().isTooManyRequests()).andExpect(header().string("Retry-After","60"));
    }
    @Test void pythonUnicodeWhitespaceValidationIsPreserved()throws Exception{
        Account account=register();
        mvc.perform(post("/api/workspaces").cookie(account.cookie).contentType("application/json").content(json.writeValueAsBytes(Map.of("name","\u00a0\u0085")))).andExpect(status().isUnprocessableEntity());
        mvc.perform(get("/api/workspaces/"+account.workspace+"/search").param("q","\u00a0\u0085").cookie(account.cookie)).andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.detail").value("query_required"));
        mvc.perform(post("/api/auth/login").contentType("application/json").content(json.writeValueAsBytes(Map.of("email","a\u0085b@example.test","password","synthetic")))).andExpect(status().isUnprocessableEntity());
        JsonNode doc=upload(account,"synthetic evidence","workspace");
        mvc.perform(put("/api/documents/"+doc.get("id").asText()).cookie(account.cookie).contentType("application/json").content(json.writeValueAsBytes(Map.of("title","\u00a0","content","valid content","visibility","workspace")))).andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.detail").value("invalid_title"));
    }
    @Test void readyReprocessFailureKeepsVerifiedRevision()throws Exception{
        Account account=register();JsonNode doc=upload(account,"synthetic verified source","workspace");String id=doc.get("id").asText();
        store.write(c->{execute(c,"UPDATE documents SET source=? WHERE id=?",new byte[]{(byte)0xff},id);return null;});
        mvc.perform(post("/api/documents/"+id+"/reprocess").cookie(account.cookie)).andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.detail").value("utf8_required"));
        assertThat(tree(mvc.perform(get("/api/documents/"+id).cookie(account.cookie)).andExpect(status().isOk()).andReturn())).isEqualTo(doc);
    }
}
