package io.doctrail;

import com.fasterxml.jackson.databind.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Service;
import java.sql.Connection;
import java.util.*;
import java.util.concurrent.Semaphore;
import static io.doctrail.Store.*;

/** Cross-workspace authorization and metadata filtering happen before any ranking or model call. */
@Service
public class KnowledgeService {
    final Store store;final Auth auth;final DocumentService docs;final MeetingService meetings;final LearnedSearch learned;final InferenceClient inference;final GenerationClient generation;final ObjectMapper json;
    private final Semaphore active=new Semaphore(1);
    KnowledgeService(Store store,Auth auth,DocumentService docs,MeetingService meetings,LearnedSearch learned,InferenceClient inference,GenerationClient generation,ObjectMapper json){this.store=store;this.auth=auth;this.docs=docs;this.meetings=meetings;this.learned=learned;this.inference=inference;this.generation=generation;this.json=json;}
    record Filter(String query,String workspace,String kind,String meeting,String from,String to,String participant,String assignee,String itemType,String method,int limit,String profile){}
    static String optional(JsonNode b,String key,int max){JsonNode v=b.get(key);if(v==null||v.isNull())return null;return MeetingAnalysis.text(b,key,1,max);}
    Filter filter(JsonNode b){
        if(b==null||!b.isObject())throw new ApiError(422,"invalid_request");Set<String> allowed=Set.of("query","workspace_id","kind","meeting_id","date_from","date_to","participant","assignee","item_type","method","limit","expected_embedding_profile");b.fieldNames().forEachRemaining(k->{if(!allowed.contains(k))throw new ApiError(422,"invalid_request");});
        String q=MeetingAnalysis.text(b,"query",1,500);if(Ingest.isBlank(q))throw new ApiError(422,"query_required");String kind=b.path("kind").asText("all"),method=b.path("method").asText("bm25");if(!Set.of("all","meeting","document").contains(kind)||!LearnedSearch.METHODS.contains(method))throw new ApiError(422,"invalid_request");int limit=b.has("limit")?MeetingAnalysis.integer(b,"limit",1,50):10;
        String from=optional(b,"date_from",10),to=optional(b,"date_to",10);if(from!=null)MeetingAnalysis.date(b.get("date_from"));if(to!=null)MeetingAnalysis.date(b.get("date_to"));if(from!=null&&to!=null&&from.compareTo(to)>0)throw new ApiError(422,"invalid_date_range");String type=optional(b,"item_type",30);if(type!=null&&!Set.of("decision","action","unresolved").contains(type))throw new ApiError(422,"invalid_request");
        return new Filter(q,optional(b,"workspace_id",100),kind,optional(b,"meeting_id",100),from,to,optional(b,"participant",200),optional(b,"assignee",200),type,method,limit,optional(b,"expected_embedding_profile",100));
    }
    record Snapshot(Object user,List<Map<String,Object>> memberships,List<Map<String,Object>> corpus){}
    Snapshot snapshot(Connection c,HttpServletRequest request,Filter f)throws Exception{
        Object user=auth.user(c,request).get("id");if(f.workspace!=null)docs.membership(c,f.workspace,user,false);if(f.meeting!=null){var d=docs.document(c,f.meeting,user,false);meetings.state(c,f.meeting);if(f.workspace!=null&&!f.workspace.equals(d.get("workspace_id")))throw new ApiError(404,"meeting_not_found");}
        var memberships=rows(c,"SELECT workspace_id,role FROM memberships WHERE user_id=? ORDER BY workspace_id",user);
        List<Map<String,Object>> corpus=new ArrayList<>();
        for(var d:rows(c,"SELECT d.id AS document_id,d.workspace_id,d.title,d.filename,d.revision,d.owner_id,d.visibility,d.updated_at,mt.analysis_status,mt.source_revision,mt.version AS meeting_version,mt.analysis FROM documents d JOIN memberships mb ON mb.workspace_id=d.workspace_id AND mb.user_id=? LEFT JOIN meetings mt ON mt.document_id=d.id WHERE d.status='ready' AND (d.visibility='workspace' OR d.owner_id=?) ORDER BY d.id",user,user)){
            boolean isMeeting=d.get("analysis_status")!=null;if(f.workspace!=null&&!f.workspace.equals(d.get("workspace_id"))||f.meeting!=null&&!f.meeting.equals(d.get("document_id"))||f.kind.equals("meeting")&&!isMeeting||f.kind.equals("document")&&isMeeting)continue;
            JsonNode a=isMeeting&&"ready".equals(d.get("analysis_status"))&&Objects.equals(d.get("source_revision"),d.get("revision"))?json.readTree((String)d.get("analysis")):null;
            String date=a==null||a.path("meeting_date").isNull()?null:a.path("meeting_date").asText();
            if(f.from!=null&&(date==null||date.compareTo(f.from)<0)||f.to!=null&&(date==null||date.compareTo(f.to)>0))continue;
            if(f.participant!=null&&(a==null||!contains(a.path("participants"),f.participant)))continue;
            if(f.assignee!=null||f.itemType!=null){boolean matched=false;if(a!=null)for(var i:a.path("items"))if((f.assignee==null||f.assignee.equals(i.path("assignee").asText()))&&(f.itemType==null||f.itemType.equals(i.path("type").asText())))matched=true;if(!matched)continue;}
            for(var chunk:rows(c,"SELECT id AS chunk_id,text,page,start_offset,end_offset,ordinal FROM chunks WHERE document_id=? ORDER BY ordinal,id",d.get("document_id"))){var row=new LinkedHashMap<>(d);row.putAll(chunk);row.put("document_kind",isMeeting?"meeting":"document");row.put("meeting_date",date);corpus.add(row);if(corpus.size()>LearnedSearch.MAX_VISIBLE)throw new ApiError(422,"visible_corpus_too_large");}
        }
        return new Snapshot(user,memberships,corpus);
    }
    static boolean contains(JsonNode array,String value){for(var v:array)if(value.equals(v.asText()))return true;return false;}
    static List<Map<String,Object>> clean(List<Map<String,Object>> results){return results.stream().map(row->{Map<String,Object> hit=new LinkedHashMap<>(row);for(String key:List.of("owner_id","visibility","updated_at","ordinal","analysis_status","source_revision","meeting_version","analysis"))hit.remove(key);return hit;}).toList();}
    Map<String,Object> execute(JsonNode b,HttpServletRequest request,boolean answer){
        long started=System.nanoTime();Filter f=filter(b);Snapshot before=store.read(c->snapshot(c,request,f));String token=Auth.token(request);if(f.profile!=null&&!f.profile.equals(inference.embeddingProfile().get("id")))throw new ApiError(409,"embedding_profile_changed");if(!active.tryAcquire())throw new ApiError(503,"inference_busy");
        try{
            if(answer&&f.limit>10)throw new ApiError(422,"answer_context_limit");
            List<Map<String,Object>> ranked;if(f.method.equals("bm25"))ranked=Retrieval.rankChunks(f.query,before.corpus,f.limit);else if(before.corpus.isEmpty())ranked=List.of();else{long deadline=inference.deadline();inference.health(deadline);ranked=learned.rank(f.query,before.corpus,f.limit,f.method,deadline);}
            List<Map<String,Object>> results=clean(ranked);Map<String,Object> response;
            if(!answer){response=new LinkedHashMap<>(Map.of("query",f.query,"method",f.method,"results",results));if(!f.method.equals("bm25"))response.put("embedding_profile",inference.embeddingProfile());}
            else if(results.isEmpty())response=abstain("no_evidence",null);
            else{
                // Ranking may have waited on a model. Do not send a stale authorization snapshot
                // to a second model, even though the final response is also revalidated below.
                store.read(c->{Snapshot current=snapshot(c,request,f);if(!token.equals(Auth.token(request))||!before.equals(current))throw new ApiError(409,"search_context_changed");return null;});
                List<Map<String,Object>> contexts=results.stream().map(row->{Map<String,Object> v=new LinkedHashMap<>();for(String key:List.of("document_id","revision","chunk_id","title","meeting_date","page","start_offset","end_offset","text"))v.put(key,row.get(key));return v;}).toList();
                JsonNode output=generation.call("/answer",Map.of("schema_version",1,"query",f.query,"contexts",contexts));response=validateAnswer(output,contexts);
            }
            if(answer){response.put("query",f.query);response.put("method",f.method);response.put("results",results);response.put("model_called",!results.isEmpty());response.put("elapsed_ms",Math.round((System.nanoTime()-started)/10_000.0)/100.0);}return store.read(c->{Snapshot after=snapshot(c,request,f);if(!token.equals(Auth.token(request))||!before.equals(after))throw new ApiError(409,"search_context_changed");return response;});
        }finally{active.release();}
    }
    static Map<String,Object> abstain(String reason,Object model){var response=new LinkedHashMap<String,Object>();response.put("status","abstained");response.put("reason",reason);response.put("claims",List.of());response.put("model",model);response.put("experimental",true);return response;}
    Map<String,Object> validateAnswer(JsonNode out,List<Map<String,Object>> contexts){
        String state=out.path("status").asText();if(state.equals("abstained")){if(!out.path("claims").isArray()||!out.path("claims").isEmpty())throw new ApiError(503,"generation_invalid_response");String reason=out.path("reason").asText();if(!Set.of("insufficient_evidence","no_evidence","unsupported_question","conflicting_evidence").contains(reason))reason="insufficient_evidence";var response=abstain(reason,out.path("model").asText());response.put("model_revision",out.path("revision").asText());return response;}
        if(!state.equals("answered")||!out.path("claims").isArray()||out.path("claims").isEmpty()||out.path("claims").size()>20)throw new ApiError(503,"generation_invalid_response");
        List<Map<String,Object>> claims=new ArrayList<>();
        try{for(var claim:out.get("claims")){
            MeetingAnalysis.fields(claim,"text","citations");String text=MeetingAnalysis.text(claim,"text",1,3000);MeetingAnalysis.array(claim,"citations",10);MeetingAnalysis.require(!claim.get("citations").isEmpty());List<Map<String,Object>> citations=new ArrayList<>();
            for(var citation:claim.get("citations")){
                MeetingAnalysis.fields(citation,"chunk_id","quote","start_offset","end_offset");String chunk=MeetingAnalysis.text(citation,"chunk_id",1,100);var context=contexts.stream().filter(c->chunk.equals(c.get("chunk_id"))).findFirst().orElseThrow(()->new ApiError(503,"generation_invalid_response"));int start=MeetingAnalysis.integer(citation,"start_offset",0,Integer.MAX_VALUE),end=MeetingAnalysis.integer(citation,"end_offset",1,Integer.MAX_VALUE),base=((Number)context.get("start_offset")).intValue(),bound=((Number)context.get("end_offset")).intValue();String quote=MeetingAnalysis.text(citation,"quote",1,12000),source=(String)context.get("text");MeetingAnalysis.require(start>=base&&end<=bound&&end>start&&quote.equals(source.substring(source.offsetByCodePoints(0,start-base),source.offsetByCodePoints(0,end-base))));var c=new LinkedHashMap<>(context);c.remove("text");c.put("quote",quote);c.put("start_offset",start);c.put("end_offset",end);citations.add(c);
            }
            claims.add(Map.of("text",text,"citations",citations));
        }}catch(RuntimeException e){throw new ApiError(503,"generation_invalid_response");}
        var response=new LinkedHashMap<String,Object>();response.put("status","answered");response.put("reason",null);response.put("claims",claims);response.put("model",out.get("model").asText());response.put("model_revision",out.get("revision").asText());response.put("experimental",true);return response;
    }
}
