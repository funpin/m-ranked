package org.mranked.admin.application;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.mranked.admin.domain.CatalogCommandResult;
import org.mranked.admin.domain.ManagedInstitution;
import org.springframework.stereotype.Service;

@Service
public class CatalogService {
    private final CatalogRepository repository;
    public CatalogService(CatalogRepository repository) { this.repository=repository; }
    public List<ManagedInstitution> institutions(long after,int limit) {
        if(after<0 || limit<1 || limit>200) throw new IllegalArgumentException("Invalid catalog page");
        return repository.institutions(after,limit);
    }
    public List<org.mranked.admin.domain.ManagedAccount> accounts(UUID institution,long after,int limit) {
        if(after<0 || limit<1 || limit>200) throw new IllegalArgumentException("Invalid catalog page");
        return repository.accounts(required(institution),after,limit);
    }
    public UUID resolve(String type,long legacyId) {
        if(!Set.of("institutions","platform_accounts","channels").contains(type) || legacyId<1)
            throw new IllegalArgumentException("Invalid legacy identifier");
        return repository.resolve(type,legacyId).orElseThrow(()->new AdminResourceNotFoundException("Catalog resource was not found"));
    }
    public long version(String type,UUID id) {
        return repository.version(type,id).orElseThrow(()->new AdminResourceNotFoundException("Catalog resource was not found"));
    }
    public CatalogCommandResult addChannel(String reference,String actor,UUID correlation) {
        var normalized=AccountReference.parse("telegram",reference,null,null);
        return execute("channel.upsert",null,null,normalized.body(null),actor,correlation);
    }
    public List<CatalogCommandResult> accountMatrix(UUID institution,Map<String,String> references,Long expectedInstitutionVersion,
            Map<String,Long> expectedAccounts,String actor,UUID correlation) {
        var normalized=List.of("telegram","vk","max","rutube").stream()
            .filter(platform->references.get(platform)!=null && !references.get(platform).isBlank())
            .map(platform->AccountReference.parse(platform,references.get(platform),null,null)).toList();
        if(normalized.isEmpty()) throw new IllegalArgumentException("Укажите хотя бы один аккаунт");
        return repository.atomic(()->java.util.stream.IntStream.range(0,normalized.size()).mapToObj(index->{
            var body=normalized.get(index).body(required(institution));
            if(expectedInstitutionVersion!=null) body.put("expectedInstitutionVersion",expectedInstitutionVersion);
            if(expectedAccounts!=null) body.put("expectedAccountVersions",expectedAccounts);
            return execute("account.upsert",null,null,body,actor,
                UUID.nameUUIDFromBytes((correlation+":"+index).getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        }).toList());
    }
    public CatalogCommandResult createInstitution(String name,String shortName,String actor,UUID correlation) {
        String canonical=AccountReference.text(name,1000,"Укажите название вуза");
        String abbreviated=AccountReference.nullable(shortName,1000);
        return execute("institution.create",null,null,Map.of("name",canonical,"shortName",abbreviated==null?canonical:abbreviated),actor,correlation);
    }
    public CatalogCommandResult updateInstitution(UUID id,long version,String name,String shortName,String actor,UUID correlation) {
        return execute("institution.update",required(id),version,Map.of(
            "name",AccountReference.text(name,1000,"Укажите название вуза"),
            "shortName",AccountReference.text(shortName,1000,"Укажите сокращение")),actor,correlation);
    }
    public CatalogCommandResult deleteInstitution(UUID id,long version,String actor,UUID correlation) {
        return execute("institution.delete",required(id),version,Map.of(),actor,correlation);
    }
    public CatalogCommandResult upsertAccount(UUID institution,Long version,String platform,String reference,String title,String url,String actor,UUID correlation) {
        var normalized=AccountReference.parse(platform,reference,title,url);
        return execute("account.upsert",null,version,normalized.body(required(institution)),actor,correlation);
    }
    public CatalogCommandResult versionedAccount(UUID institution,Long version,String platform,String reference,String title,String url,String actor,UUID correlation) {
        var body=AccountReference.parse(platform,reference,title,url).body(required(institution));
        if(version==null) body.put("expectedAccountVersions",Map.of());
        return execute("account.upsert",null,version,body,actor,correlation);
    }
    public CatalogCommandResult accountCommand(UUID id,long version,String operation,String nativeId,String actor,UUID correlation) {
        if(!Set.of("enable","disable","delete","native_id","channel_delete").contains(operation)) throw new IllegalArgumentException("Unsupported account command");
        String action=operation.equals("channel_delete")?"channel.delete":"account."+operation;
        String nativeValue=AccountReference.nullable(nativeId,200);
        return execute(action,required(id),version,Map.of("nativeId",nativeValue==null?"":nativeValue),actor,correlation);
    }
    private CatalogCommandResult execute(String action,UUID target,Long version,Map<String,Object> body,String actor,UUID correlation) {
        if(version!=null && version<0 || correlation==null) throw new IllegalArgumentException("Invalid command version or correlation ID");
        var result=repository.command(action,target,version,body,AdminService.sanitizeActor(actor),correlation);
        return switch(result.outcome()) {
            case "succeeded" -> result;
            case "not_found" -> throw new AdminResourceNotFoundException("Catalog resource was not found");
            case "version_conflict","idempotency_conflict" -> throw new AdminOptimisticLockException();
            default -> throw new IllegalStateException("Unexpected catalog command outcome");
        };
    }
    private static UUID required(UUID value) { if(value==null) throw new IllegalArgumentException("Identifier is required"); return value; }
}
