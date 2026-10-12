package io.doctrail;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.*;
import org.springframework.http.*;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import java.nio.file.*;
@Controller class FrontendController {
    private final Path dist;
    FrontendController(@Value("${doctrail.web-dist}") String dist) {
        this.dist=Path.of(dist).toAbsolutePath().normalize();
    }
    @GetMapping("/**") ResponseEntity<Resource> frontend(HttpServletRequest request) throws Exception {
        String path=request.getRequestURI().substring(1);
        if(path.equals("api")||path.startsWith("api/"))throw new ApiError(404,"not_found");
        if(path.contains("\\")||path.contains("%")||path.contains(".."))throw new ApiError(404,"not_found");
        Path target=dist.resolve(path).normalize();
        if(!target.startsWith(dist))throw new ApiError(404,"not_found");
        Resource resource=new FileSystemResource(target);
        if(!resource.isReadable()||Files.isDirectory(target))resource=new ClassPathResource("static/"+path);
        if(!resource.exists()||!resource.isReadable()||path.isEmpty()) {
            if(path.substring(path.lastIndexOf('/')+1).contains("."))throw new ApiError(404,"frontend_not_built");
            resource=new FileSystemResource(dist.resolve("index.html"));
            if(!resource.exists())resource=new ClassPathResource("static/index.html");
        }
        if(!resource.exists()||!resource.isReadable())throw new ApiError(404,"frontend_not_built");
        return ResponseEntity.ok().contentType(MediaTypeFactory.getMediaType(resource).orElse(MediaType.APPLICATION_OCTET_STREAM)).body(resource);
    }
}
