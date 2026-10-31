package io.doctrail;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.ProxySelector;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.Flow;

/** Local model-only boundary. No retries, redirects, or lexical fallback. */
@Component
public class InferenceClient {
    static final String EMBEDDING="intfloat/multilingual-e5-small", EMBEDDING_REVISION="614241f622f53c4eeff9890bdc4f31cfecc418b3";
    static final String TERMINAL_EMBEDDING="doctrail/multilingual-e5-small-m4-terminal-v1", TERMINAL_REVISION="62e530d3094e98b336d039f10956c8e0e2a39d24d66b07818e92a46f0aac10fb";
    private final Map<String,String> embeddingProfile;
    static final String RERANKER="BAAI/bge-reranker-v2-m3", RERANKER_REVISION="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e";
    static final int DIMENSION=384, MAX_RESPONSE=4*1024*1024;
    private final URI base;
    private final String token;
    private final ObjectMapper json;
    private final HttpClient http=HttpClient.newBuilder().proxy(ProxySelector.of(null)).connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER).build();
    final long timeoutMillis;

    InferenceClient(String url,String token,long timeoutMillis,ObjectMapper json){this(url,token,timeoutMillis,"base",json);}
    @Autowired
    public InferenceClient(@Value("${doctrail.inference-url:}") String url,
            @Value("${doctrail.inference-token:}") String token,
            @Value("${doctrail.inference-timeout-ms:120000}") long timeoutMillis,
            @Value("${doctrail.embedding-profile:base}") String profile,ObjectMapper json) {
        embeddingProfile=switch(profile){
            case "base"->Map.of("id","base","model",EMBEDDING,"revision",EMBEDDING_REVISION);
            case "m4-terminal-v1"->Map.of("id","m4-terminal-v1","model",TERMINAL_EMBEDDING,"revision",TERMINAL_REVISION);
            default->throw new IllegalArgumentException("invalid_embedding_profile");
        };
        this.json=json; this.token=token; this.timeoutMillis=timeoutMillis;
        if(timeoutMillis<1||timeoutMillis>120000)throw new IllegalArgumentException("invalid_inference_configuration");
        if(url.isBlank()){base=null;return;}
        try {
            base=URI.create(url);
            if(!"http".equals(base.getScheme())||!"127.0.0.1".equals(base.getHost())||base.getPort()<1||base.getPort()>65535
                    ||base.getUserInfo()!=null||base.getQuery()!=null||base.getFragment()!=null
                    ||!(base.getPath().isEmpty()||base.getPath().equals("/"))
                    ||token.length()<32||token.chars().anyMatch(c->c<33||c>126))throw new IllegalArgumentException();
        } catch(IllegalArgumentException e){throw new IllegalArgumentException("invalid_inference_configuration");}
    }
    boolean enabled(){return base!=null;}
    Map<String,String> embeddingProfile(){return embeddingProfile;}
    long deadline(){return System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(timeoutMillis);}
    void health(long deadline){
        JsonNode root=call("/health",null,deadline);
        require(integer(root,"schema_version",1)&&"ready".equals(root.path("status").asText()));
        model(root.path("embedding"),embeddingProfile.get("model"),embeddingProfile.get("revision"));
        model(root.path("reranker"),RERANKER,RERANKER_REVISION);
        require(integer(root.path("embedding"),"dimension",DIMENSION)&&integer(root.path("embedding"),"max_length",512)
                &&integer(root.path("reranker"),"max_length",512)&&integer(root.path("limits"),"max_embed_items",64)&&integer(root.path("limits"),"max_rerank_items",50));
    }
    private static boolean integer(JsonNode root,String key,int value){return root.path(key).isIntegralNumber()&&root.path(key).canConvertToInt()&&root.path(key).asInt()==value;}
    Map<String,double[]> embed(String kind,List<Map<String,String>> items,long deadline){
        JsonNode root=call("/embed",Map.of("schema_version",1,"kind",kind,"items",items),deadline);
        validate(root,embeddingProfile.get("model"),embeddingProfile.get("revision"),items);
        require(integer(root,"dimension",DIMENSION));
        Map<String,double[]> result=new HashMap<>();
        for(JsonNode item:root.path("items")){
            JsonNode vector=item.path("vector");require(vector.isArray()&&vector.size()==DIMENSION);
            double[] values=new double[DIMENSION]; double norm=0;
            for(int i=0;i<DIMENSION;i++){require(vector.get(i).isNumber());values[i]=vector.get(i).asDouble();require(Double.isFinite(values[i]));norm+=values[i]*values[i];}
            require(Double.isFinite(norm)&&norm>0);
            double magnitude=Math.sqrt(norm);for(int i=0;i<DIMENSION;i++)values[i]/=magnitude;
            result.put(item.path("id").asText(),values);
        }
        return result;
    }
    Map<String,Double> rerank(String query,List<Map<String,String>> items,long deadline){
        JsonNode root=call("/rerank",Map.of("schema_version",1,"query",query,"items",items),deadline);
        validate(root,RERANKER,RERANKER_REVISION,items);
        Map<String,Double> result=new HashMap<>();
        for(JsonNode item:root.path("items")){require(item.path("score").isNumber());double value=item.path("score").asDouble();require(Double.isFinite(value));result.put(item.path("id").asText(),value);}
        return result;
    }
    private void validate(JsonNode root,String model,String revision,List<Map<String,String>> items){
        require(integer(root,"schema_version",1));model(root,model,revision);
        require(root.path("items").isArray()&&root.path("items").size()==items.size());
        Set<String> expected=new HashSet<>();for(var item:items)expected.add(item.get("id"));
        for(JsonNode item:root.path("items"))require(item.path("id").isTextual()&&expected.remove(item.path("id").asText()));
        require(expected.isEmpty());
    }
    private static void model(JsonNode root,String model,String revision){require(model.equals(root.path("model").asText())&&revision.equals(root.path("revision").asText()));}
    private static void require(boolean condition){if(!condition)throw new ApiError(503,"inference_invalid_response");}
    private JsonNode call(String path,Object payload,long deadline){
        if(!enabled())throw new ApiError(503,"inference_disabled");
        long remaining=deadline-System.nanoTime();if(remaining<=0)throw new ApiError(504,"inference_timeout");
        CompletableFuture<HttpResponse<byte[]>> pending=null;
        try{
            var builder=HttpRequest.newBuilder(base.resolve(path)).timeout(Duration.ofNanos(remaining)).header("Authorization","Bearer "+token).header("Accept","application/json");
            if(payload==null)builder.GET();else builder.header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofByteArray(json.writeValueAsBytes(payload)));
            pending=http.sendAsync(builder.build(),info->new BoundedBody());
            HttpResponse<byte[]> response=pending.get(Math.max(1,deadline-System.nanoTime()),TimeUnit.NANOSECONDS);
            if(response.statusCode()!=200)throw workerError(response.statusCode(),response.body());
            JsonNode root=json.readTree(response.body());require(root!=null&&root.isObject());return root;
        }catch(TimeoutException e){throw new ApiError(504,"inference_timeout");}
        catch(InterruptedException e){Thread.currentThread().interrupt();throw new ApiError(503,"inference_unavailable");}
        catch(ExecutionException e){if(e.getCause() instanceof HttpTimeoutException)throw new ApiError(504,"inference_timeout");throw new ApiError(503,"inference_unavailable");}
        catch(ApiError e){throw e;}
        catch(Exception e){throw new ApiError(503,"inference_invalid_response");}
        finally{if(pending!=null&&!pending.isDone())pending.cancel(true);}
    }
    /** Translate only documented safe failures; upstream text and auth failures stay private. */
    private ApiError workerError(int status,byte[] body){
        try{
            JsonNode error=json.readTree(body);
            String code=error!=null&&error.isObject()&&error.path("error").isTextual()?error.path("error").asText():"";
            if(status==422&&code.equals("query_too_long"))return new ApiError(422,"query_too_long");
            if(status==503&&code.equals("model_busy"))return new ApiError(503,"inference_busy");
        }catch(Exception ignored){/* Malformed error bodies never escape or become browser auth errors. */}
        return new ApiError(503,"inference_unavailable");
    }
    static final class BoundedBody implements HttpResponse.BodySubscriber<byte[]> {
        final CompletableFuture<byte[]> result=new CompletableFuture<>();final ByteArrayOutputStream bytes=new ByteArrayOutputStream();Flow.Subscription subscription;
        public CompletionStage<byte[]> getBody(){return result;}
        public void onSubscribe(Flow.Subscription subscription){this.subscription=subscription;subscription.request(1);}
        public void onNext(List<ByteBuffer> buffers){
            for(ByteBuffer buffer:buffers){if(buffer.remaining()>MAX_RESPONSE-bytes.size()){subscription.cancel();result.completeExceptionally(new IllegalArgumentException("response_too_large"));return;}byte[] next=new byte[buffer.remaining()];buffer.get(next);bytes.writeBytes(next);}
            subscription.request(1);
        }
        public void onError(Throwable error){result.completeExceptionally(error);}
        public void onComplete(){result.complete(bytes.toByteArray());}
    }
}
