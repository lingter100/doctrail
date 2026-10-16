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
        fields(a,"meeting_title","meeting_date","participants","purpose","summary","summary_evidence","metadata_evidence","items");
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
