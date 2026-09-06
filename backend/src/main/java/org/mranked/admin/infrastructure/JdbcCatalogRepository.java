package org.mranked.admin.infrastructure;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.sql.Types;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.application.CatalogRepository;
import org.mranked.admin.domain.CatalogCommandResult;
import org.mranked.admin.domain.ManagedInstitution;
import org.springframework.jdbc.CannotGetJdbcConnectionException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.json.JsonMapper;

public final class JdbcCatalogRepository implements CatalogRepository {
    private static final JsonMapper JSON=new JsonMapper();
    private final JdbcClient jdbc;
    private final TransactionOperations transactions;
    private final IdentityCommandEvidence identityEvidence;
    public JdbcCatalogRepository(JdbcClient jdbc,TransactionOperations transactions) { this(jdbc,transactions,IdentityCommandEvidence.configured()); }
    public JdbcCatalogRepository(JdbcClient jdbc,TransactionOperations transactions,IdentityCommandEvidence identityEvidence) {
        this.jdbc=jdbc; this.transactions=transactions; this.identityEvidence=identityEvidence;
    }
    static final String CATALOG_SQL="""
        WITH page AS MATERIALIZED (
            SELECT institution.*,alias.legacy_id FROM catalog.visible_institution institution
            JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=institution.id AND alias.entity_type='institutions'
            WHERE alias.legacy_id>:after ORDER BY alias.legacy_id LIMIT :limit
        ), account_rows AS (
            SELECT account.institution_id,alias.legacy_id,row_number() OVER(PARTITION BY account.institution_id ORDER BY alias.legacy_id) AS ordinal,
                jsonb_build_object('id',account.id,'legacyId',alias.legacy_id,
                'channelId',channel.legacy_id,'institutionId',account.institution_id,'platform',account.platform,
                'externalKey',account.canonical_external_id,'username',account.current_username,'title',account.current_title,
                'url',account.current_url,'accessMode',account.access_mode,'enabled',account.enabled,'rowVersion',account.row_version,
                'nativeId',native.external_id,'subscribers',metric.value,
                'legacyAccessMode',presentation.access_mode,'lastErrorCode',presentation.last_error_code) AS item
            FROM page JOIN LATERAL (SELECT candidate.* FROM catalog.visible_platform_account candidate
                JOIN catalog.legacy_entity_alias candidate_alias ON candidate_alias.target_uuid=candidate.id AND candidate_alias.entity_type='platform_accounts'
                WHERE candidate.institution_id=page.id ORDER BY candidate_alias.legacy_id LIMIT 51) account ON true
            JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id AND alias.entity_type='platform_accounts'
            LEFT JOIN catalog.legacy_entity_alias channel ON channel.target_uuid=account.id AND channel.entity_type='channels'
            LEFT JOIN catalog.account_external_identity native ON native.platform_account_id=account.id
                AND native.identity_namespace=account.platform::text||':native_id' AND native.valid_to IS NULL
            LEFT JOIN analytics.account_latest metric ON metric.platform_account_id=account.id AND metric.metric_key='subscribers'
            LEFT JOIN LATERAL ops_and_admin.legacy_account_presentation(account.id) presentation ON true
        ), accounts AS (
            SELECT institution_id,jsonb_agg(item ORDER BY legacy_id) FILTER(WHERE ordinal<=50) AS items,
                CASE WHEN count(*)>50 THEN max(legacy_id) FILTER(WHERE ordinal=50) END AS next_after
            FROM account_rows GROUP BY institution_id
        ) SELECT jsonb_build_object('id',page.id,'legacyId',page.legacy_id,'name',page.canonical_name,
            'shortName',page.short_name,'rowVersion',page.row_version,'accounts',coalesce(accounts.items,'[]'::jsonb),
            'nextAccountAfter',accounts.next_after,'officialRatings',ratings.items)::text
        FROM page LEFT JOIN accounts ON accounts.institution_id=page.id
        CROSS JOIN LATERAL (
            SELECT jsonb_object_agg(category.key,jsonb_build_object('rank',observation.rank,'score',observation.score)) AS items
            FROM (VALUES('all','social'),('telegram','telegram'),('vk','vk'),('max','max'),('rutube','rutube')) category(key,source)
            LEFT JOIN LATERAL (SELECT rank,score FROM rating.official_institution_rating_observation
                WHERE institution_id=page.id AND category=category.source ORDER BY fetched_at DESC,id DESC LIMIT 1) observation ON true
        ) ratings ORDER BY page.legacy_id
        """;
    static final String ACCOUNTS_SQL="""
        SELECT jsonb_build_object('id',account.id,'legacyId',alias.legacy_id,'channelId',channel.legacy_id,
            'institutionId',account.institution_id,'platform',account.platform,'externalKey',account.canonical_external_id,
            'username',account.current_username,'title',account.current_title,'url',account.current_url,'accessMode',account.access_mode,
            'enabled',account.enabled,'rowVersion',account.row_version,'nativeId',native.external_id,'subscribers',metric.value,
            'legacyAccessMode',presentation.access_mode,'lastErrorCode',presentation.last_error_code)::text
        FROM catalog.visible_platform_account account
        JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id AND alias.entity_type='platform_accounts'
        LEFT JOIN catalog.legacy_entity_alias channel ON channel.target_uuid=account.id AND channel.entity_type='channels'
        LEFT JOIN catalog.account_external_identity native ON native.platform_account_id=account.id
            AND native.identity_namespace=account.platform::text||':native_id' AND native.valid_to IS NULL
        LEFT JOIN analytics.account_latest metric ON metric.platform_account_id=account.id AND metric.metric_key='subscribers'
        LEFT JOIN LATERAL ops_and_admin.legacy_account_presentation(account.id) presentation ON true
        WHERE account.institution_id=:institution AND alias.legacy_id>:after ORDER BY alias.legacy_id LIMIT :limit
        """;
    @Override public List<ManagedInstitution> institutions(long after,int limit) {
        return jdbc.sql(CATALOG_SQL).param("after",after).param("limit",limit)
            .query((row,index)->JSON.readValue(row.getString(1),ManagedInstitution.class)).list();
    }
    @Override public List<org.mranked.admin.domain.ManagedAccount> accounts(UUID institution,long after,int limit) {
        return jdbc.sql(ACCOUNTS_SQL).param("institution",institution).param("after",after).param("limit",limit)
            .query((row,index)->JSON.readValue(row.getString(1),org.mranked.admin.domain.ManagedAccount.class)).list();
    }
    @Override public Optional<UUID> resolve(String type,long legacyId) {
        return jdbc.sql("SELECT target_uuid FROM catalog.legacy_entity_alias WHERE entity_type=:type AND legacy_id=:id")
            .param("type",type).param("id",legacyId).query(UUID.class).optional();
    }
    @Override public Optional<Long> version(String type,UUID id) {
        String table=switch(type) { case "institutions"->"catalog.visible_institution";
            case "channels","platform_accounts"->"catalog.visible_platform_account";
            default->throw new IllegalArgumentException("Invalid catalog type"); };
        return jdbc.sql("SELECT row_version FROM "+table+" WHERE id=:id").param("id",id).query(Long.class).optional();
    }
    @Override public Optional<Long> parentLegacyId(UUID id) {
        return jdbc.sql("SELECT alias.legacy_id FROM catalog.visible_platform_account account JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.institution_id AND alias.entity_type='institutions' WHERE account.id=:id")
            .param("id",id).query(Long.class).optional();
    }
    @Override public <T> T atomic(java.util.function.Supplier<T> operation) {
        return transactions.execute(status->operation.get());
    }
    @Override public CatalogCommandResult command(String action,UUID target,Long version,Map<String,Object> body,String actor,UUID correlation) {
        try {
            return transactions.execute(status -> {
                // PostgreSQL's JSONB encoding is the existing receipt digest
                // protocol. This serializes original inputs, never target rows.
                String original=jdbc.sql("SELECT jsonb_build_object('action',CAST(:action AS text),'target',CAST(:target AS uuid),'expected',CAST(:version AS bigint),'body',CAST(:body AS jsonb))::text")
                    .param("action",action).param("target",target,Types.OTHER).param("version",version,Types.BIGINT)
                    .param("body",JSON.writeValueAsString(body)).query(String.class).single();
                identityEvidence.persist(original);
                String json=jdbc.sql("SELECT ops_and_admin.catalog_command(:action,:target,:version,CAST(:body AS jsonb),:actor,:correlation)::text")
                    .param("action",action).param("target",target,Types.OTHER).param("version",version,Types.BIGINT)
                    .param("body",JSON.writeValueAsString(body)).param("actor",actor).param("correlation",correlation)
                    .query(String.class).single();
                var result=JSON.readTree(json);
                return new CatalogCommandResult(result.path("outcome").asString(),uuid(result.path("targetId")),
                    number(result.path("legacyId")),number(result.path("datasetRevision")),
                    number(result.path("state").path("row_version")),correlation);
            });
        } catch(CannotGetJdbcConnectionException failure) { throw new AdminDatabaseUnavailableException(); }
    }
    private static UUID uuid(tools.jackson.databind.JsonNode value) { return value.isTextual()?UUID.fromString(value.asString()):null; }
    private static Long number(tools.jackson.databind.JsonNode value) { return value.isNumber()?value.longValue():null; }
}
