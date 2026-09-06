package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.sql.DriverManager;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

@EnabledIfEnvironmentVariable(named="MRANKED_CATALOG_TEST_POSTGRES_URL",matches=".+")
class LegacyAccountPresentationPostgresIntegrationTest {
    private static final tools.jackson.databind.json.JsonMapper JSON=new tools.jackson.databind.json.JsonMapper();
    private java.sql.Connection owner() throws Exception {
        return DriverManager.getConnection(System.getenv("MRANKED_CATALOG_TEST_POSTGRES_URL"),
            System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"));
    }
    private record Presentation(String mode,String error,boolean present) { }
    private static Presentation presentation(JdbcClient jdbc,UUID account) {
        return jdbc.sql("SELECT * FROM ops_and_admin.legacy_account_presentation(:account)").param("account",account)
            .query((row,index)->new Presentation(row.getString("access_mode"),row.getString("last_error_code"),row.getBoolean("error_present"))).optional().orElse(null);
    }

    @Test void preservedLabelsAreFiniteAndBoundToTheirOwnCurrentSemanticAccountContext() throws Exception {
        try(var connection=owner()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));var fixture=new Fixture(jdbc);
                String[][] modes={{"public","telegram","public_web"},{"public_api","rutube","public_api"},
                    {"official_api","vk","official_api"},{"public_web","telegram","public_web"},
                    {"telegram_web","telegram","telegram_web"},{"user_session","max","user_session"},
                    {"owner","max","user_session"},{"mtproto","telegram","mtproto"},
                    {"api","vk","official_api"},{"official","vk","official_api"},{"user","max","user_session"},
                    {"user_api","max","user_session"},{"disabled","max","disabled"}};
                for(String[] mode:modes) {
                    UUID account=fixture.account(mode[1],mode[2]);fixture.source(account,mode[0],false);
                    assertThat(presentation(jdbc,account)).isEqualTo(new Presentation(mode[0],null,false));
                }
                UUID other=fixture.account("rutube","public_api");fixture.source(other,"password=private-source",true);
                assertThat(presentation(jdbc,other)).isEqualTo(new Presentation("public","legacy_collection_error",true));
                UUID changed=fixture.account("rutube","public_api");fixture.source(changed,"public_api",false);
                jdbc.sql("UPDATE catalog.platform_account SET access_mode='user_session' WHERE id=:id").param("id",changed).update();
                assertThat(presentation(jdbc,changed)).isEqualTo(new Presentation("user_session",null,false));
                assertThat(presentation(jdbc,UUID.randomUUID())).isNull();
            } finally {connection.rollback();}
        }
    }

    @Test void rowHashAndLatestBatchBindingPreventStaleErrorOrModeLeakage() throws Exception {
        try(var connection=owner()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));var fixture=new Fixture(jdbc);
                UUID account=fixture.account("rutube","public_api");fixture.source(account,"public_api",true);
                assertThat(presentation(jdbc,account)).isEqualTo(new Presentation("public_api","legacy_collection_error",true));
                jdbc.sql("UPDATE migration.legacy_identity_map SET source_row_hash=repeat('b',64) WHERE target_uuid=:account").param("account",account).update();
                assertThat(presentation(jdbc,account)).isEqualTo(new Presentation("public",null,false));
                jdbc.sql("UPDATE migration.legacy_identity_map SET source_row_hash=repeat('a',64),last_seen_batch_id=:batch WHERE target_uuid=:account")
                    .param("batch",fixture.batch()).param("account",account).update();
                assertThat(presentation(jdbc,account)).isEqualTo(new Presentation("public",null,false));
                UUID cleared=fixture.account("vk","official_api");String pk=fixture.source(cleared,"api",false);
                jdbc.sql("INSERT INTO migration.legacy_evidence(batch_id,source_table,source_pk,source_row_hash,evidence_kind,evidence) VALUES(:batch,'platform_accounts',:pk,repeat('a',64),'sanitized_last_error','{\"present\":true}')")
                    .param("batch",fixture.batch).param("pk",pk).update();
                assertThat(presentation(jdbc,cleared)).isEqualTo(new Presentation("api",null,false));
            } finally {connection.rollback();}
        }
    }

    @Test void nativeDefaultsRemainPublicLabelsWithoutInventingLegacyErrorText() throws Exception {
        try(var connection=owner()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));var fixture=new Fixture(jdbc);
                for(String[] pair:new String[][]{{"vk","official_api"},{"rutube","public_api"},{"telegram","public_web"}})
                    assertThat(presentation(jdbc,fixture.account(pair[0],pair[1]))).isEqualTo(new Presentation("public",null,false));
                assertThat(presentation(jdbc,fixture.account("max","user_session"))).isEqualTo(new Presentation("user_session",null,false));
                UUID account=fixture.account("vk","official_api");fixture.source(account,"official_api",true);
                assertThat(presentation(jdbc,account).toString()).doesNotContain("private-source","password","sha256","length");
            } finally {connection.rollback();}
        }
    }

    @Test void onlyAdministrativeDatabaseRoleCanExecuteAndRawEvidenceRemainsPrivate() throws Exception {
        for(String role:List.of("api_read","api_write_admin")) {
            String password=System.getenv(role.equals("api_read")?"MRANKED_QUERY_TEST_PASSWORD":"MRANKED_ADMIN_TEST_PASSWORD");
            try(var connection=DriverManager.getConnection(System.getenv("MRANKED_CATALOG_TEST_POSTGRES_URL"),role,password)) {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
                assertThat(jdbc.sql("SELECT has_function_privilege(current_user,'ops_and_admin.legacy_account_presentation(uuid)','EXECUTE')").query(Boolean.class).single())
                    .isEqualTo(role.equals("api_write_admin"));
                if(role.equals("api_write_admin")) assertThat(presentation(jdbc,UUID.randomUUID())).isNull();
                else assertThatThrownBy(()->connection.createStatement().executeQuery("SELECT * FROM ops_and_admin.legacy_account_presentation(gen_random_uuid())"))
                    .isInstanceOf(java.sql.SQLException.class).satisfies(error->assertThat(((java.sql.SQLException)error).getSQLState()).isEqualTo("42501"));
                assertThatThrownBy(()->connection.createStatement().executeQuery("SELECT evidence FROM migration.legacy_evidence LIMIT 1"))
                    .isInstanceOf(java.sql.SQLException.class).satisfies(error->assertThat(((java.sql.SQLException)error).getSQLState()).isEqualTo("42501"));
            }
        }
    }

    private static final class Fixture {
        final JdbcClient jdbc;final UUID institution=UUID.randomUUID(),namespace=UUID.randomUUID(),batch;
        int key;
        Fixture(JdbcClient jdbc) {
            this.jdbc=jdbc;batch=batch();
            jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES(:id,'Admin presentation fixture')").param("id",institution).update();
        }
        UUID batch() {
            UUID result=UUID.randomUUID();
            jdbc.sql("INSERT INTO migration.import_batch(id,source_name,source_file_name,source_size_bytes,source_sha256,source_schema_version,snapshot_kind,tool_version,status) VALUES(:id,:name,'presentation.db',0,repeat('a',64),1,'fixture','integration','succeeded')")
                .param("id",result).param("name",result.toString()).update();return result;
        }
        UUID account(String platform,String mode) {
            UUID result=UUID.randomUUID();
            jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES(:id,:institution,CAST(:platform AS catalog.platform_code),:external,CAST(:mode AS catalog.access_mode))")
                .param("id",result).param("institution",institution).param("platform",platform).param("external",result.toString()).param("mode",mode).update();return result;
        }
        String source(UUID account,String mode,boolean error) {
            String pk=Integer.toString(++key);
            jdbc.sql("INSERT INTO migration.legacy_identity_map(source_namespace,source_table,source_pk,target_type,target_uuid,natural_key,source_row_hash,first_batch_id,last_seen_batch_id) VALUES(:namespace,'platform_accounts',:pk,'platform_account',:account,'{}',repeat('a',64),:batch,:batch)")
                .param("namespace",namespace).param("pk",pk).param("account",account).param("batch",batch).update();
            String body=JSON.writeValueAsString(Map.of("access_mode",mode,"last_error",Map.of("present",error,"length",error?25:0,"sha256","a".repeat(64),"raw","password=private-source")));
            jdbc.sql("INSERT INTO migration.legacy_evidence(batch_id,source_table,source_pk,source_row_hash,evidence_kind,evidence) VALUES(:batch,'platform_accounts',:pk,repeat('a',64),'legacy_account_presentation',CAST(:body AS jsonb))")
                .param("batch",batch).param("pk",pk).param("body",body).update();return pk;
        }
    }
}
