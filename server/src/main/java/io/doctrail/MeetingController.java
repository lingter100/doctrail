package io.doctrail;

import com.fasterxml.jackson.databind.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static io.doctrail.Store.*;

@RestController @RequestMapping("/api")
public class MeetingController {
    final Store store;final Auth auth;final DocumentService docs;final MeetingService meetings;final KnowledgeService knowledge;
    MeetingController(Store store,Auth auth,DocumentService docs,MeetingService meetings,KnowledgeService knowledge){this.store=store;this.auth=auth;this.docs=docs;this.meetings=meetings;this.knowledge=knowledge;}
    static String visibility(String value){if(!Set.of("workspace","private").contains(value))throw new ApiError(422,"invalid_request");return value;}
    @GetMapping("/workspaces/{workspace}/meetings") Map<String,Object> list(@PathVariable String workspace,HttpServletRequest request){return store.read(c->Map.of("items",meetings.list(c,workspace,auth.user(c,request).get("id"))));}
    @PostMapping("/workspaces/{workspace}/meetings") @ResponseStatus(HttpStatus.CREATED) Map<String,Object> upload(@PathVariable String workspace,@RequestParam MultipartFile file,@RequestParam(required=false) String title,@RequestParam(defaultValue="workspace") String visibility,HttpServletRequest request)throws Exception{
        String v=visibility(visibility);if(file.getSize()>Ingest.MAX_FILE_BYTES)throw new ApiError(413,"file_too_large");byte[] bytes=file.getBytes();return autoAnalyze(store.write(c->meetings.upload(c,workspace,auth.user(c,request).get("id"),file.getOriginalFilename(),bytes,title,v)),request);
    }
    @PostMapping("/workspaces/{workspace}/meetings/text") @ResponseStatus(HttpStatus.CREATED) Map<String,Object> text(@PathVariable String workspace,@RequestBody JsonNode b,HttpServletRequest request){
        MeetingAnalysis.fields(b,"title","content","visibility");String title=MeetingAnalysis.text(b,"title",1,200),content=MeetingAnalysis.text(b,"content",1,Ingest.MAX_CONTENT_CHARS),v=visibility(MeetingAnalysis.text(b,"visibility",1,20));return autoAnalyze(store.write(c->meetings.upload(c,workspace,auth.user(c,request).get("id"),"meeting.txt",content.getBytes(StandardCharsets.UTF_8),title,v)),request);
    }
    @SuppressWarnings("unchecked") private Map<String,Object> autoAnalyze(Map<String,Object> detail,HttpServletRequest request){var document=(Map<String,Object>)detail.get("document");String id=(String)document.get("id");if("ready".equals(document.get("status")))try{return meetings.analyze(id,meetings.json.valueToTree(Map.of("expected_revision",document.get("revision"))),request);}catch(ApiError error){if(error.status!=503)throw error;}return store.read(c->meetings.detail(c,id,auth.user(c,request).get("id")));}
    @GetMapping("/meetings/{id}") Map<String,Object> detail(@PathVariable String id,HttpServletRequest request){return store.read(c->meetings.detail(c,id,auth.user(c,request).get("id")));}
    @PostMapping("/meetings/{id}/analyze") @ResponseStatus(HttpStatus.ACCEPTED) Map<String,Object> analyze(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest request){return meetings.analyze(id,b,request);}
    @PutMapping("/meetings/{id}/analysis") Map<String,Object> edit(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest request){return store.write(c->meetings.update(c,id,auth.user(c,request).get("id"),b));}
    @GetMapping("/meetings/{id}/runs") Map<String,Object> runs(@PathVariable String id,HttpServletRequest request){return store.read(c->{Object user=auth.user(c,request).get("id");docs.document(c,id,user,false);meetings.state(c,id);return Map.of("items",rows(c,"SELECT id,source_revision,status,model,model_revision,error,created_at,completed_at FROM meeting_runs WHERE document_id=? ORDER BY created_at DESC,id",id));});}
    @GetMapping("/meetings/{id}/links") Map<String,Object> links(@PathVariable String id,HttpServletRequest request){return store.read(c->Map.of("items",meetings.links(c,id,auth.user(c,request).get("id"))));}
    @PostMapping("/meetings/{id}/links") @ResponseStatus(HttpStatus.CREATED) Map<String,Object> link(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest request){return store.write(c->meetings.link(c,id,auth.user(c,request).get("id"),b));}
    @DeleteMapping("/meetings/{id}/links/{link}") @ResponseStatus(HttpStatus.NO_CONTENT) void deleteLink(@PathVariable String id,@PathVariable String link,HttpServletRequest request){store.write(c->{Object user=auth.user(c,request).get("id");docs.document(c,id,user,true);var l=one(c,"SELECT * FROM meeting_links WHERE id=? AND source_id=?",link,id);if(l==null)throw new ApiError(404,"link_not_found");docs.document(c,(String)l.get("target_id"),user,false);execute(c,"DELETE FROM meeting_links WHERE id=?",link);return null;});}
    @GetMapping("/tasks") Map<String,Object> tasks(@RequestParam(name="workspace_id",required=false) String workspace,@RequestParam(required=false) String assignee,@RequestParam(required=false) String status,HttpServletRequest request){return store.read(c->Map.of("items",meetings.tasks(c,auth.user(c,request).get("id"),workspace,assignee,status)));}
    @PostMapping("/knowledge/search") Map<String,Object> search(@RequestBody JsonNode b,HttpServletRequest request){return knowledge.execute(b,request,false);}
    @PostMapping("/knowledge/answer") Map<String,Object> answer(@RequestBody JsonNode b,HttpServletRequest request){return knowledge.execute(b,request,true);}
}
