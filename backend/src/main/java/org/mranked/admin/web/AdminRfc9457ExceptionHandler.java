package org.mranked.admin.web;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import java.net.URI;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.application.AdminOptimisticLockException;
import org.mranked.admin.application.AdminResourceNotFoundException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = AdminController.class)
public class AdminRfc9457ExceptionHandler {
    private static final Logger LOGGER = LoggerFactory.getLogger(AdminRfc9457ExceptionHandler.class);

    @ExceptionHandler(AdminResourceNotFoundException.class)
    ResponseEntity<ProblemDetail> notFound(
            AdminResourceNotFoundException exception,
            HttpServletRequest request
    ) {
        return problem(HttpStatus.NOT_FOUND, "Resource not found", exception.getMessage(),
                "urn:m-ranked:problem:not-found", request);
    }

    @ExceptionHandler(AdminOptimisticLockException.class)
    ResponseEntity<ProblemDetail> conflict(
            AdminOptimisticLockException exception,
            HttpServletRequest request
    ) {
        return problem(HttpStatus.CONFLICT, "Concurrent modification", exception.getMessage(),
                "urn:m-ranked:problem:optimistic-lock", request);
    }

    @ExceptionHandler(AdminDatabaseUnavailableException.class)
    ResponseEntity<ProblemDetail> unavailable(
            AdminDatabaseUnavailableException exception,
            HttpServletRequest request
    ) {
        return problem(HttpStatus.SERVICE_UNAVAILABLE, "Administrative database unavailable",
                "The administrative database is unavailable",
                "urn:m-ranked:problem:admin-unavailable", request);
    }

    @ExceptionHandler({
            IllegalArgumentException.class,
            ConstraintViolationException.class,
            HandlerMethodValidationException.class,
            MethodArgumentNotValidException.class,
            MethodArgumentTypeMismatchException.class
    })
    ResponseEntity<ProblemDetail> invalidRequest(Exception exception, HttpServletRequest request) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid request",
                "One or more request parameters are invalid",
                "urn:m-ranked:problem:invalid-request", request);
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ProblemDetail> internalError(Exception exception, HttpServletRequest request) {
        LOGGER.error(
                "Unhandled admin API failure for {} errorType={}",
                request.getRequestURI(), exception.getClass().getName()
        );
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal server error",
                "The request could not be completed",
                "urn:m-ranked:problem:internal-error", request);
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
