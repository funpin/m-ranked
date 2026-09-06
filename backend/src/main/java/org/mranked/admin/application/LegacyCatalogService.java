package org.mranked.admin.application;

import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

/** The unversioned HTML forms keep their original URL and redirect contracts. */
@Service
public class LegacyCatalogService {
    private static final Pattern INSTITUTION=Pattern.compile("^/manage/institutions/([1-9][0-9]*)(/accounts)?$");
    private static final Pattern ACCOUNT=Pattern.compile("^/manage/(channels|platform-accounts)/([1-9][0-9]*)/(enable|disable|delete|native-id)$");
    private final CatalogService catalog;
    private final CatalogRepository repository;
    private final OfficialRatingService ratings;
    public LegacyCatalogService(CatalogService catalog,CatalogRepository repository,OfficialRatingService ratings) { this.catalog=catalog;this.repository=repository;this.ratings=ratings; }
    public String execute(String path,Map<String,String> fields,String actor,UUID correlation) {
        try { return executeForm(path,fields,actor,correlation); }
        catch(AdminResourceNotFoundException missing) {
            String detail=path!=null && path.startsWith("/manage/channels/")?"Канал не найден"
                :path!=null && path.startsWith("/manage/platform-accounts/")?"Аккаунт не найден":"Вуз не найден";
            throw new AdminResourceNotFoundException(detail);
        }
        catch(IllegalArgumentException invalid) { throw LegacyFormException.safe(invalid.getMessage()); }
    }
    private String executeForm(String path,Map<String,String> fields,String actor,UUID correlation) {
        if(path==null || path.length()>200 || fields==null || fields.size()>20
            || fields.entrySet().stream().anyMatch(entry->entry.getKey().length()>100 || entry.getValue()==null
                || entry.getValue().length()>(entry.getKey().equals("expected_account_versions")?131072:4096)))
            throw new IllegalArgumentException("Invalid form");
        if(path.equals("/manage/m-rating/update")) {
            try { ratings.refresh(actor,correlation); return "/manage?m_rating_status=updated"; }
            catch(AdminOptimisticLockException conflict) { throw conflict; }
            catch(RuntimeException failure) { return "/manage?m_rating_status=error"; }
        }
        if(path.equals("/manage/institutions")) {
            var result=catalog.createInstitution(required(fields,"name"),fields.get("short_name"),actor,correlation);
            return "/manage?platform_status=institution-added&institution_id="+result.legacyId();
        }
        if(path.equals("/manage/channels")) {
            catalog.addChannel(required(fields,"channel"),actor,correlation);
            return "/manage?channel_status=added";
        }
        if(path.equals("/manage/platform-accounts")) {
            String platform=required(fields,"platform");
            if(!java.util.Set.of("vk","max","rutube").contains(platform)) throw new IllegalArgumentException("Telegram-каналы добавляются через основную форму мониторинга");
            long institutionId=Long.parseLong(required(fields,"institution_id"));
            if(institutionId<1) throw new AdminResourceNotFoundException("Вуз не найден");
            UUID institution=catalog.resolve("institutions",institutionId);
            catalog.upsertAccount(institution,null,platform,required(fields,"reference"),fields.get("title"),fields.get("url"),actor,correlation);
            return "/manage?platform_status=account-added";
        }
        var institution=INSTITUTION.matcher(path);
        if(institution.matches()) {
            if(institution.group(2)==null && (required(fields,"name").isBlank() || required(fields,"short_name").isBlank()))
                throw new IllegalArgumentException("Institution name and short name are required");
            long legacyId=positive(institution.group(1)); UUID id=catalog.resolve("institutions",legacyId);
            if(institution.group(2)!=null) {
                catalog.accountMatrix(id,Map.of("telegram",fields.getOrDefault("telegram",""),"vk",fields.getOrDefault("vk",""),
                    "max",fields.getOrDefault("max_account",""),"rutube",fields.getOrDefault("rutube","")),
                    fields.containsKey("expected_row_version")?Long.valueOf(fields.get("expected_row_version")):null,
                    expectedAccounts(fields.get("expected_account_versions")),actor,correlation);
                return "/manage?platform_status=accounts-updated&institution_id="+legacyId;
            }
            catalog.updateInstitution(id,version(fields,"institutions",id),required(fields,"name"),required(fields,"short_name"),actor,correlation);
            return "/manage?platform_status=institution-updated&institution_id="+legacyId;
        }
        var account=ACCOUNT.matcher(path);
        if(account.matches()) {
            String type=account.group(1).replace('-','_'); UUID id=catalog.resolve(type,positive(account.group(2)));
            String operation=account.group(3); boolean channel=type.equals("channels");
            if(channel && operation.equals("native-id")) throw new AdminResourceNotFoundException("Route was not found");
            Long parent=repository.parentLegacyId(id).orElseThrow(()->new AdminResourceNotFoundException("Аккаунт не найден"));
            if(operation.equals("native-id")) {
                String value=required(fields,"native_id").strip();
                UUID institutionId=catalog.resolve("institutions",parent);
                var target=repository.accounts(institutionId,positive(account.group(2))-1,1).stream()
                    .filter(row->row.id().equals(id)).findFirst().orElseThrow(()->new AdminResourceNotFoundException("Аккаунт не найден"));
                if(target.platform().equals("max") && !value.isEmpty() && !value.matches("-?[0-9]+"))
                    throw new IllegalArgumentException("MAX chat_id должен быть числом");
            }
            catalog.accountCommand(id,version(fields,type,id),channel && operation.equals("delete")?"channel_delete":operation.replace('-','_'),
                operation.equals("native-id")?required(fields,"native_id"):null,actor,correlation);
            if(channel) return operation.equals("delete")?"/manage?channel_status=deleted":"/manage";
            String status=switch(operation) {case "enable"->"account-enabled";case "disable"->"account-disabled";
                case "delete"->"account-deleted";default->"native-id-updated";};
            return "/manage?platform_status="+status+"&institution_id="+parent;
        }
        throw new AdminResourceNotFoundException("Route was not found");
    }
    private long version(Map<String,String> fields,String type,UUID id) {
        String value=fields.get("expected_row_version");
        // Existing bookmarked legacy forms predate optimistic version fields;
        // bind their command to the state observed by this request, then CAS in SQL.
        return value==null?catalog.version(type,id):Long.parseLong(value);
    }
    private static String required(Map<String,String> fields,String name) {
        if(!fields.containsKey(name)) throw new IllegalArgumentException("Missing form field: "+name); return fields.get(name);
    }
    private static long positive(String value) { long result=Long.parseLong(value); if(result<1) throw new IllegalArgumentException("Invalid identifier"); return result; }
    private static Map<String,Long> expectedAccounts(String value) {
        if(value==null) return null;
        try {
            var json=new tools.jackson.databind.json.JsonMapper().readTree(value);
            if(!json.isObject() || json.size()>2000) throw new IllegalArgumentException("Invalid account versions");
            Map<String,Long> result=new java.util.LinkedHashMap<>();
            for(var property:json.properties()) {
                UUID.fromString(property.getKey());
                if(!property.getValue().isIntegralNumber() || !property.getValue().canConvertToLong() || property.getValue().longValue()<0)
                    throw new IllegalArgumentException("Invalid account version");
                result.put(property.getKey(),property.getValue().longValue());
            }
            return result;
        } catch(RuntimeException failure) { throw new IllegalArgumentException("Invalid account versions"); }
    }
}
