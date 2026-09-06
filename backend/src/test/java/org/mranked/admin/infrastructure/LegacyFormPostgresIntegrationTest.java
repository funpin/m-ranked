package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.admin.application.CatalogService;
import org.mranked.admin.application.LegacyCatalogService;
import org.mranked.admin.application.LegacyFormException;
import org.mranked.admin.application.AdminResourceNotFoundException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@EnabledIfEnvironmentVariable(named="MRANKED_CATALOG_TEST_POSTGRES_URL",matches=".+")
class LegacyFormPostgresIntegrationTest {
    @Test void invalidMaxNativeIdNeverReachesDatabaseAndValidRetryPreservesCas() {
        var source=new DriverManagerDataSource(System.getenv("MRANKED_CATALOG_TEST_POSTGRES_URL"),"api_write_admin",System.getenv("MRANKED_ADMIN_TEST_PASSWORD"));
        var repository=new JdbcCatalogRepository(JdbcClient.create(source),new TransactionTemplate(new DataSourceTransactionManager(source)));
        var catalog=new CatalogService(repository); var legacy=new LegacyCatalogService(catalog,repository,null);
        String actor="legacy-form-it-"+UUID.randomUUID();
        var institution=catalog.createInstitution("Form verifier","FV",actor,UUID.randomUUID());
        var account=catalog.upsertAccount(institution.targetId(),null,"max","form_"+UUID.randomUUID(),null,null,actor,UUID.randomUUID());
        String path="/manage/platform-accounts/"+account.legacyId()+"/native-id";
        var owner=JdbcClient.create(new DriverManagerDataSource(System.getenv("MRANKED_CATALOG_TEST_POSTGRES_URL"),
            System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD")));
        long before=owner.sql("SELECT count(*) FROM ops_and_admin.audit_log WHERE subject=:actor").param("actor",actor).query(Long.class).single();
        UUID correlation=UUID.randomUUID();
        assertThatThrownBy(()->legacy.execute(path,Map.of("native_id","not-a-number","expected_row_version","0"),actor,correlation))
            .isInstanceOf(LegacyFormException.class).hasMessage("MAX chat_id должен быть числом");
        assertThat(repository.version("platform_accounts",account.targetId())).contains(0L);
        assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.audit_log WHERE subject=:actor").param("actor",actor).query(Long.class).single()).isEqualTo(before);
        assertThat(legacy.execute(path,Map.of("native_id","-123456","expected_row_version","0"),actor,correlation)).contains("native-id-updated");
        assertThat(repository.version("platform_accounts",account.targetId())).contains(1L);
        assertThatThrownBy(()->legacy.execute("/manage/platform-accounts/9223372036854775807/enable",Map.of(),actor,UUID.randomUUID()))
            .isInstanceOf(AdminResourceNotFoundException.class).hasMessage("Аккаунт не найден");
        assertThatThrownBy(()->legacy.execute("/manage/channels/9223372036854775807/enable",Map.of(),actor,UUID.randomUUID()))
            .isInstanceOf(AdminResourceNotFoundException.class).hasMessage("Канал не найден");
    }
}
