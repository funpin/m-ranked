package org.mranked.query.application;

public class InvalidCursorException extends RuntimeException {
    public InvalidCursorException() {
        super("The cursor is malformed or unsupported");
    }
}
