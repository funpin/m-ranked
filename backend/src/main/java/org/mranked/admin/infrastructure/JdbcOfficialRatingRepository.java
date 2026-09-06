package org.mranked.admin.infrastructure;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.HashSet;
import java.util.UUID;
import org.mranked.admin.application.AdminOptimisticLockException;
import org.mranked.admin.application.OfficialRatingRepository;
import org.mranked.admin.domain.OfficialRatingDataset;
import org.mranked.admin.domain.OfficialRating;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.json.JsonMapper;

final class JdbcOfficialRatingRepository implements OfficialRatingRepository {
    private static final JsonMapper JSON=new JsonMapper();
    private static final Map<String,String> CODES=loadCodes();
    private final JdbcClient jdbc;
    private final TransactionOperations transactions;
    JdbcOfficialRatingRepository(JdbcClient jdbc,TransactionOperations transactions) { this.jdbc=jdbc;this.transactions=transactions; }
    public Optional<Result> previous(String actor,UUID correlation) {
        return jdbc.sql("SELECT ops_and_admin.previous_official_rating(:actor,:id)::text").param("actor",actor).param("id",correlation)
            .query((row,index)->row.getString(1)).optional().map(JdbcOfficialRatingRepository::result);
    }
    public Result persist(OfficialRatingDataset dataset,String actor,UUID correlation) {
        return transactions.execute(status->{
            jdbc.sql("SELECT pg_advisory_xact_lock(782194601)").query((row,index)->Boolean.TRUE).single();
            var channels=jdbc.sql("""
                SELECT account.id,account.institution_id,account.current_username
                FROM catalog.visible_platform_account account JOIN catalog.legacy_entity_alias alias
                    ON alias.target_uuid=account.id AND alias.entity_type='channels'
                WHERE account.platform='telegram' AND lower(account.current_username) IN (:names)
                ORDER BY account.current_username COLLATE "C",alias.legacy_id LIMIT 10001
                """).param("names",CODES.keySet()).query((row,index)->new Channel(row.getObject(1,UUID.class),row.getObject(2,UUID.class),row.getString(3))).list();
            if(channels.size()>10000) throw new IllegalStateException("Official import account limit");
            Set<UUID> seenInstitutions=new HashSet<>();
            var institutions=new ArrayList<Map<String,Object>>();var accounts=new ArrayList<Map<String,Object>>();
            for(var channel:channels) {
                String code=CODES.get(OfficialRatingParser.casefold(channel.username()));
                if(code==null) continue;
                var telegram=dataset.rankings().get("telegram").get(code);
                if(telegram!=null) accounts.add(observation("accountId",channel.id(),null,telegram));
                if(seenInstitutions.add(channel.institution())) for(String category:java.util.List.of("social","telegram","vk","max","rutube"))
                    institutions.add(observation("institutionId",channel.institution(),category,dataset.rankings().get(category).get(code)));
            }
            Map<String,Object> payload=new LinkedHashMap<>();payload.put("period",dataset.period());payload.put("sourceUrl",dataset.sourceUrl());
            payload.put("sourceSha256",dataset.sourceSha256());payload.put("fetchedAt",dataset.fetchedAt().toString());payload.put("evidence",dataset.evidence());
            payload.put("available",dataset.rankings().get("social").size());payload.put("institutions",institutions);payload.put("accounts",accounts);
            String value=jdbc.sql("SELECT ops_and_admin.import_official_rating(CAST(:payload AS jsonb),:actor,:id)::text")
                .param("payload",JSON.writeValueAsString(payload)).param("actor",actor).param("id",correlation).query(String.class).single();
            return result(value);
        });
    }
    public void recordFailure(String actor,UUID correlation,String code) {
        if(!code.equals("official_source_unavailable")) throw new IllegalArgumentException("Invalid official source error code");
        transactions.executeWithoutResult(status->{
            jdbc.sql("""
                INSERT INTO ops_and_admin.operational_checkpoint(checkpoint_key,scope_type,value,correlation_id)
                VALUES('admin.m_rating','system',jsonb_build_object('period',NULL,'updatedAt',NULL,'error',CAST(:error AS text)),:id)
                ON CONFLICT(checkpoint_key,scope_type,scope_id,platform) DO UPDATE SET
                    value=ops_and_admin.operational_checkpoint.value||jsonb_build_object('error',CAST(:error AS text)),updated_at=transaction_timestamp(),correlation_id=:id
                """).param("error",code).param("id",correlation).update();
            jdbc.sql("""
                INSERT INTO ops_and_admin.audit_log(subject,action,target_type,correlation_id,after_state,outcome)
                VALUES(:actor,'official_rating.refresh','official_rating_import',:id,jsonb_build_object('errorCode',CAST(:error AS text)),'failed')
                """).param("actor",actor).param("id",correlation).param("error",code).update();
        });
    }
    private record Channel(UUID id,UUID institution,String username) { }
    private static Map<String,Object> observation(String targetKey,UUID target,String category,OfficialRating rating) {
        Map<String,Object> result=new LinkedHashMap<>();result.put(targetKey,target);if(category!=null) result.put("category",category);
        result.put("rank",rating==null?null:rating.rank());result.put("score",rating==null?null:rating.score());return result;
    }
    private static Result result(String value) {
        var node=JSON.readTree(value);if(node.path("outcome").asString("").equals("idempotency_conflict")) throw new AdminOptimisticLockException();
        return new Result(node.path("period").asString(),node.path("updated").asInt(),node.path("available").asInt(),node.path("fetchedAt").asString(),node.path("datasetRevision").longValue());
    }
    private static Map<String,String> loadCodes() {
        try(var input=JdbcOfficialRatingRepository.class.getResourceAsStream("/admin/official-m-rating-channel-codes.json")) {
            if(input==null) throw new IllegalStateException("Official institution code mapping is missing");
            Map<String,String> result=new LinkedHashMap<>();JSON.readTree(input).properties().forEach(property->result.put(property.getKey(),property.getValue().asString()));return Map.copyOf(result);
        } catch(java.io.IOException failure) { throw new IllegalStateException("Cannot read official institution codes",failure); }
    }
}
