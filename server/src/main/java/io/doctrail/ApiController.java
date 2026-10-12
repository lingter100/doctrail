package io.doctrail;
import jakarta.servlet.http.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.util.*;
import static io.doctrail.Store.*;
import static io.doctrail.DocumentService.length;
import static io.doctrail.DocumentService.strip;
@RestController @RequestMapping("/api") public class ApiController {
    private final Store store;
    private final Auth auth;
    private final DocumentService docs;
    ApiController(Store store,Auth auth,DocumentService docs) {
        this.store=store;
        this.auth=auth;
        this.docs=docs;
    }
    private static void fields(Map<String,Object> body,String... required) {
        if(body==null||!body.keySet().equals(Set.of(required)))throw new ApiError(422,"invalid_request");
    }
    private static String string(Map<String,Object> body,String key,int min,int max) {
        Object value=body.get(key);
        if(!(value instanceof String s)||length(s)<min||length(s)>max)throw new ApiError(422,"invalid_request");
        return s;
    }
    private static String email(Map<String,Object> body) {
        String email=strip(string(body,"email",3,254)).toLowerCase(Locale.ROOT);
        if(!email.contains("@")||email.codePoints().anyMatch(c->Character.isWhitespace(c)||Character.isSpaceChar(c)||c==0x85))throw new ApiError(422,"invalid_request");
        return email;
    }
    private static String visibility(String value) {
        if(!Set.of("workspace","private").contains(value))throw new ApiError(422,"invalid_request");
        return value;
    }
    @GetMapping("/health") Map<String,Object> health() {
        return Map.of("status","ok","version","0.1.0");
    }
    @PostMapping("/auth/register") @ResponseStatus(HttpStatus.CREATED) Map<String,Object> register(@RequestBody Map<String,Object> body,HttpServletRequest request,HttpServletResponse response) {
        fields(body,"email","password","name","workspace_name");
        String email=email(body),password=string(body,"password",10,1024),name=strip(string(body,"name",1,100)),workspace=strip(string(body,"workspace_name",1,100));
        if(name.isEmpty()||workspace.isEmpty())throw new ApiError(422,"invalid_request");
        auth.throttle(request);
        String passwordHash=Auth.passwordHash(password);
        return store.write(c-> {
            if(one(c,"SELECT id FROM users WHERE email=?",email)!=null)throw new ApiError(409,"email_already_registered");
            String userId=Auth.uid(),workspaceId=Auth.uid();
            execute(c,"INSERT INTO users VALUES (?,?,?,?)",userId,email,name,passwordHash);
            execute(c,"INSERT INTO workspaces VALUES (?,?)",workspaceId,workspace);
            execute(c,"INSERT INTO memberships VALUES (?,?,'owner')",workspaceId,userId);
            auth.session(c,request,response,userId);
            return Map.of("user",Map.of("id",userId,"email",email,"name",name),"workspaces",docs.workspaces(c,userId));
        });
    }
    @PostMapping("/auth/login") Map<String,Object> login(@RequestBody Map<String,Object> body,HttpServletRequest request,HttpServletResponse response) {
        fields(body,"email","password");
        String email=email(body),password=string(body,"password",1,1024);
        auth.throttle(request);
        return store.write(c-> {
            Map<String,Object> row=one(c,"SELECT * FROM users WHERE email=?",email);
            boolean valid=auth.verifyOrDummy(password,row);
            if(row==null||!valid)throw new ApiError(401,"invalid_credentials");
            String id=(String)row.get("id");
            auth.session(c,request,response,id);
            row.remove("password_hash");
            return Map.of("user",row,"workspaces",docs.workspaces(c,id));
        });
    }
    @GetMapping("/auth/me") Map<String,Object> me(HttpServletRequest request) {
        return store.read(c-> {
            Map<String,Object> user=auth.user(c,request);
            return Map.of("user",user,"workspaces",docs.workspaces(c,user.get("id")));
        });
    }
    @PostMapping("/auth/logout") @ResponseStatus(HttpStatus.NO_CONTENT) void logout(HttpServletRequest request,HttpServletResponse response) {
        store.write(c-> {
            execute(c,"DELETE FROM sessions WHERE token_hash=?",Auth.hash(Auth.token(request)));
            return null;
        });
        auth.clear(response);
    }
    @GetMapping("/workspaces") Map<String,Object> workspaces(HttpServletRequest request) {
        return store.read(c->Map.of("items",docs.workspaces(c,auth.user(c,request).get("id"))));
    }
    @PostMapping("/workspaces") @ResponseStatus(HttpStatus.CREATED) Map<String,Object> createWorkspace(@RequestBody Map<String,Object> body,HttpServletRequest request) {
        fields(body,"name");
        String name=strip(string(body,"name",1,100));
        if(name.isEmpty())throw new ApiError(422,"invalid_request");
        return store.write(c-> {
            Object user=auth.user(c,request).get("id");
            String id=Auth.uid();
            execute(c,"INSERT INTO workspaces VALUES (?,?)",id,name);
            execute(c,"INSERT INTO memberships VALUES (?,?,'owner')",id,user);
            return Map.of("id",id,"name",name,"role","owner");
        });
    }
    @GetMapping("/workspaces/{workspace_id}/members") Map<String,Object> members(@PathVariable("workspace_id") String workspace,HttpServletRequest request) {
        return store.read(c-> {
            Object user=auth.user(c,request).get("id");
            docs.membership(c,workspace,user,false);
            return Map.of("items",rows(c,"SELECT u.id,u.email,u.name,m.role FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.workspace_id=? ORDER BY u.name,u.id",workspace));
        });
    }
    @PostMapping("/workspaces/{workspace_id}/members") @ResponseStatus(HttpStatus.CREATED) Map<String,Object> addMember(@PathVariable("workspace_id") String workspace,@RequestBody Map<String,Object> body,HttpServletRequest request) {
        fields(body,"email");
        String email=strip(string(body,"email",3,254)).toLowerCase(Locale.ROOT);
        return store.write(c-> {
            Object user=auth.user(c,request).get("id");
            docs.membership(c,workspace,user,true);
            Map<String,Object> member=one(c,"SELECT id FROM users WHERE email=?",email);
            if(member==null)throw new ApiError(404,"user_not_found");
            execute(c,"INSERT OR IGNORE INTO memberships VALUES (?,?,'member')",workspace,member.get("id"));
            return Map.of("ok",true);
        });
    }
    @GetMapping("/workspaces/{workspace_id}/documents") Map<String,Object> documents(@PathVariable("workspace_id") String workspace,HttpServletRequest request) {
        return store.read(c-> {
            Object user=auth.user(c,request).get("id");
            docs.membership(c,workspace,user,false);
            List<Map<String,Object>> items=new ArrayList<>();
            for(Map<String,Object> row:rows(c,"SELECT * FROM documents WHERE workspace_id=? AND (visibility='workspace' OR owner_id=?) ORDER BY updated_at DESC,id",workspace,user))items.add(docs.serialize(c,row,false));
            return Map.of("items",items);
        });
    }
    @PostMapping("/workspaces/{workspace_id}/documents") @ResponseStatus(HttpStatus.CREATED) Map<String,Object> upload(@PathVariable("workspace_id") String workspace,@RequestParam("file") MultipartFile file,@RequestParam(required=false) String title,@RequestParam(defaultValue="workspace") String visibility,HttpServletRequest request) throws java.io.IOException {
        String checkedVisibility=visibility(visibility);
        if(file.getSize()>Ingest.MAX_FILE_BYTES)throw new ApiError(413,"file_too_large");
        byte[] source=file.getBytes();
        return store.write(c->docs.upload(c,workspace,auth.user(c,request).get("id"),file.getOriginalFilename(),source,title,checkedVisibility));
    }
    @GetMapping("/documents/{document_id}") Map<String,Object> document(@PathVariable("document_id") String id,HttpServletRequest request) {
        return store.read(c->docs.serialize(c,docs.document(c,id,auth.user(c,request).get("id"),false),true));
    }
    @PutMapping("/documents/{document_id}") Map<String,Object> edit(@PathVariable("document_id") String id,@RequestBody Map<String,Object> body,HttpServletRequest request) {
        fields(body,"title","content","visibility");
        String title=string(body,"title",1,200),content=string(body,"content",1,Ingest.MAX_CONTENT_CHARS),visibility=visibility(string(body,"visibility",1,20));
        return store.write(c->docs.edit(c,id,auth.user(c,request).get("id"),title,content,visibility));
    }
    @PostMapping("/documents/{document_id}/reprocess") Map<String,Object> reprocess(@PathVariable("document_id") String id,HttpServletRequest request) {
        return store.write(c->docs.reprocess(c,id,auth.user(c,request).get("id")));
    }
    @DeleteMapping("/documents/{document_id}") @ResponseStatus(HttpStatus.NO_CONTENT) void delete(@PathVariable("document_id") String id,HttpServletRequest request) {
        store.write(c-> {
            Object user=auth.user(c,request).get("id");
            docs.document(c,id,user,true);
            execute(c,"DELETE FROM documents WHERE id=?",id);
            return null;
        });
    }
    @GetMapping("/workspaces/{workspace_id}/search") Map<String,Object> search(@PathVariable("workspace_id") String workspace,@RequestParam String q,@RequestParam(defaultValue="10") int limit,HttpServletRequest request) {
        if(length(q)<1||length(q)>500||limit<1||limit>50)throw new ApiError(422,"invalid_request");
        if(Ingest.isBlank(q))throw new ApiError(422,"query_required");
        long started=System.nanoTime();
        String searchId=Auth.uid();
        return store.write(c-> {
            Object user=auth.user(c,request).get("id");
            docs.membership(c,workspace,user,false);
            List<Map<String,Object>> candidates=rows(c,"SELECT d.id AS document_id,d.title,d.filename,d.revision,c.id AS chunk_id,c.text,c.page,c.start_offset,c.end_offset FROM chunks c JOIN documents d ON c.document_id=d.id WHERE d.workspace_id=? AND d.status='ready' AND (d.visibility='workspace' OR d.owner_id=?)",workspace,user);
            List<Map<String,Object>> results=Retrieval.rankChunks(q,candidates,limit);
            execute(c,"INSERT INTO searches VALUES (?,?,?,?,?)",searchId,workspace,user,q,Auth.now());
            for(Map<String,Object> result:results)execute(c,"INSERT INTO search_results VALUES (?,?,?,?)",searchId,result.get("document_id"),result.get("chunk_id"),result.get("revision"));
            return Map.of("query",q,"method","bm25","elapsed_ms",Math.round((System.nanoTime()-started)/10_000.0)/100.0,"search_id",searchId,"results",results);
        });
    }
    @GetMapping("/workspaces/{workspace_id}/history") Map<String,Object> history(@PathVariable("workspace_id") String workspace,HttpServletRequest request) {
        return store.read(c-> {
            Object user=auth.user(c,request).get("id");
            docs.membership(c,workspace,user,false);
            return Map.of("items",rows(c,"SELECT s.id,s.query,s.created_at,(SELECT COUNT(*) FROM search_results r JOIN documents d ON d.id=r.document_id WHERE r.search_id=s.id AND d.status='ready' AND d.revision=r.revision AND (d.visibility='workspace' OR d.owner_id=?)) AS result_count FROM searches s WHERE s.workspace_id=? AND s.user_id=? ORDER BY s.created_at DESC,s.id LIMIT 100",user,workspace,user));
        });
    }
    @PostMapping("/searches/{search_id}/feedback") Map<String,Object> feedback(@PathVariable("search_id") String search,@RequestBody Map<String,Object> body,HttpServletRequest request) {
        fields(body,"document_id","relevant");
        String id=string(body,"document_id",0,Integer.MAX_VALUE);
        if(!(body.get("relevant") instanceof Boolean relevant))throw new ApiError(422,"invalid_request");
        return store.write(c-> {
            Object user=auth.user(c,request).get("id");
            Map<String,Object> row=one(c,"SELECT * FROM searches WHERE id=? AND user_id=?",search,user);
            if(row==null)throw new ApiError(404,"search_not_found");
            docs.membership(c,(String)row.get("workspace_id"),user,false);
            Map<String,Object> doc=docs.document(c,id,user,false);
            Map<String,Object> returned=one(c,"SELECT revision FROM search_results WHERE search_id=? AND document_id=? LIMIT 1",search,id);
            if(returned==null)throw new ApiError(422,"document_not_in_search");
            if(!Objects.equals(doc.get("revision"),returned.get("revision")))throw new ApiError(409,"search_result_stale");
            execute(c,"INSERT INTO feedback VALUES (?,?,?,?) ON CONFLICT(search_id,document_id) DO UPDATE SET relevant=excluded.relevant,created_at=excluded.created_at",search,id,relevant?1:0,Auth.now());
            return Map.of("ok",true);
        });
    }
}
