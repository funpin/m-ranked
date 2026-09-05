package org.mranked.admin.application;

public class AdminDatabaseUnavailableException extends RuntimeException {
    public AdminDatabaseUnavailableException() {
        super("Administrative mutations are not configured on this runtime");
    }
}
