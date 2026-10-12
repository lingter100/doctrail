package io.doctrail;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.bouncycastle.crypto.generators.SCrypt;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.sql.Connection;
import java.util.*;
import static io.doctrail.Store.*;
@Component public class Auth {
    static final String COOKIE="doctrail_session";
    static final long TTL=604800;
    private static final SecureRandom RANDOM=new SecureRandom();
    private final boolean secure;
    private final String dummy=passwordHash(randomToken());
    private final Map<String,ArrayDeque<Long>> attempts=new HashMap<>();
    Auth(@Value("${doctrail.secure-cookie}") String secure) {
        this.secure="1".equals(secure);
    }
    static String uid() {
        return UUID.randomUUID().toString().replace("-","");
    }
    static String now() {
        return java.time.OffsetDateTime.now(java.time.ZoneOffset.UTC).format(java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSSSSSxxx"));
    }
    static String randomToken() {
        byte[] bytes=new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
    static String hash(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)));
        }
        catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("hash_unavailable");
        }
    }
    static String passwordHash(String password) {
        byte[] salt=new byte[16];
        RANDOM.nextBytes(salt);
        return derive(password,HexFormat.of().formatHex(salt));
    }
    private static String derive(String password,String salt) {
        return salt+":"+HexFormat.of().formatHex(SCrypt.generate(password.getBytes(StandardCharsets.UTF_8),HexFormat.of().parseHex(salt),16384,8,1,64));
    }
    static boolean verify(String password,String stored) {
        try {
            return MessageDigest.isEqual(derive(password,stored.split(":",-1)[0]).getBytes(StandardCharsets.US_ASCII),stored.getBytes(StandardCharsets.US_ASCII));
        }
        catch (IllegalArgumentException e) {
            return false;
        }
    }
    boolean verifyOrDummy(String password,Map<String,Object> record) {
        return verify(password,record==null?dummy:(String)record.get("password_hash"));
    }
    static String token(HttpServletRequest request) {
        if(request.getCookies()!=null) for(Cookie cookie:request.getCookies()) if(COOKIE.equals(cookie.getName())) return cookie.getValue();
        return "";
    }
    Map<String,Object> user(Connection c,HttpServletRequest request) throws Exception {
        Map<String,Object> user=one(c,"SELECT u.id,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",hash(token(request)),System.currentTimeMillis()/1000.0);
        if(user==null) throw new ApiError(401,"authentication_required");
        return user;
    }
    void session(Connection c,HttpServletRequest request,HttpServletResponse response,String userId) throws Exception {
        String token=randomToken();
        execute(c,"DELETE FROM sessions WHERE token_hash=? OR expires_at<=?",hash(token(request)),System.currentTimeMillis()/1000.0);
        execute(c,"INSERT INTO sessions VALUES (?,?,?)",hash(token),userId,System.currentTimeMillis()/1000.0+TTL);
        response.addHeader("Set-Cookie",ResponseCookie.from(COOKIE,token).path("/").httpOnly(true).secure(secure).sameSite("Strict").maxAge(TTL).build().toString());
    }
    void clear(HttpServletResponse response) {
        response.addHeader("Set-Cookie",ResponseCookie.from(COOKIE,"").path("/").httpOnly(true).secure(secure).sameSite("Strict").maxAge(0).build().toString());
    }
    synchronized void throttle(HttpServletRequest request) {
        long current=System.nanoTime(),cutoff=current-60_000_000_000L;
        if(attempts.size()>4096) attempts.entrySet().removeIf(e->e.getValue().isEmpty()||e.getValue().getLast()<cutoff);
        ArrayDeque<Long> queue=attempts.computeIfAbsent(request.getRemoteAddr(),key->new ArrayDeque<>());
        while(!queue.isEmpty()&&queue.getFirst()<cutoff) queue.removeFirst();
        if(queue.size()>=20) throw new ApiError(429,"authentication_rate_limited");
        queue.addLast(current);
    }
}
