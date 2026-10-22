package io.doctrail;

import com.fasterxml.jackson.databind.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

/** Separate local generation boundary; no model downloads or subprocesses in Java. */
@Component
public class GenerationClient {
    private final URI base; private final String token; private final long timeout; private final ObjectMapper json;
    private final HttpClient http=HttpClient.newBuilder().proxy(ProxySelector.of(null)).connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER).build();
    public GenerationClient(@Value("${doctrail.generation-url:}") String url,@Value("${doctrail.generation-token:}") String token,@Value("${doctrail.generation-timeout-ms:120000}") long timeout,ObjectMapper json){
        this.token=token;this.timeout=timeout;this.json=json.copy().enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION).enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
        if(timeout<1||timeout>120000)throw new IllegalArgumentException("invalid_generation_configuration");
        if(url.isBlank()){base=null;return;}
        try{base=URI.create(url);if(!"http".equals(base.getScheme())||!"127.0.0.1".equals(base.getHost())||base.getPort()<1||base.getPort()>65535||base.getUserInfo()!=null||base.getQuery()!=null||base.getFragment()!=null||!(base.getPath().isEmpty()||base.getPath().equals("/"))||token.length()<32||token.chars().anyMatch(c->c<33||c>126))throw new IllegalArgumentException();}catch(Exception e){throw new IllegalArgumentException("invalid_generation_configuration");}
    }
    boolean enabled(){return base!=null;}
    JsonNode call(String path,Object body){
        return call(path,body,null);
    }
    JsonNode call(String path,Object body,AnswerDeadline budget){
        if(budget!=null&&!path.equals("/answer"))throw new IllegalArgumentException("answer_budget_path_required");
        if(budget!=null)budget.check();
        if(base==null)throw new ApiError(503,"generation_disabled");
        CompletableFuture<HttpResponse<byte[]>> pending=null;
        try{
            byte[] payload=json.writeValueAsBytes(body);
            long remaining=TimeUnit.MILLISECONDS.toNanos(timeout);
            if(budget!=null)remaining=Math.min(remaining,budget.remainingNanos());
            long transportDeadline=System.nanoTime()+remaining;
            var builder=HttpRequest.newBuilder(base.resolve(path)).timeout(Duration.ofNanos(remaining)).header("Authorization","Bearer "+token).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofByteArray(payload));
            if(budget!=null){
                long millis=TimeUnit.NANOSECONDS.toMillis(Math.min(remaining,budget.remainingNanos()));
                if(millis<1)throw new ApiError(504,"generation_timeout");
                builder.header("X-DocTrail-Request-Budget-Ms",Long.toString(Math.min(AnswerDeadline.MAX_MILLIS,millis)));
                budget.check();
            }
            pending=http.sendAsync(builder.build(),info->new InferenceClient.BoundedBody());
            long wait=transportDeadline-System.nanoTime();
            if(budget!=null)wait=Math.min(wait,budget.remainingNanos());
            if(wait<=0)throw new ApiError(504,"generation_timeout");
            var response=pending.get(wait,TimeUnit.NANOSECONDS);
            if(budget!=null)budget.check();
            if(response.statusCode()!=200)throw workerError(response.statusCode(),response.body());
            JsonNode value=json.readTree(response.body());
            if(value==null||!value.isObject()||!value.path("schema_version").isIntegralNumber()||!value.path("schema_version").canConvertToInt()||value.path("schema_version").intValue()!=1||!value.path("model").isTextual()||value.path("model").asText().isBlank()||!value.path("revision").isTextual()||value.path("revision").asText().isBlank())throw new ApiError(503,"generation_invalid_response");
            if(budget!=null)budget.check();
            return value;
        }catch(TimeoutException e){throw new ApiError(504,"generation_timeout");}catch(ExecutionException e){if(e.getCause() instanceof HttpTimeoutException)throw new ApiError(504,"generation_timeout");throw new ApiError(503,"generation_unavailable");}catch(InterruptedException e){Thread.currentThread().interrupt();throw new ApiError(503,"generation_unavailable");}catch(ApiError e){throw e;}catch(com.fasterxml.jackson.core.JsonProcessingException e){throw new ApiError(503,"generation_invalid_response");}catch(Exception e){throw new ApiError(503,"generation_unavailable");}
        finally{if(pending!=null&&!pending.isDone())pending.cancel(true);}
    }
    private ApiError workerError(int status,byte[] body){
        try{String code=json.readTree(body).path("error").asText();
            if(status==413&&code.equals("body_too_large"))return new ApiError(413,"generation_input_limit");
            if(status==422&&Set.of("invalid_request","generation_input_limit","generation_partition_limit","context_budget_exceeded").contains(code))return new ApiError(422,code.equals("invalid_request")?"generation_invalid_request":code);
            if(status==503&&Set.of("model_busy","generation_failed","generation_cleanup_failed").contains(code))return new ApiError(503,code.equals("model_busy")?"generation_busy":code);
            if(status==504&&code.equals("generation_deadline_exceeded"))return new ApiError(504,"generation_timeout");
            if(status==502&&Set.of("generation_invalid_json","generation_invalid_schema","generation_invalid_evidence","generation_duplicate_item","generation_unsupported_field","generation_unsupported_metadata","generation_conflicting_metadata","generation_output_truncated","generation_language_mismatch","generation_summary_insufficient","generation_summary_review_rejected").contains(code))return new ApiError(503,code);
        }catch(Exception ignored){}return new ApiError(503,"generation_unavailable");
    }
}
