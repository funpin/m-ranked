package org.mranked.query.application;

public class ResourceNotFoundException extends RuntimeException {
    public ResourceNotFoundException(String resource, long legacyId) {
        super(resource + " with legacy id " + legacyId + " was not found");
    }

    public ResourceNotFoundException(String detail) {
        super(detail);
    }
}
