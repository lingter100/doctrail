package io.doctrail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.MultipartException;
import org.springframework.web.servlet.resource.NoResourceFoundException;
import java.util.Map;
/** No exception messages, binding values, passwords or parser excerpts cross this boundary. */
@RestControllerAdvice public class ApiErrors {
    @ExceptionHandler(ApiError.class) ResponseEntity<?> api(ApiError e) {
        var response=ResponseEntity.status(e.status);
        if(e.status==429)response.header("Retry-After","60");
        return response.body(Map.of("detail",e.getMessage()));
    }
    @ExceptionHandler(MaxUploadSizeExceededException.class) ResponseEntity<?> size(Exception e) {
        return ResponseEntity.status(413).body(Map.of("detail","request_too_large"));
    }
    @ExceptionHandler( {
        org.springframework.http.converter.HttpMessageNotReadableException.class,org.springframework.web.bind.MissingServletRequestParameterException.class,org.springframework.web.multipart.support.MissingServletRequestPartException.class,org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class,org.springframework.web.bind.MethodArgumentNotValidException.class,MultipartException.class
    }) ResponseEntity<?> validation(Exception e) {
        return ResponseEntity.status(422).body(Map.of("detail","invalid_request"));
    }
    @ExceptionHandler( {
        NoResourceFoundException.class,org.springframework.web.servlet.NoHandlerFoundException.class
    }) ResponseEntity<?> missing(Exception e) {
        return ResponseEntity.status(404).body(Map.of("detail","not_found"));
    }
    @ExceptionHandler(org.springframework.web.HttpRequestMethodNotSupportedException.class) ResponseEntity<?> method(Exception e) {
        return ResponseEntity.status(405).body(Map.of("detail","method_not_allowed"));
    }
    @ExceptionHandler(org.springframework.web.HttpMediaTypeNotSupportedException.class) ResponseEntity<?> media(Exception e) {
        return ResponseEntity.status(422).body(Map.of("detail","invalid_request"));
    }
    @ExceptionHandler(Exception.class) ResponseEntity<?> unknown(Exception e) {
        return ResponseEntity.status(500).body(Map.of("detail","internal_error"));
    }
}
