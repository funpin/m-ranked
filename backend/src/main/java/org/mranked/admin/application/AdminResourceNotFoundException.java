package org.mranked.admin.application;

public class AdminResourceNotFoundException extends RuntimeException {
    public AdminResourceNotFoundException(String detail) {
        super(detail);
    }
}
