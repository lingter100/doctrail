package io.doctrail;

import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.assertj.core.api.Assertions.*;

class AnswerContextSelectorTest {
    static Map<String,Object> row(String id,int ordinal) {
        var row=new LinkedHashMap<String,Object>();
        row.put("document_id","doc");row.put("revision",1);row.put("chunk_id",id);
        row.put("title","Synthetic");row.put("meeting_date",null);row.put("page",1);
        row.put("start_offset",ordinal*2);row.put("end_offset",ordinal*2+2);
        row.put("text","😀a");row.put("ordinal",ordinal);return row;
    }
    static List<Object> ids(List<Map<String,Object>> rows){return rows.stream().map(r->r.get("chunk_id")).toList();}

    @Test void preservesAnchorsThenOriginalAnchorNeighborOrderWithoutRecursion() {
        List<Map<String,Object>> corpus=new ArrayList<>();for(int i=0;i<7;i++)corpus.add(row("c"+i,i));
        var ranked=List.of(new LinkedHashMap<>(corpus.get(2)),new LinkedHashMap<>(corpus.get(4)));
        ranked.forEach(r->r.remove("ordinal"));
        assertThat(ids(AnswerContextSelector.select(corpus,new ArrayList<>(ranked))))
                .containsExactly("c2","c4","c1","c3","c5");
        assertThat(corpus.get(2)).containsEntry("ordinal",2);
    }
    @Test void fullCapKeepsOriginalOrderAndUnderfilledExpansionStopsAtTen() {
        List<Map<String,Object>> corpus=new ArrayList<>();for(int i=0;i<14;i++)corpus.add(row("c"+i,i));
        var ten=new ArrayList<>(corpus.subList(3,13));Collections.reverse(ten);
        assertThat(ids(AnswerContextSelector.select(corpus,ten))).isEqualTo(ids(ten));
        var nine=new ArrayList<>(corpus.subList(2,11));
        assertThat(ids(AnswerContextSelector.select(corpus,nine))).containsExactly(
                "c2","c3","c4","c5","c6","c7","c8","c9","c10","c1");
    }
    @Test void skipsMissingOrdinalAndOtherDocumentRevisionOrPage() {
        var anchor=row("anchor",0);var gap=row("gap",2);
        var otherDoc=row("otherDoc",1);otherDoc.put("document_id","other");
        var otherRevision=row("otherRevision",1);otherRevision.put("revision",2);
        var otherPage=row("otherPage",1);otherPage.put("page",2);
        assertThat(ids(AnswerContextSelector.select(List.of(anchor,gap,otherDoc,otherRevision,otherPage),List.of(anchor))))
                .containsExactly("anchor");
    }
    @ParameterizedTest @ValueSource(strings={"text","start_offset","document_id","revision","page","ordinal","chunk_id"})
    void changedOrUnauthorizedAnchorCannotBeSubstituted(String field) {
        var canonical=row("id",1);var forged=new LinkedHashMap<>(canonical);
        forged.put(field,switch(field){case "text"->"changed";case "document_id","chunk_id"->"unknown";default->99;});
        assertThatThrownBy(()->AnswerContextSelector.select(List.of(canonical),List.of(forged)))
                .isInstanceOf(ApiError.class).hasMessage("search_context_changed");
    }
    @Test void duplicateIdentityOrOrdinalAndMalformedCandidateFailClosed() {
        var anchor=row("a",1);var neighbor=row("b",2);
        assertThatThrownBy(()->AnswerContextSelector.select(List.of(anchor,new LinkedHashMap<>(anchor)),List.of(anchor)))
                .isInstanceOf(ApiError.class);
        var ambiguous=row("different-id",1);
        assertThatThrownBy(()->AnswerContextSelector.select(List.of(anchor,ambiguous),List.of(anchor)))
                .isInstanceOf(ApiError.class);
        neighbor.put("end_offset",999);
        assertThatThrownBy(()->AnswerContextSelector.select(List.of(anchor,neighbor),List.of(anchor)))
                .isInstanceOf(ApiError.class);
    }
}
