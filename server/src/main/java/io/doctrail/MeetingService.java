package io.doctrail;

import com.fasterxml.jackson.databind.*;
import jakarta.annotation.PreDestroy;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Service;
import java.sql.Connection;
import java.util.*;
import java.util.concurrent.*;
import static io.doctrail.Store.*;

@Service
public class MeetingService {
    final Store store;final Auth auth;final DocumentService docs;final ObjectMapper json;final GenerationClient generation;
    private final ThreadPoolExecutor jobs=new ThreadPoolExecutor(1,1,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(8),r->{Thread t=new Thread(r,"meeting-analysis");t.setDaemon(true);return t;},new ThreadPoolExecutor.AbortPolicy());
    MeetingService(Store store,Auth auth,DocumentService docs,ObjectMapper json,GenerationClient generation){this.store=store;this.auth=auth;this.docs=docs;this.json=json;this.generation=generation;
        store.write(c->{execute(c,"UPDATE meeting_runs SET status='failed',error='generation_interrupted',completed_at=? WHERE status IN ('queued','running')",Auth.now());execute(c,"UPDATE meetings SET analysis_status=CASE WHEN ai_analysis IS NOT NULL AND source_revision=(SELECT revision FROM documents WHERE id=meetings.document_id) THEN 'ready' ELSE 'failed' END,analysis_error='generation_interrupted',active_run=NULL WHERE analysis_status IN ('queued','running')");return null;});
    }
    @PreDestroy void close(){jobs.shutdownNow();try{jobs.awaitTermination(5,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}}
    Map<String,Object> state(Connection c,String id)throws Exception{var m=one(c,"SELECT * FROM meetings WHERE document_id=?",id);if(m==null)throw new ApiError(404,"meeting_not_found");return m;}
    JsonNode analysis(Map<String,Object> row)throws Exception{return json.readTree((String)row.get("analysis"));}
    Map<String,Object> detail(Connection c,String id,Object user)throws Exception{
        var d=docs.document(c,id,user,false);var m=new LinkedHashMap<>(state(c,id));m.remove("active_run");JsonNode a=analysis(m);m.put("analysis",a);m.put("ai_analysis",m.get("ai_analysis")==null?null:json.readTree((String)m.get("ai_analysis")));m.put("meeting_date",a.get("meeting_date"));m.put("participants",a.get("participants"));return Map.of("document",docs.serialize(c,d,true),"meeting",m);
    }
    Map<String,Object> upload(Connection c,String workspace,Object user,String filename,byte[] source,String title,String visibility)throws Exception{
        var d=docs.upload(c,workspace,user,filename,source,title,visibility);String id=(String)d.get("id");execute(c,"INSERT INTO meetings(document_id,analysis_status,analysis_error,source_revision,version,ai_analysis,analysis,provenance) VALUES (?,?,?,?,0,NULL,?,'ai')",id,"failed","analysis_not_started",d.get("revision"),json.writeValueAsString(MeetingAnalysis.empty(json)));return detail(c,id,user);
    }
    List<Map<String,Object>> list(Connection c,String workspace,Object user)throws Exception{
        docs.membership(c,workspace,user,false);List<Map<String,Object>> result=new ArrayList<>();for(var d:rows(c,"SELECT d.id FROM documents d JOIN meetings m ON m.document_id=d.id WHERE workspace_id=? AND (visibility='workspace' OR owner_id=?) ORDER BY updated_at DESC,d.id",workspace,user))result.add(detail(c,(String)d.get("id"),user));return result;
    }
    static void cas(Map<String,Object> d,Map<String,Object> m,int revision,int version){if(((Number)d.get("revision")).intValue()!=revision||((Number)m.get("source_revision")).intValue()!=revision||((Number)m.get("version")).intValue()!=version)throw new ApiError(409,"meeting_context_changed");}
    Map<String,Object> update(Connection c,String id,Object user,JsonNode body)throws Exception{
        MeetingAnalysis.fields(body,"expected_revision","expected_version","analysis");var d=docs.document(c,id,user,true);var m=state(c,id);cas(d,m,MeetingAnalysis.integer(body,"expected_revision",1,Integer.MAX_VALUE),MeetingAnalysis.integer(body,"expected_version",0,Integer.MAX_VALUE));if(Set.of("running","queued").contains(m.get("analysis_status")))throw new ApiError(409,"analysis_running");if(!"ready".equals(m.get("analysis_status")))throw new ApiError(409,"analysis_not_ready");
        var a=MeetingAnalysis.validate(body.get("analysis"),(String)d.get("content"),false);execute(c,"INSERT INTO meeting_edits VALUES (?,?,?,?,?,?,?)",Auth.uid(),id,d.get("revision"),((Number)m.get("version")).intValue()+1,json.writeValueAsString(a),user,Auth.now());execute(c,"UPDATE meetings SET analysis=?,provenance='user_edited',version=version+1 WHERE document_id=?",json.writeValueAsString(a),id);return detail(c,id,user);
    }
    record Job(String id,String run,Object user,String sessionHash,Map<String,Object> document,Map<String,Object> membership,int version){}
    Map<String,Object> analyze(String id,JsonNode body,HttpServletRequest request){
        MeetingAnalysis.fields(body,"expected_revision");int revision=MeetingAnalysis.integer(body,"expected_revision",1,Integer.MAX_VALUE);
        Job job=store.write(c->{Object user=auth.user(c,request).get("id");var d=docs.document(c,id,user,true);var m=state(c,id);if(((Number)d.get("revision")).intValue()!=revision)throw new ApiError(409,"meeting_context_changed");if(!"ready".equals(d.get("status")))throw new ApiError(409,"document_not_ready");if(Set.of("queued","running").contains(m.get("analysis_status")))throw new ApiError(409,"analysis_running");String run=Auth.uid();execute(c,"INSERT INTO meeting_runs(id,document_id,source_revision,status,created_at) VALUES (?,?,?,'queued',?)",run,id,revision,Auth.now());execute(c,"UPDATE meetings SET analysis_status='queued',analysis_error=NULL,active_run=? WHERE document_id=?",run,id);return new Job(id,run,user,Auth.hash(Auth.token(request)),snapshotDocument(d),one(c,"SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",d.get("workspace_id"),user),((Number)m.get("version")).intValue());});
        try{jobs.execute(()->run(job));}catch(RejectedExecutionException e){fail(job,"generation_queue_full");throw new ApiError(503,"generation_queue_full");}
        return store.read(c->detail(c,id,auth.user(c,request).get("id")));
    }
    static Map<String,Object> snapshotDocument(Map<String,Object> d){var copy=new LinkedHashMap<>(d);copy.remove("source");return copy;}
    void revalidate(Connection c,Job job)throws Exception{
        var session=one(c,"SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",job.sessionHash,System.currentTimeMillis()/1000.0);if(session==null||!job.user.equals(session.get("user_id")))throw new ApiError(409,"analysis_context_changed");var d=docs.document(c,job.id,job.user,true);var m=state(c,job.id);if(!job.document.equals(snapshotDocument(d))||!Objects.equals(m.get("active_run"),job.run)||((Number)m.get("version")).intValue()!=job.version||!job.membership.equals(one(c,"SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",d.get("workspace_id"),job.user)))throw new ApiError(409,"analysis_context_changed");
    }
    void run(Job job){
        try{
            store.write(c->{revalidate(c,job);execute(c,"UPDATE meetings SET analysis_status='running' WHERE document_id=?",job.id);execute(c,"UPDATE meeting_runs SET status='running' WHERE id=?",job.run);return null;});
            var output=generation.call("/analyze",Map.of("schema_version",1,"document_id",job.id,"revision",job.document.get("revision"),"title",job.document.get("title"),"content",job.document.get("content")));
            JsonNode draft=output.path("analysis").deepCopy();if(draft.path("items").isArray())for(var item:draft.get("items"))if(item.isObject())((com.fasterxml.jackson.databind.node.ObjectNode)item).put("id",Auth.uid());var a=MeetingAnalysis.validate(draft,(String)job.document.get("content"),true);String encoded=json.writeValueAsString(a);
            store.write(c->{revalidate(c,job);execute(c,"UPDATE meeting_runs SET status='ready',analysis=?,model=?,model_revision=?,completed_at=? WHERE id=?",encoded,output.get("model").asText(),output.get("revision").asText(),Auth.now(),job.run);var current=state(c,job.id);boolean keep="user_edited".equals(current.get("provenance"))&&Objects.equals(current.get("source_revision"),job.document.get("revision"));execute(c,"UPDATE meetings SET analysis_status='ready',analysis_error=NULL,source_revision=?,version=version+1,ai_analysis=?,analysis=?,provenance=?,active_run=NULL WHERE document_id=?",job.document.get("revision"),encoded,keep?current.get("analysis"):encoded,keep?"user_edited":"ai",job.id);return null;});
        }catch(Exception e){fail(job,e instanceof ApiError a? a.getMessage():"generation_failed");}
    }
    void fail(Job job,String error){store.write(c->{
        execute(c,"UPDATE meeting_runs SET status='failed',error=?,completed_at=? WHERE id=? AND status IN ('queued','running')",error,Auth.now(),job.run);
        // A failed retry does not revoke an already usable analysis for the same source.
        // The latest run still records its failure, and analysis_error makes it visible in UI.
        execute(c,"UPDATE meetings SET analysis_status=CASE WHEN ai_analysis IS NOT NULL AND source_revision=(SELECT revision FROM documents WHERE id=?) THEN 'ready' ELSE 'failed' END,analysis_error=?,active_run=NULL WHERE document_id=? AND active_run=?",job.id,error,job.id,job.run);
        return null;
    });}
    JsonNode decision(Map<String,Object> m,String item)throws Exception{if(!"ready".equals(m.get("analysis_status")))throw new ApiError(409,"analysis_not_ready");for(var i:analysis(m).get("items"))if(i.get("id").asText().equals(item)&&i.get("type").asText().equals("decision")&&i.get("status").asText().equals("confirmed"))return i;throw new ApiError(422,"confirmed_decision_required");}
    Map<String,Object> link(Connection c,String id,Object user,JsonNode b)throws Exception{
        MeetingAnalysis.fields(b,"target_meeting_id","source_item_id","target_item_id","relation","expected_revision","expected_version","target_expected_revision","target_expected_version","quote","start_offset","end_offset");String target=MeetingAnalysis.text(b,"target_meeting_id",1,100);if(id.equals(target))throw new ApiError(422,"distinct_meetings_required");var d=docs.document(c,id,user,true);var t=docs.document(c,target,user,false);var m=state(c,id);var tm=state(c,target);cas(d,m,MeetingAnalysis.integer(b,"expected_revision",1,Integer.MAX_VALUE),MeetingAnalysis.integer(b,"expected_version",0,Integer.MAX_VALUE));cas(t,tm,MeetingAnalysis.integer(b,"target_expected_revision",1,Integer.MAX_VALUE),MeetingAnalysis.integer(b,"target_expected_version",0,Integer.MAX_VALUE));String si=MeetingAnalysis.text(b,"source_item_id",1,100),ti=MeetingAnalysis.text(b,"target_item_id",1,100);decision(m,si);decision(tm,ti);String relation=MeetingAnalysis.text(b,"relation",1,30);if(!Set.of("related","supersedes").contains(relation))throw new ApiError(422,"invalid_request");MeetingAnalysis.evidence(b,(String)d.get("content"));String link=Auth.uid();execute(c,"INSERT INTO meeting_links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",link,id,target,d.get("revision"),t.get("revision"),m.get("version"),tm.get("version"),si,ti,relation,b.get("quote").asText(),b.get("start_offset").intValue(),b.get("end_offset").intValue(),user,Auth.now());execute(c,"INSERT INTO meeting_link_evidence VALUES (?,?,?)",link,json.writeValueAsString(decision(m,si)),json.writeValueAsString(decision(tm,ti)));return one(c,"SELECT * FROM meeting_links WHERE id=?",link);
    }
    List<Map<String,Object>> links(Connection c,String id,Object user)throws Exception{
        docs.document(c,id,user,false);state(c,id);List<Map<String,Object>> result=new ArrayList<>();for(var l:rows(c,"SELECT l.*,s.title AS source_title,t.title AS target_title FROM meeting_links l JOIN documents s ON s.id=l.source_id JOIN documents t ON t.id=l.target_id WHERE (source_id=? OR target_id=?) ORDER BY created_at,id",id,id))try{var d=docs.document(c,(String)l.get("source_id"),user,false);var t=docs.document(c,(String)l.get("target_id"),user,false);var m=state(c,(String)d.get("id"));var tm=state(c,(String)t.get("id"));if(!Objects.equals(d.get("revision"),l.get("source_revision"))||!Objects.equals(t.get("revision"),l.get("target_revision")))continue;var proof=one(c,"SELECT * FROM meeting_link_evidence WHERE link_id=?",l.get("id"));if(proof==null||!decision(m,(String)l.get("source_item_id")).equals(json.readTree((String)proof.get("source_item")))||!decision(tm,(String)l.get("target_item_id")).equals(json.readTree((String)proof.get("target_item"))))continue;var sourceDate=analysis(m).get("meeting_date");var targetDate=analysis(tm).get("meeting_date");l.put("source_meeting_date",sourceDate.isNull()?null:sourceDate.asText());l.put("target_meeting_date",targetDate.isNull()?null:targetDate.asText());l.put("source_item_text",decision(m,(String)l.get("source_item_id")).get("text").asText());l.put("target_item_text",decision(tm,(String)l.get("target_item_id")).get("text").asText());result.add(l);}catch(ApiError ignored){}result.sort(Comparator.<Map<String,Object>,String>comparing(l->(String)l.get("source_meeting_date"),Comparator.nullsLast(Comparator.naturalOrder())).thenComparing(l->(String)l.get("target_meeting_date"),Comparator.nullsLast(Comparator.naturalOrder())).thenComparing(l->(String)l.get("created_at")));return result;
    }
    List<Map<String,Object>> tasks(Connection c,Object user,String workspace,String assignee,String status)throws Exception{
        if(workspace!=null)docs.membership(c,workspace,user,false);List<Map<String,Object>> result=new ArrayList<>();for(var d:rows(c,"SELECT d.* FROM documents d JOIN meetings mt ON mt.document_id=d.id JOIN memberships mb ON mb.workspace_id=d.workspace_id AND mb.user_id=? WHERE (d.visibility='workspace' OR d.owner_id=?) AND mt.analysis_status='ready' AND mt.source_revision=d.revision ORDER BY d.id",user,user)){
            if(workspace!=null&&!workspace.equals(d.get("workspace_id")))continue;var m=state(c,(String)d.get("id"));for(var item:analysis(m).get("items")){if(!item.get("type").asText().equals("action")||assignee!=null&&!assignee.equals(item.path("assignee").asText())||status!=null&&!status.equals(item.path("status").asText()))continue;Map<String,Object> row=json.convertValue(item,new com.fasterxml.jackson.core.type.TypeReference<>(){});row.put("meeting_id",d.get("id"));row.put("title",d.get("title"));row.put("workspace_id",d.get("workspace_id"));row.put("source_revision",m.get("source_revision"));row.put("version",m.get("version"));result.add(row);}}
        return result;
    }
}
