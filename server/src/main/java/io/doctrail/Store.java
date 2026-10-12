package io.doctrail;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Repository;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.*;
import java.util.*;

/** A connection belongs to exactly one operation; write ACL checks share its SQLite lock. */
@Repository
public class Store {
    private final String url;
    public Store(@Value("${doctrail.db}") String path) {
        try {
            Path absolute = Path.of(path).toAbsolutePath();
            Files.createDirectories(absolute.getParent());
            url = "jdbc:sqlite:" + absolute;
            try (Connection c = connect()) {
                int version = ((Number) one(c, "PRAGMA user_version").get("user_version")).intValue();
                if (version == 0) {
                    execute(c, "BEGIN IMMEDIATE");
                    try {
                        for (String sql : SCHEMA.split(";")) if (!sql.isBlank()) execute(c, sql);
                        execute(c, "COMMIT");
                    } catch (Exception e) { execute(c, "ROLLBACK"); throw e; }
                } else if (version != 1) throw new IllegalStateException("unsupported_database_schema_version");
                // Additive extension: legacy schema-v1 readers safely ignore this table.
                execute(c, "CREATE TABLE IF NOT EXISTS search_metadata (search_id TEXT PRIMARY KEY REFERENCES searches(id) ON DELETE CASCADE,method TEXT NOT NULL CHECK(method IN ('bm25','dense','hybrid','hybrid_rerank')))");
                execute(c, "PRAGMA journal_mode=WAL");
            }
        } catch (Exception e) { throw new IllegalStateException("database_initialization_failed"); }
    }
    Connection connect() throws SQLException {
        Connection c = DriverManager.getConnection(url);
        execute(c, "PRAGMA foreign_keys=ON"); execute(c, "PRAGMA busy_timeout=10000");
        return c;
    }
    @FunctionalInterface interface Work<T> { T run(Connection c) throws Exception; }
    <T> T read(Work<T> work) { return transaction(false, work); }
    <T> T write(Work<T> work) { return transaction(true, work); }
    private <T> T transaction(boolean write, Work<T> work) {
        try (Connection c = connect()) {
            execute(c, write ? "BEGIN IMMEDIATE" : "BEGIN");
            try { T result = work.run(c); execute(c, "COMMIT"); return result; }
            catch (Exception e) { execute(c, "ROLLBACK"); if (e instanceof RuntimeException r) throw r; throw new IllegalStateException("database_operation_failed"); }
        } catch (SQLException e) { throw new IllegalStateException("database_operation_failed"); }
    }
    static void execute(Connection c, String sql, Object... args) throws SQLException {
        try (PreparedStatement p = c.prepareStatement(sql)) { bind(p, args); p.execute(); }
    }
    static List<Map<String,Object>> rows(Connection c, String sql, Object... args) throws SQLException {
        try (PreparedStatement p = c.prepareStatement(sql)) {
            bind(p, args);
            try (ResultSet r = p.executeQuery()) {
                List<Map<String,Object>> result = new ArrayList<>();
                while (r.next()) {
                    Map<String,Object> row = new LinkedHashMap<>();
                    for (int i=1; i<=r.getMetaData().getColumnCount(); i++) row.put(r.getMetaData().getColumnLabel(i), r.getObject(i));
                    result.add(row);
                }
                return result;
            }
        }
    }
    static Map<String,Object> one(Connection c,String sql,Object... args) throws SQLException {
        List<Map<String,Object>> rows=rows(c,sql,args); return rows.isEmpty()?null:rows.getFirst();
    }
    private static void bind(PreparedStatement p,Object[] args) throws SQLException {
        for(int i=0;i<args.length;i++) { if(args[i] instanceof byte[] bytes) p.setBytes(i+1,bytes); else p.setObject(i+1,args[i]); }
    }
    private static final String SCHEMA="""
        CREATE TABLE users (id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,name TEXT NOT NULL,password_hash TEXT NOT NULL);
        CREATE TABLE workspaces (id TEXT PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE memberships (workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,role TEXT NOT NULL CHECK(role IN ('owner','member')),PRIMARY KEY(workspace_id,user_id));
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires_at REAL NOT NULL);
        CREATE TABLE documents (id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,title TEXT NOT NULL,filename TEXT NOT NULL,media_type TEXT NOT NULL,visibility TEXT NOT NULL CHECK(visibility IN ('workspace','private')),owner_id TEXT NOT NULL REFERENCES users(id),status TEXT NOT NULL,error TEXT,revision INTEGER NOT NULL,content TEXT NOT NULL,source BLOB NOT NULL,source_kind TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE chunks (id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,text TEXT NOT NULL,page INTEGER,start_offset INTEGER NOT NULL,end_offset INTEGER NOT NULL,ordinal INTEGER NOT NULL,UNIQUE(document_id,ordinal));
        CREATE TABLE searches (id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,query TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE search_results (search_id TEXT NOT NULL REFERENCES searches(id) ON DELETE CASCADE,document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,chunk_id TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(search_id,chunk_id));
        CREATE TABLE feedback (search_id TEXT NOT NULL REFERENCES searches(id) ON DELETE CASCADE,document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,relevant INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(search_id,document_id));
        CREATE INDEX ix_documents_workspace ON documents(workspace_id);
        CREATE INDEX ix_chunks_document ON chunks(document_id);
        CREATE INDEX ix_searches_user_workspace ON searches(user_id,workspace_id);
        PRAGMA user_version=1;
        """;
}
