package io.doctrail;
import org.springframework.stereotype.Service;
import java.sql.Connection;
import java.util.*;
import static io.doctrail.Store.*;
@Service public class DocumentService {
    String membership(Connection c,String workspace,Object user,boolean owner) throws Exception {
        Map<String,Object> row=one(c,"SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",workspace,user);
        if(row==null) throw new ApiError(404,"workspace_not_found");
        if(owner&&!"owner".equals(row.get("role"))) throw new ApiError(403,"workspace_owner_required");
        return (String)row.get("role");
    }
    Map<String,Object> document(Connection c,String id,Object user,boolean owner) throws Exception {
        Map<String,Object> row=one(c,"SELECT d.* FROM documents d JOIN memberships m ON m.workspace_id=d.workspace_id WHERE d.id=? AND m.user_id=? AND (d.visibility='workspace' OR d.owner_id=?)",id,user,user);
        if(row==null) throw new ApiError(404,"document_not_found");
        if(owner&&!user.equals(row.get("owner_id"))) throw new ApiError(403,"document_owner_required");
        return row;
    }
    List<Map<String,Object>> workspaces(Connection c,Object user) throws Exception {
        return rows(c,"SELECT w.id,w.name,m.role FROM workspaces w JOIN memberships m ON w.id=m.workspace_id WHERE m.user_id=? ORDER BY w.name,w.id",user);
    }
    Map<String,Object> serialize(Connection c,Map<String,Object> row,boolean detail) throws Exception {
        Map<String,Object> result=new LinkedHashMap<>(row);
        // Keep the established ordinary-document DTO byte-for-byte compatible.
        // Only meeting documents need the additive marker for read-only source UI.
        if(one(c,"SELECT document_id FROM meetings WHERE document_id=?",row.get("id"))!=null)result.put("document_kind","meeting");
        result.remove("source");
        result.remove("source_kind");
        Object content=result.remove("content");
        List<Map<String,Object>> chunks=rows(c,"SELECT id,text,page,start_offset,end_offset,ordinal FROM chunks WHERE document_id=? ORDER BY ordinal",row.get("id"));
        result.put("chunk_count",chunks.size());
        if(detail) {
            result.put("content",content);
            result.put("chunks",chunks);
        }
        return result;
    }
    void replaceChunks(Connection c,String id,Ingest.Extraction extracted) throws Exception {
        execute(c,"UPDATE meetings SET analysis_status='stale',analysis_error=NULL,active_run=NULL WHERE document_id=?",id);
        execute(c,"DELETE FROM chunks WHERE document_id=?",id);
        for(Retrieval.Chunk chunk:Retrieval.chunkContent(extracted.content(),extracted.pages())) execute(c,"INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",Auth.uid(),id,chunk.text(),chunk.page(),chunk.startOffset(),chunk.endOffset(),chunk.ordinal());
    }
    Map<String,Object> upload(Connection c,String workspace,Object user,String originalFilename,byte[] source,String rawTitle,String visibility) throws Exception {
        membership(c,workspace,user,false);
        String filename=originalFilename==null?"document":originalFilename.replace('\\','/');
        filename=filename.substring(filename.lastIndexOf('/')+1);
        if(filename.codePointCount(0,filename.length())>255) filename=filename.substring(0,filename.offsetByCodePoints(0,255));
        filename=filename.replaceAll("[\\x00-\\x1f]","");
        if(filename.isEmpty()) filename="document";
        String title=strip(rawTitle==null||rawTitle.isEmpty()?filename:rawTitle);
        if(Ingest.isBlank(title)||length(title)>200) throw new ApiError(422,"invalid_title");
        if(source.length>Ingest.MAX_FILE_BYTES) throw new ApiError(413,"file_too_large");
        String kind=filename.contains(".")?filename.substring(filename.lastIndexOf('.')+1).toLowerCase(Locale.ROOT):"";
        String media=switch(kind) {
            case "pdf"->"application/pdf";
            case "md"->"text/markdown";
            case "txt"->"text/plain";
            default->"application/octet-stream";
        };
        Ingest.Extraction extracted=new Ingest.Extraction("",List.of());
        String error=null;
        try {
            extracted=Ingest.extract(source,kind);
        }
        catch(Ingest.ExtractionError e) {
            error=e.getMessage();
        }
        String id=Auth.uid(),timestamp=Auth.now();
        execute(c,"INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",id,workspace,title,filename,media,visibility,user,error==null?"ready":"failed",error,1,extracted.content(),source,kind,timestamp,timestamp);
        replaceChunks(c,id,extracted);
        return serialize(c,document(c,id,user,false),true);
    }
    Map<String,Object> edit(Connection c,String id,Object user,String title,String content,String visibility) throws Exception {
        document(c,id,user,true);
        if(Ingest.isBlank(title))throw new ApiError(422,"invalid_title");
        Ingest.Extraction extracted;
        try {
            extracted=Ingest.extract(content.getBytes(java.nio.charset.StandardCharsets.UTF_8),"txt");
        }
        catch(Ingest.ExtractionError e) {
            throw new ApiError(422,e.getMessage());
        }
        execute(c,"UPDATE documents SET title=?,content=?,visibility=?,source=?,source_kind='txt',status='ready',error=NULL,revision=revision+1,updated_at=? WHERE id=?",strip(title),extracted.content(),visibility,extracted.content().getBytes(java.nio.charset.StandardCharsets.UTF_8),Auth.now(),id);
        replaceChunks(c,id,extracted);
        return serialize(c,document(c,id,user,false),true);
    }
    Map<String,Object> reprocess(Connection c,String id,Object user) throws Exception {
        Map<String,Object> row=document(c,id,user,true);
        Ingest.Extraction extracted=new Ingest.Extraction("",List.of());
        String error=null;
        try {
            extracted=Ingest.extract((byte[])row.get("source"),(String)row.get("source_kind"));
        }
        catch(Ingest.ExtractionError e) {
            if("ready".equals(row.get("status")))throw new ApiError(422,e.getMessage());
            error=e.getMessage();
        }
        execute(c,"UPDATE documents SET content=?,status=?,error=?,revision=revision+1,updated_at=? WHERE id=?",extracted.content(),error==null?"ready":"failed",error,Auth.now(),id);
        replaceChunks(c,id,extracted);
        return serialize(c,document(c,id,user,false),true);
    }
    static int length(String text) {
        return text.codePointCount(0,text.length());
    }
    static String strip(String text) {
        int start=0,end=text.length();
        while(start<end&&space(text.codePointAt(start)))start+=Character.charCount(text.codePointAt(start));
        while(end>start&&space(text.codePointBefore(end)))end-=Character.charCount(text.codePointBefore(end));
        return text.substring(start,end);
    }
    private static boolean space(int point) {
        return Character.isWhitespace(point)||Character.isSpaceChar(point)||point==0x85;
    }
}
