package org.mranked.admin.application;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.mranked.admin.domain.CatalogCommandResult;
import org.mranked.admin.domain.ManagedInstitution;

public interface CatalogRepository {
    List<ManagedInstitution> institutions(long afterLegacyId, int limit);
    List<org.mranked.admin.domain.ManagedAccount> accounts(UUID institution,long afterLegacyId,int limit);
    Optional<UUID> resolve(String type, long legacyId);
    Optional<Long> version(String type, UUID id);
    Optional<Long> parentLegacyId(UUID account);
    <T> T atomic(java.util.function.Supplier<T> operation);
    CatalogCommandResult command(String action, UUID target, Long expectedVersion,
            Map<String,Object> body, String actor, UUID correlationId);
}
