package io.doctrail;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerMapping;
import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
/** Bound JSON streams; multipart streams use the container's independent maxRequestSize. */
@Component @Order(Ordered.HIGHEST_PRECEDENCE) public class RequestGuard extends OncePerRequestFilter {
    static final int MAX_REQUEST_BYTES=5*1024*1024+65536;
    private static final Logger LOG=LoggerFactory.getLogger("doctrail.requests");
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws ServletException,IOException {
        String id=Auth.uid();
        long start=System.nanoTime();
        response.setHeader("X-Request-ID",id);
        response.setHeader("X-Content-Type-Options","nosniff");
        response.setHeader("Referrer-Policy","same-origin");
        response.setHeader("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'");
        if(request.getRequestURI().startsWith("/api")) response.setHeader("Cache-Control","no-store");
        try {
            if(!java.util.Set.of("GET","HEAD","OPTIONS").contains(request.getMethod())) {
                String origin=request.getHeader("Origin");
                if("cross-site".equals(request.getHeader("Sec-Fetch-Site"))||origin!=null&&!sameOrigin(origin,request)) throw new ApiError(403,"cross_origin_request_rejected");
            }
            String length=request.getHeader("Content-Length");
            if(length!=null) {
                try {
                    if(Long.parseLong(length)<0||Long.parseLong(length)>MAX_REQUEST_BYTES) throw new ApiError(413,"request_too_large");
                }
                catch(NumberFormatException e) {
                    throw new ApiError(413,"request_too_large");
                }
            }
            if(request.getContentType()!=null&&request.getContentType().toLowerCase(java.util.Locale.ROOT).startsWith("multipart/")) {
                chain.doFilter(request,response);
            }
            else {
                byte[] body=request.getInputStream().readNBytes(MAX_REQUEST_BYTES+1);
                if(body.length>MAX_REQUEST_BYTES) throw new ApiError(413,"request_too_large");
                chain.doFilter(new CachedRequest(request,body),response);
            }
        }
        catch(ApiError e) {
            error(response,e.status,e.getMessage());
        }
        catch(Exception e) {
            error(response,500,"internal_error");
        }
        finally {
            Object route=request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
            // Never log the URL, query string, exceptions or request body.
            LOG.info("request_id={} method={} route={} status={} elapsed_ms={}",id,request.getMethod(),route==null?"unmatched":route,response.getStatus(),(System.nanoTime()-start)/1_000_000.0);
        }
    }
    private static boolean sameOrigin(String origin,HttpServletRequest request) {
        try {
            URI parsed=URI.create(origin),target=URI.create(request.getRequestURL().toString());
            return parsed.getScheme()!=null&&parsed.getRawAuthority()!=null&&parsed.getScheme().equals(target.getScheme())&&parsed.getRawAuthority().equals(target.getRawAuthority());
        }
        catch(IllegalArgumentException e) {
            return false;
        }
    }
    static void error(HttpServletResponse response,int status,String code) throws IOException {
        if(response.isCommitted()) return;
        response.resetBuffer();
        response.setStatus(status);
        response.setContentType("application/json");
        response.getWriter().write("{\"detail\":\""+code+"\"}");
    }
    private static final class CachedRequest extends HttpServletRequestWrapper {
        private final byte[] body;
        CachedRequest(HttpServletRequest request,byte[] body) {
            super(request);
            this.body=body;
        }
        @Override public ServletInputStream getInputStream() {
            ByteArrayInputStream input=new ByteArrayInputStream(body);
            return new ServletInputStream() {
                public int read() {
                    return input.read();
                }
                public int read(byte[] bytes,int offset,int length) {
                    return input.read(bytes,offset,length);
                }
                public boolean isFinished() {
                    return input.available()==0;
                }
                public boolean isReady() {
                    return true;
                }
                public void setReadListener(ReadListener listener) {
                    throw new UnsupportedOperationException("synchronous_requests_only");
                }
            };
        }
        @Override public BufferedReader getReader() {
            return new BufferedReader(new InputStreamReader(getInputStream(),StandardCharsets.UTF_8));
        }
    }
}
