package io.doctrail;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import java.time.LocalDate;
import java.util.*;

/** Structural and source-span validation only; never a semantic quality certification. */
final class MeetingAnalysis {
    static final Set<String> TYPES=Set.of("topic","proposal","decision","unresolved","action");
    static final Set<String> STATES=Set.of("needs_confirmation","confirmed","todo","doing","done");
    static ObjectNode empty(ObjectMapper json){
        ObjectNode a=json.createObjectNode();a.putNull("meeting_title");a.putNull("meeting_date");a.putArray("participants");a.putNull("purpose");a.put("summary","");a.putArray("summary_evidence");a.putArray("metadata_evidence");a.putArray("items");return a;
    }
    static JsonNode validate(JsonNode a,String content,boolean ai){
        require(a!=null&&a.isObject());
        boolean grounded=a.has("summary_version")||a.has("summary_claims");
        if(grounded){
            fields(a,"meeting_title","meeting_date","participants","purpose","summary","summary_evidence","metadata_evidence","items","summary_version","summary_claims");
            require(integer(a,"summary_version",2,2)==2);
            groundedSummary(a,content,ai);
        }else fields(a,"meeting_title","meeting_date","participants","purpose","summary","summary_evidence","metadata_evidence","items");
        nullable(a,"meeting_title",200);date(a.get("meeting_date"));nullable(a,"purpose",2000);text(a,"summary",0,12000);
        array(a,"participants",100);Set<String> participants=new HashSet<>();for(var p:a.get("participants")){require(p.isTextual()&&!p.asText().isBlank()&&DocumentService.length(p.asText())<=200&&participants.add(p.asText()));}
        array(a,"summary_evidence",100);for(var e:a.get("summary_evidence")){fields(e,"quote","start_offset","end_offset");evidence(e,content);}
        require(a.get("summary").asText().isEmpty()||!a.get("summary_evidence").isEmpty());
        array(a,"metadata_evidence",100);Set<String> evidenced=new HashSet<>();for(var e:a.get("metadata_evidence")){fields(e,"field","quote","start_offset","end_offset");String f=text(e,"field",1,40);require(Set.of("meeting_title","meeting_date","participants","purpose").contains(f));evidence(e,content);evidenced.add(f);}
        if(ai){for(String f:List.of("meeting_title","meeting_date","purpose"))if(!a.get(f).isNull()){require(evidenced.contains(f));require(supported(a,f,a.get(f).asText()));}for(String participant:participants)require(supported(a,"participants",participant));}
        array(a,"items",150);Set<String> ids=new HashSet<>();
        for(var i:a.get("items")){
            fields(i,"id","type","text","quote","start_offset","end_offset","assignee","due_date","priority","status");
            require(ids.add(text(i,"id",1,100)));String type=text(i,"type",1,30),state=text(i,"status",1,40);require(TYPES.contains(type)&&STATES.contains(state));text(i,"text",1,3000);evidence(i,content);nullable(i,"assignee",200);date(i.get("due_date"));nullable(i,"priority",10);require(i.get("priority").isNull()||Set.of("low","medium","high").contains(i.get("priority").asText()));
            if(type.equals("action"))require(Set.of("todo","doing","done","needs_confirmation").contains(state));else {require(Set.of("needs_confirmation","confirmed").contains(state));require(i.get("assignee").isNull()&&i.get("due_date").isNull()&&i.get("priority").isNull());}
            if(ai){require(!state.equals("confirmed")&&!state.equals("doing")&&!state.equals("done"));if(!i.get("assignee").isNull())require(i.get("quote").asText().contains(i.get("assignee").asText()));if(!i.get("due_date").isNull())require(i.get("quote").asText().contains(i.get("due_date").asText()));}
        }
        return a.deepCopy();
    }
    static int summaryVersion(JsonNode a){return a.has("summary_version")?integer(a,"summary_version",2,2):1;}
    private record Span(int start,int end){}
    static void groundedSummary(JsonNode a,String content,boolean ai){
        unicode(content);
        array(a,"summary_claims",6);require(!a.get("summary_claims").isEmpty());
        var flattened=new TreeMap<Span,JsonNode>(Comparator.comparingInt(Span::start).thenComparingInt(Span::end));
        List<String> texts=new ArrayList<>();int total=0,index=0;
        for(var claim:a.get("summary_claims")){
            fields(claim,"id","text","citations");require(integer(claim,"id",0,5)==index++);
            String text=text(claim,"text",1,240);unicode(text);
            require(!blank(text)&&text.codePoints().noneMatch(MeetingAnalysis::lineBreak));
            if(ai)require(text.codePoints().anyMatch(c->c>=0x1100&&c<=0x11ff||c>=0x3131&&c<=0x318e||c>=0xac00&&c<=0xd7a3));
            total+=DocumentService.length(text);require(total<=1200);texts.add(text);
            array(claim,"citations",4);require(!claim.get("citations").isEmpty());Span previous=null;
            for(var citation:claim.get("citations")){
                fields(citation,"quote","start_offset","end_offset");evidence(citation,content);
                String quote=citation.get("quote").asText();unicode(quote);require(!blank(quote));
                Span span=new Span(citation.get("start_offset").intValue(),citation.get("end_offset").intValue());
                require(previous==null||flattened.comparator().compare(previous,span)<0);
                previous=span;flattened.put(span,citation);
            }
        }
        require(a.path("summary").isTextual()&&a.get("summary").asText().equals(String.join("\n",texts)));
        array(a,"summary_evidence",24);require(a.get("summary_evidence").size()==flattened.size());
        int position=0;for(var citation:flattened.values())require(citation.equals(a.get("summary_evidence").get(position++)));
    }
    // Match Python's Unicode scalar, str.strip and splitlines boundaries for v2 only.
    static void unicode(String value){for(int i=0;i<value.length();i++){char c=value.charAt(i);if(Character.isHighSurrogate(c)){require(i+1<value.length()&&Character.isLowSurrogate(value.charAt(++i)));}else require(!Character.isLowSurrogate(c));}}
    static boolean blank(String value){return value.codePoints().allMatch(c->Character.isWhitespace(c)||Character.isSpaceChar(c)||c==0x85);}
    static boolean lineBreak(int c){return c==10||c==13||c==11||c==12||c>=0x1c&&c<=0x1e||c==0x85||c==0x2028||c==0x2029;}
    static boolean supported(JsonNode a,String field,String value){for(var e:a.get("metadata_evidence"))if(field.equals(e.get("field").asText())&&e.get("quote").asText().contains(value))return true;return false;}
    static void evidence(JsonNode e,String content){String quote=text(e,"quote",1,12000);int start=integer(e,"start_offset",0,Integer.MAX_VALUE),end=integer(e,"end_offset",1,Integer.MAX_VALUE);require(end>start&&end<=DocumentService.length(content));require(quote.equals(content.substring(content.offsetByCodePoints(0,start),content.offsetByCodePoints(0,end))));}
    static void fields(JsonNode n,String... fields){require(n!=null&&n.isObject());Set<String> actual=new HashSet<>();n.fieldNames().forEachRemaining(actual::add);require(actual.equals(Set.of(fields)));}
    static String text(JsonNode n,String field,int min,int max){JsonNode v=n.get(field);require(v!=null&&v.isTextual()&&DocumentService.length(v.asText())>=min&&DocumentService.length(v.asText())<=max);return v.asText();}
    static int integer(JsonNode n,String field,int min,int max){JsonNode v=n.get(field);require(v!=null&&v.isIntegralNumber()&&v.canConvertToInt()&&v.intValue()>=min&&v.intValue()<=max);return v.intValue();}
    static void nullable(JsonNode n,String field,int max){JsonNode v=n.get(field);require(v!=null);if(!v.isNull())text(n,field,1,max);}
    static void array(JsonNode n,String f,int max){require(n.path(f).isArray()&&n.get(f).size()<=max);}
    static void date(JsonNode n){require(n!=null);if(n.isNull())return;require(n.isTextual()&&n.asText().matches("\\d{4}-\\d{2}-\\d{2}"));try{LocalDate.parse(n.asText());}catch(Exception e){throw new ApiError(422,"invalid_analysis");}}
    static void require(boolean ok){if(!ok)throw new ApiError(422,"invalid_analysis");}
}
