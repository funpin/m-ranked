package org.mranked.emoji.web;

import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.mranked.emoji.application.CustomEmojiNotFoundException;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = CustomEmojiController.class)
@Order(Ordered.HIGHEST_PRECEDENCE)
public final class CustomEmojiExceptionHandler {
    @ExceptionHandler(CustomEmojiNotFoundException.class)
    public ResponseEntity<ProblemDetail> notFound(
            CustomEmojiNotFoundException exception,
            HttpServletRequest request
    ) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.NOT_FOUND, exception.getMessage()
        );
        problem.setTitle("Resource not found");
        problem.setType(URI.create("urn:m-ranked:problem:not-found"));
        problem.setInstance(URI.create(request.getRequestURI()));
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .cacheControl(CacheControl.noStore())
                .contentType(MediaType.APPLICATION_PROBLEM_JSON)
                .body(problem);
    }
}
