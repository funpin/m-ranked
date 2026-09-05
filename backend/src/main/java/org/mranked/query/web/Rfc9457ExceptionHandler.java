package org.mranked.query.web;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import java.net.URI;
import org.mranked.query.application.InvalidCursorException;
import org.mranked.query.application.ResourceNotFoundException;
import org.mranked.query.domain.InvalidComparisonSelectionException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.CacheControl;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice
public class Rfc9457ExceptionHandler {
    private static final Logger LOGGER = LoggerFactory.getLogger(Rfc9457ExceptionHandler.class);

    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity<ProblemDetail> notFound(
            ResourceNotFoundException exception,
            HttpServletRequest request
    ) {
        return problem(HttpStatus.NOT_FOUND, "Resource not found", exception.getMessage(),
                "urn:m-ranked:problem:not-found", request);
    }

    @ExceptionHandler({
            InvalidCursorException.class,
            IllegalArgumentException.class,
            ConstraintViolationException.class,
            HandlerMethodValidationException.class,
            MethodArgumentNotValidException.class,
            MethodArgumentTypeMismatchException.class,
            MissingServletRequestParameterException.class
    })
    public ResponseEntity<ProblemDetail> invalidRequest(Exception exception, HttpServletRequest request) {
        String detail = exception instanceof InvalidCursorException
                || exception instanceof InvalidComparisonSelectionException
                ? exception.getMessage() : "One or more request parameters are invalid";
        return problem(HttpStatus.BAD_REQUEST, "Invalid request", detail,
                "urn:m-ranked:problem:invalid-request", request);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ProblemDetail> internalError(
            Exception exception,
            HttpServletRequest request
    ) {
        LOGGER.error(
                "Unhandled API failure for {} errorType={}",
                request.getRequestURI(), exception.getClass().getName()
        );
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal server error",
                "The request could not be completed", "urn:m-ranked:problem:internal-error", request);
    }

    private static ResponseEntity<ProblemDetail> problem(
            HttpStatus status,
            String title,
            String detail,
            String type,
            HttpServletRequest request
    ) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setTitle(title);
        problem.setType(URI.create(type));
        problem.setInstance(URI.create(request.getRequestURI()));
        return ResponseEntity.status(status)
                .cacheControl(CacheControl.noStore())
                .contentType(MediaType.APPLICATION_PROBLEM_JSON)
                .body(problem);
    }
}
