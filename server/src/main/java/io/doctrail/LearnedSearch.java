package io.doctrail;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Service;
import java.sql.Connection;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.Semaphore;
import static io.doctrail.Store.*;

/** Java owns authorization, revision consistency, corpus selection and ranking. */
@Service
public class LearnedSearch {
    static final List<String> METHODS=List.of("bm25","dense","hybrid","hybrid_rerank");
    static final int MAX_VISIBLE=4096;
    private final Store store;private final Auth auth;private final DocumentService docs;private final InferenceClient inference;
    private final Semaphore activeSearch=new Semaphore(1);
    LearnedSearch(Store store,Auth auth,DocumentService docs,InferenceClient inference){this.store=store;this.auth=auth;this.docs=docs;this.inference=inference;}
    Map<String,Object> capabilities(HttpServletRequest request){
        store.read(c->auth.user(c,request));
        String status=inference.enabled()?"ready":"disabled";
        if(inference.enabled())try{inference.health(System.nanoTime()+TimeUnit.SECONDS.toNanos(2));}catch(ApiError e){status="unavailable";}
        return Map.of("default_method","bm25","model_enabled",inference.enabled(),"status",status,"methods",METHODS,"available_methods",status.equals("ready")?METHODS:List.of("bm25"),"embedding_profile",inference.embeddingProfile());
    }
    private record Snapshot(Object user,Map<String,Object> membership,List<Map<String,Object>> rows){}
    private List<Map<String,Object>> visible(Connection c,String workspace,Object user)throws Exception{
        return rows(c,"SELECT d.id AS document_id,d.title,d.filename,d.revision,d.owner_id,d.visibility,d.updated_at,c.id AS chunk_id,c.text,c.page,c.start_offset,c.end_offset,c.ordinal FROM chunks c JOIN documents d ON c.document_id=d.id WHERE d.workspace_id=? AND d.status='ready' AND (d.visibility='workspace' OR d.owner_id=?) ORDER BY d.id,c.ordinal,c.id LIMIT 4097",workspace,user);
    }
    Map<String,Object> search(String workspace,String query,int limit,String method,HttpServletRequest request){
        return search(workspace,query,limit,method,null,request);
    }
    Map<String,Object> search(String workspace,String query,int limit,String method,String expectedProfile,HttpServletRequest request){
        // Authenticate before reporting local admission status. Never queue unbounded model work.
        store.read(c->{Object user=auth.user(c,request).get("id");docs.membership(c,workspace,user,false);return null;});
        if(expectedProfile!=null&&!expectedProfile.equals(inference.embeddingProfile().get("id")))throw new ApiError(409,"embedding_profile_changed");
        if(!activeSearch.tryAcquire())throw new ApiError(503,"inference_busy");
        try{return searchAdmitted(workspace,query,limit,method,request);}finally{activeSearch.release();}
    }
    private Map<String,Object> searchAdmitted(String workspace,String query,int limit,String method,HttpServletRequest request){
        long started=System.nanoTime(),deadline=inference.deadline();
        String token=Auth.token(request);
        Snapshot snapshot=store.read(c->{
            Object user=auth.user(c,request).get("id");docs.membership(c,workspace,user,false);
            var member=one(c,"SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",workspace,user);
            var visible=visible(c,workspace,user);if(visible.size()>MAX_VISIBLE)throw new ApiError(422,"visible_corpus_too_large");
            return new Snapshot(user,member,visible);
        });
        inference.health(deadline);
        List<Map<String,Object>> results=rank(query,snapshot.rows,limit,method,deadline);
        return store.write(c->{
            Object user=auth.user(c,request).get("id");
            if(!token.equals(Auth.token(request))||!snapshot.user.equals(user))throw new ApiError(401,"authentication_required");
            var member=one(c,"SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",workspace,user);
            if(!snapshot.membership.equals(member)||!snapshot.rows.equals(visible(c,workspace,user)))throw new ApiError(409,"search_context_changed");
            String searchId=Auth.uid();
            execute(c,"INSERT INTO searches VALUES (?,?,?,?,?)",searchId,workspace,user,query,Auth.now());
            execute(c,"INSERT INTO search_metadata VALUES (?,?)",searchId,method);
            var profile=inference.embeddingProfile();
            execute(c,"INSERT INTO search_model_metadata VALUES (?,?,?,?)",searchId,profile.get("id"),profile.get("model"),profile.get("revision"));
            for(var result:results)execute(c,"INSERT INTO search_results VALUES (?,?,?,?)",searchId,result.get("document_id"),result.get("chunk_id"),result.get("revision"));
            Map<String,Object> response=new LinkedHashMap<>(Map.of("query",query,"method",method,"elapsed_ms",Math.round((System.nanoTime()-started)/10_000.0)/100.0,"search_id",searchId,"results",results));
            response.put("embedding_profile",profile);
            if(method.equals("hybrid_rerank"))response.put("candidate_policy","balanced_depth_rrf50_v1");
            return response;
        });
    }
    List<Map<String,Object>> rank(String query,List<Map<String,Object>> rows,int limit,String method,long deadline){
        if(rows.isEmpty())return List.of();
        var queryVector=inference.embed("query",List.of(Map.of("id","query","text",query)),deadline).get("query");
        Map<String,Double> scores=new HashMap<>();
        for(int start=0;start<rows.size();start+=64){
            var batch=rows.subList(start,Math.min(rows.size(),start+64));
            var vectors=inference.embed("passage",items(batch),deadline);
            for(var row:batch){String id=(String)row.get("chunk_id");double score=0;double[] vector=vectors.get(id);for(int i=0;i<queryVector.length;i++)score+=queryVector[i]*vector[i];scores.put(id,Math.max(-1,Math.min(1,score)));}
        }
        List<Map<String,Object>> dense=score(rows,scores,50);
        if(method.equals("dense"))return clean(dense.subList(0,Math.min(limit,dense.size())));
        var bm25=Retrieval.rankChunks(query,rows,50);
        var fused=fuse(bm25,dense,rows);
        if(method.equals("hybrid"))return clean(fused.subList(0,Math.min(limit,fused.size())));
        var selected=balanced(bm25,dense,fused);
        var reranked=rerankScores(selected,inference.rerank(query,items(selected),deadline),limit);
        return clean(reranked);
    }
    static List<Map<String,String>> items(List<Map<String,Object>> rows){return rows.stream().map(row->Map.of("id",(String)row.get("chunk_id"),"text",(String)row.get("text"))).toList();}
    /** Stable raw-score ties retain the selected full-branch RRF input order. */
    static List<Map<String,Object>> rerankScores(List<Map<String,Object>> selected,Map<String,Double> scores,int limit){
        List<Map<String,Object>> result=new ArrayList<>();
        for(var row:selected){var hit=new LinkedHashMap<>(row);hit.put("score",scores.get(row.get("chunk_id")));result.add(hit);}
        result.sort(Comparator.comparingDouble(row->-((Number)row.get("score")).doubleValue()));
        return new ArrayList<>(result.subList(0,Math.min(limit,result.size())));
    }
    static final Comparator<Map<String,Object>> TIES=Comparator.<Map<String,Object>,String>comparing(row->(String)row.get("document_id"),Retrieval.CODE_POINT_ORDER)
            .thenComparingInt(row->((Number)row.get("ordinal")).intValue()).thenComparing(row->(String)row.get("chunk_id"),Retrieval.CODE_POINT_ORDER);
    static List<Map<String,Object>> score(List<Map<String,Object>> rows,Map<String,Double> scores,int limit){
        List<Map<String,Object>> result=new ArrayList<>();
        for(var row:rows)if(scores.containsKey(row.get("chunk_id"))){var hit=new LinkedHashMap<>(row);hit.put("score",scores.get(row.get("chunk_id")));result.add(hit);}
        result.sort(Comparator.<Map<String,Object>>comparingDouble(row->-((Number)row.get("score")).doubleValue()).thenComparing(TIES));
        return new ArrayList<>(result.subList(0,Math.min(limit,result.size())));
    }
    static List<Map<String,Object>> fuse(List<Map<String,Object>> bm25,List<Map<String,Object>> dense,List<Map<String,Object>> corpus){
        Map<String,Double> scores=new HashMap<>();
        for(var branch:List.of(bm25,dense))for(int i=0;i<branch.size();i++)scores.merge((String)branch.get(i).get("chunk_id"),1.0/(60+i+1),Double::sum);
        return score(corpus,scores,100);
    }
    static List<Map<String,Object>> balanced(List<Map<String,Object>> bm25,List<Map<String,Object>> dense,List<Map<String,Object>> fused){
        Set<Object> selected=new HashSet<>();int target=Math.min(50,fused.size());
        for(int i=0;i<Math.max(bm25.size(),dense.size())&&selected.size()<target;i++)for(var branch:List.of(bm25,dense))if(i<branch.size()&&selected.size()<target)selected.add(branch.get(i).get("chunk_id"));
        return fused.stream().filter(row->selected.contains(row.get("chunk_id"))).toList();
    }
    private static List<Map<String,Object>> clean(List<Map<String,Object>> rows){
        return rows.stream().map(row->{Map<String,Object> hit=new LinkedHashMap<>(row);for(String field:List.of("owner_id","visibility","updated_at","ordinal"))hit.remove(field);return hit;}).toList();
    }
}
