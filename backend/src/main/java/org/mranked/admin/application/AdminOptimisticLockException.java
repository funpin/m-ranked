package org.mranked.admin.application;

public class AdminOptimisticLockException extends RuntimeException {
    public AdminOptimisticLockException() {
        super("The platform account changed after it was read");
    }
}
