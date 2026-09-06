package org.mranked.admin.infrastructure;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.LinkOption;
import java.util.List;
import org.mranked.admin.application.CatalogStatusPort;
import org.mranked.admin.domain.CatalogStatus;
import org.mranked.analytics.domain.Platform;
import org.mranked.query.application.ProviderConfiguration;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.json.JsonMapper;

final class JdbcCatalogStatus implements CatalogStatusPort {
    private final JdbcClient jdbc;
    private final ProviderConfiguration providers;
    private final Path project;
    private long sampledAt;
    private Long projectBytes;
    JdbcCatalogStatus(JdbcClient jdbc,ProviderConfiguration providers,Path project) { this.jdbc=jdbc;this.providers=providers;this.project=project; }
    public CatalogStatus status() {
        var row=jdbc.sql("""
            SELECT (SELECT count(*) FROM catalog.visible_platform_account account JOIN catalog.legacy_entity_alias alias
                    ON alias.target_uuid=account.id AND alias.entity_type='channels') AS channels,
                (SELECT count(*) FROM catalog.visible_platform_account) AS accounts,
                (SELECT count(*) FROM catalog.visible_institution) AS institutions,
                (SELECT count(*) FROM catalog.visible_platform_account WHERE platform='max') AS max_accounts,
                (SELECT count(*) FROM catalog.visible_platform_account account
                    JOIN catalog.account_external_identity native ON native.platform_account_id=account.id
                      AND native.identity_namespace='max:native_id' AND native.valid_to IS NULL
                    WHERE account.platform='max' AND native.external_id<>'') AS max_native_ids,
                pg_database_size(current_database()) AS database_bytes,
                coalesce((SELECT value FROM ops_and_admin.operational_checkpoint WHERE checkpoint_key='admin.m_rating' AND scope_type='system'),
                    jsonb_build_object(
                        'period',(SELECT value#>>'{}' FROM ops_and_admin.operational_checkpoint WHERE checkpoint_key='m_rating_last_period' AND scope_type='system'),
                        'updatedAt',(SELECT value#>>'{}' FROM ops_and_admin.operational_checkpoint WHERE checkpoint_key='m_rating_last_updated' AND scope_type='system'),
                        'error',CASE WHEN EXISTS(SELECT 1 FROM ops_and_admin.operational_checkpoint WHERE checkpoint_key='m_rating_last_error'
                            AND scope_type='system' AND value->>'present'='true') THEN 'legacy_source_error' ELSE NULL END))::text AS rating
            """).query((result,index)->new Object[]{result.getLong("channels"),result.getLong("accounts"),result.getLong("institutions"),result.getLong("database_bytes"),result.getString("rating"),result.getLong("max_accounts"),result.getLong("max_native_ids")}).single();
        Long total=null,free=null;
        try { var store=Files.getFileStore(project);total=store.getTotalSpace();free=store.getUsableSpace(); } catch(java.io.IOException ignored) { }
        var integrations=List.of(
            new CatalogStatus.Integration("telegram",providers.status(Platform.TELEGRAM),"Публичный HTML-источник"),
            new CatalogStatus.Integration("vk",providers.status(Platform.VK),"VK_ACCESS_TOKEN · просмотры, лайки, комментарии, репосты"),
            new CatalogStatus.Integration("max",providers.status(Platform.MAX),"Пользовательская сессия · chat_id определён у "+row[6]+" из "+row[5]+" аккаунтов"),
            new CatalogStatus.Integration("rutube",providers.status(Platform.RUTUBE),"Официальные публичные API · токен не требуется · просмотры, лайки, комментарии"));
        return new CatalogStatus((Long)row[0],(Long)row[1],(Long)row[2],new JsonMapper().readValue((String)row[4],CatalogStatus.MRating.class),
            integrations,new CatalogStatus.Storage(total,free,projectSize(),(Long)row[3]));
    }
    /** Filesystem failures, limits or slow walks produce unknown, never a partial total. */
    private synchronized Long projectSize() {
        long now=System.nanoTime();
        if(sampledAt!=0 && now-sampledAt<300_000_000_000L) return projectBytes;
        sampledAt=now;projectBytes=null;
        try(var paths=Files.walk(project)) {
            var iterator=paths.iterator();long total=0;int count=0;
            while(iterator.hasNext()) {
                Path path=iterator.next();
                if(++count>250_000 || System.nanoTime()-now>500_000_000L) return null;
                if(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)) total=Math.addExact(total,Files.size(path));
            }
            projectBytes=total;
        } catch(java.io.IOException|java.io.UncheckedIOException|ArithmeticException ignored) { }
        return projectBytes;
    }
}
