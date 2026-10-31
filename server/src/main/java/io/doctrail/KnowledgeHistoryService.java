package io.doctrail;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Connection;
import java.util.*;
import static io.doctrail.Store.*;

/** Personal completion records retain evidence identities, never answer or source bodies. */
public class KnowledgeHistoryService {
    final Store store; final Auth auth; final DocumentService docs; final MeetingService meetings; final ObjectMapper json;
    KnowledgeHistoryService(Store store,Auth auth,DocumentService docs,MeetingService meetings,ObjectMapper json){
        this.store=store;this.auth=auth;this.docs=docs;this.meetings=meetings;this.json=json;
    }
    Map<String,Object> filters(KnowledgeService.Filter f){
        var values=new LinkedHashMap<String,Object>();
        values.put("meeting_id",f.meeting());values.put("date_from",f.from());values.put("date_to",f.to());
        values.put("participant",f.participant());values.put("assignee",f.assignee());values.put("item_type",f.itemType());values.put("limit",f.limit());
        return values;
    }
    void save(Connection c,Object user,KnowledgeService.Filter f,boolean answer,Map<String,Object> response,
              List<Map<String,Object>> results,Map<String,String> embeddingProfile)throws Exception{
        String id=Auth.uid();boolean called=answer&&Boolean.TRUE.equals(response.get("model_called"));
        Object model=called?Map.of("model",response.get("model"),"revision",response.get("model_revision")):null;
        execute(c,"INSERT INTO knowledge_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",id,user,answer?"answer":"search",f.query(),f.workspace(),f.kind(),
                json.writeValueAsString(filters(f)),f.method(),embeddingProfile==null?null:json.writeValueAsString(embeddingProfile),
                model==null?null:json.writeValueAsString(model),answer?response.get("status"):"searched",answer?response.get("reason"):null,called?1:0,Auth.now());
        for(var result:results){
            String resultId=Auth.uid();
            execute(c,"INSERT INTO knowledge_history_results VALUES (?,?,?,?,?,?,?,?)",resultId,id,result.get("document_id"),result.get("revision"),
                    result.get("chunk_id"),result.get("start_offset"),result.get("end_offset"),Auth.hash((String)result.get("text")));
            result.put("result_id",resultId);
        }
        response.put("history_id",id);
    }
    boolean scopeAccessible(Connection c,Map<String,Object> history,Object user)throws Exception{
        try{
            if(history.get("workspace_id")!=null)docs.membership(c,(String)history.get("workspace_id"),user,false);
            JsonNode filters=json.readTree((String)history.get("filters_json"));
            if(!filters.path("meeting_id").isNull()&&!filters.path("meeting_id").isMissingNode()){
                String id=filters.path("meeting_id").asText();var document=docs.document(c,id,user,false);meetings.state(c,id);
                if(history.get("workspace_id")!=null&&!history.get("workspace_id").equals(document.get("workspace_id")))return false;
            }
            return true;
        }catch(ApiError e){if(e.status==404)return false;throw e;}
    }
    // A missing/inaccessible document is hidden; an accessible but changed identity is stale.
    boolean current(Connection c,Map<String,Object> result,Object user)throws Exception{
        var document=docs.document(c,(String)result.get("document_id"),user,false);
        if(!"ready".equals(document.get("status"))||!Objects.equals(document.get("revision"),result.get("revision")))return false;
        var chunk=one(c,"SELECT * FROM chunks WHERE id=? AND document_id=?",result.get("chunk_id"),result.get("document_id"));
        return chunk!=null&&Objects.equals(chunk.get("start_offset"),result.get("start_offset"))
                &&Objects.equals(chunk.get("end_offset"),result.get("end_offset"))&&Auth.hash((String)chunk.get("text")).equals(result.get("evidence_sha256"));
    }
    Map<String,Object> list(HttpServletRequest request){return store.read(c->{
        Object user=auth.user(c,request).get("id");List<Map<String,Object>> items=new ArrayList<>();
        for(var history:rows(c,"SELECT * FROM knowledge_history WHERE user_id=? ORDER BY created_at DESC,id DESC",user)){
            if(!scopeAccessible(c,history,user))continue;
            int count=0;
            for(var result:rows(c,"SELECT * FROM knowledge_history_results WHERE history_id=?",history.get("id")))try{
                if(current(c,result,user))count++;
            }catch(ApiError e){if(e.status!=404)throw e;}
            var item=new LinkedHashMap<>(history);item.remove("user_id");
            item.put("filters",json.readTree((String)item.remove("filters_json")));
            for(String key:List.of("embedding_profile","generation_model")){String value=(String)item.remove(key+"_json");item.put(key,value==null?null:json.readTree(value));}
            item.put("model_called",((Number)item.get("model_called")).intValue()!=0);item.put("result_count",count);items.add(item);
            if(items.size()==100)break;
        }
        return Map.of("items",items);
    });}
    Map<String,Object> feedback(String id,JsonNode body,HttpServletRequest request){
        if(body==null||!body.isObject()||body.size()!=2||!body.has("result_id")||!body.path("relevant").isBoolean())throw new ApiError(422,"invalid_request");
        String resultId=KnowledgeService.optional(body,"result_id",100);if(resultId==null)throw new ApiError(422,"invalid_request");
        return store.write(c->{
            Object user=auth.user(c,request).get("id");
            var history=one(c,"SELECT * FROM knowledge_history WHERE id=? AND user_id=?",id,user);
            if(history==null||!scopeAccessible(c,history,user))throw new ApiError(404,"knowledge_result_not_found");
            var result=one(c,"SELECT * FROM knowledge_history_results WHERE id=? AND history_id=?",resultId,id);
            if(result==null)throw new ApiError(404,"knowledge_result_not_found");
            boolean valid;
            try{valid=current(c,result,user);}catch(ApiError e){if(e.status==404)throw new ApiError(404,"knowledge_result_not_found");throw e;}
            if(!valid)throw new ApiError(409,"knowledge_result_stale");
            execute(c,"INSERT INTO knowledge_feedback VALUES (?,?,?) ON CONFLICT(result_id) DO UPDATE SET relevant=excluded.relevant,updated_at=excluded.updated_at",resultId,body.get("relevant").booleanValue()?1:0,Auth.now());
            return Map.of("ok",true);
        });
    }
}
