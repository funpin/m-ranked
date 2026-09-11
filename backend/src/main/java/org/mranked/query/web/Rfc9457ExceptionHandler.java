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

    @ExceptionHandler(org.mranked.query.application.CsvExportLimitException.class)
    public org.springframework.http.ResponseEntity<org.springframework.http.ProblemDetail> exportLimit(
            org.mranked.query.application.CsvExportLimitException exception) {
        var problem = org.springframework.http.ProblemDetail.forStatusAndDetail(org.springframework.http.HttpStatus.TOO_MANY_REQUESTS, exception.getMessage());
        return org.springframework.http.ResponseEntity.status(429).header("Retry-After", "60")
                .header("Cache-Control", "no-store").body(problem);
    }

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
        Throwable root = exception;
        while (root.getCause() != null && root.getCause() != root) root = root.getCause();
        String sqlState = root instanceof java.sql.SQLException sql ? sql.getSQLState() : null;
        String serverRoutine = postgresServerRoutine(root);
        Integer serverPosition = postgresServerPosition(root);
        LOGGER.error(
                "Unhandled API failure for {} errorType={} rootType={} sqlState={} serverRoutine={} serverPosition={}",
                request.getRequestURI(), exception.getClass().getName(), root.getClass().getName(),
                sqlState, serverRoutine, serverPosition
        );
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal server error",
                "The request could not be completed", "urn:m-ranked:problem:internal-error", request);
    }

    private static String postgresServerRoutine(Throwable root) {
        if (!"org.postgresql.util.PSQLException".equals(root.getClass().getName())) return null;
        try {
            Object serverError = root.getClass().getMethod("getServerErrorMessage").invoke(root);
            if (serverError == null) return null;
            Object routine = serverError.getClass().getMethod("getRoutine").invoke(serverError);
            return routine instanceof String value ? value : null;
        } catch (ReflectiveOperationException ignored) {
            return null;
        }
    }

    private static Integer postgresServerPosition(Throwable root) {
        if (!"org.postgresql.util.PSQLException".equals(root.getClass().getName())) return null;
        try {
            Object serverError = root.getClass().getMethod("getServerErrorMessage").invoke(root);
            if (serverError == null) return null;
            Object position = serverError.getClass().getMethod("getPosition").invoke(serverError);
            return position instanceof Integer value ? value : null;
        } catch (ReflectiveOperationException ignored) {
            return null;
        }
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
