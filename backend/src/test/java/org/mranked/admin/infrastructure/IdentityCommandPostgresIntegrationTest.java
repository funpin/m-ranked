package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.nio.file.*;
import java.net.URI;
import java.sql.DriverManager;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mranked.testing.FinalSchemaInstaller;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.admin.application.CatalogService;
import org.mranked.admin.application.AdminOptimisticLockException;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.json.JsonMapper;

@EnabledIfEnvironmentVariable(named="MRANKED_EXPORT_TEST_ADMIN_URL",matches=".+")
class IdentityCommandPostgresIntegrationTest {
    @TempDir Path output;
    @Test
    void originalJavaCommandsSurviveReverseSecondSFinalAndNoOpReplay() throws Exception {
        output=output.toRealPath();
        String initial=System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");var base=URI.create(initial.substring(5));
        assertThat(base.getHost()).isIn("127.0.0.1","localhost");assertThat(base.getPath()).endsWith("_it");
        String name="mranked_identity_command_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:postgresql://"+base.getHost()+":"+base.getPort()+"/"+name;
        String ownerName=System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"),ownerPassword=System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        Path root=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        Path receipts=output.resolve("receipts");
        try(var control=DriverManager.getConnection(initial,ownerName,ownerPassword)) {
            control.createStatement().execute("CREATE DATABASE "+name+" OWNER migration_owner");
            try {
                FinalSchemaInstaller.install(url, ownerName, ownerPassword);
                runPython(root,base,name,receipts,"prepare");
                var ids=new JsonMapper().readTree(Files.readString(output.resolve("controls.json")));
                UUID account=UUID.fromString(ids.path("accountId").asString()),institution=UUID.fromString(ids.path("institutionId").asString());
                long initialVersion=ids.path("rowVersion").asLong();
                var source=new DriverManagerDataSource(url,"api_write_admin",System.getenv("MRANKED_ADMIN_TEST_PASSWORD"));
                var jdbc=JdbcClient.create(source);var transaction=new TransactionTemplate(new DataSourceTransactionManager(source));
                var repository=new JdbcCatalogRepository(jdbc,transaction,new IdentityCommandEvidence(receipts));
                var service=new CatalogService(repository);
                var owner=JdbcClient.create(new DriverManagerDataSource(url,ownerName,ownerPassword));
                String actor="original-command-fixture";
                UUID rolledBack=UUID.randomUUID();
                assertThatThrownBy(()->repository.atomic(()->{
                    service.upsertAccount(institution,initialVersion,"max","history_input","Must roll back",null,actor,rolledBack);
                    throw new IllegalStateException("injected rollback");
                })).isInstanceOf(IllegalStateException.class);
                assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.catalog_command_receipt WHERE correlation_id=:id").param("id",rolledBack).query(Integer.class).single()).isZero();
                Path unavailable=output.resolve("unavailable");Files.createDirectories(unavailable);Files.writeString(unavailable.resolve("admin"),"not a directory");
                var blocked=new JdbcCatalogRepository(jdbc,transaction,new IdentityCommandEvidence(unavailable));
                UUID refused=UUID.randomUUID();
                assertThatThrownBy(()->blocked.command("account.native_id",account,initialVersion,Map.of("nativeId","-999"),actor,refused)).isInstanceOf(IllegalStateException.class);
                assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.catalog_command_receipt WHERE correlation_id=:id").param("id",refused).query(Integer.class).single()).isZero();
                var presentation=service.upsertAccount(institution,initialVersion,"max","history_input","Original command title","http://max.ru/history_input",actor,UUID.randomUUID());
                assertThat(presentation.targetId()).isEqualTo(account);
                UUID repeated=UUID.randomUUID();
                var nativeId=service.accountCommand(account,presentation.rowVersion(),"native_id","-20001",actor,repeated);
                assertThat(service.accountCommand(account,presentation.rowVersion(),"native_id","-20001",actor,repeated)).isEqualTo(nativeId);
                assertThatThrownBy(()->service.accountCommand(account,presentation.rowVersion(),"native_id","-20001","another-actor",UUID.randomUUID())).isInstanceOf(AdminOptimisticLockException.class);
                var changed=service.accountCommand(account,nativeId.rowVersion(),"native_id","-20002",actor,UUID.randomUUID());
                var cleared=service.accountCommand(account,changed.rowVersion(),"native_id",null,actor,UUID.randomUUID());
                assertThat(owner.sql("SELECT count(*) FROM catalog.account_external_identity WHERE platform_account_id=:id AND valid_to IS NULL").param("id",account).query(Integer.class).single()).isZero();
                var reenrolled=service.accountCommand(account,cleared.rowVersion(),"native_id","-20003",actor,UUID.randomUUID());
                assertThat(owner.sql("SELECT (SELECT valid_from FROM catalog.account_external_identity WHERE platform_account_id=:id AND valid_to IS NULL) > (SELECT max(valid_to) FROM catalog.account_external_identity WHERE platform_account_id=:id)").param("id",account).query(Boolean.class).single()).isTrue();
                service.accountCommand(account,reenrolled.rowVersion(),"native_id",null,actor,UUID.randomUUID());
                runPython(root,base,name,receipts,"collector-gap");
                assertThat(owner.sql("SELECT current_username FROM catalog.platform_account WHERE id=:id").param("id",account).query(String.class).single()).isEqualTo("history_input");
                assertThat(owner.sql("SELECT current_url FROM catalog.platform_account WHERE id=:id").param("id",account).query(String.class).single()).isEqualTo("http://max.ru/history_input");
                runPython(root,base,name,receipts,"verify");
                var proof=new JsonMapper().readTree(Files.readString(output.resolve("proof.json")));
                assertThat(proof.path("status").asString()).isEqualTo("pass");
                assertThat(proof.path("history").path("checks").get(0).path("expected").path("rows").asInt()).isEqualTo(3);
                assertThat(proof.path("history").path("checks").get(1).path("expected").path("rows").asInt()).isEqualTo(5);
                if(System.getenv("MRANKED_IDENTITY_COMMAND_PROOF")!=null) {
                    Path destination=Path.of(System.getenv("MRANKED_IDENTITY_COMMAND_PROOF"));
                    Files.copy(output.resolve("proof.json"),destination);
                }
            } finally { control.createStatement().execute("DROP DATABASE "+name+" WITH (FORCE)"); }
        }
    }
    private void runPython(Path root,URI base,String name,Path receipts,String phase) throws Exception {
        var builder=new ProcessBuilder(org.mranked.testing.IntegrationRuntime.python(root),"-m","migration.integration.identity_command_fixture",phase,
            "--directory",output.toString()).directory(root.toFile()).redirectErrorStream(true);
        builder.environment().put("BRIDGE_DATABASE_URL","host="+base.getHost()+" port="+base.getPort()+" dbname="+name+" user=migration_bridge password="+System.getenv("MRANKED_LEGACY_CSV_BRIDGE_PASSWORD"));
        builder.environment().put("MRANKED_IDENTITY_RECEIPT_DIR",receipts.toString());
        builder.environment().put("COLLECTOR_DATABASE_URL","host="+base.getHost()+" port="+base.getPort()+" dbname="+name+" user=collector_ingest password="+System.getenv("MRANKED_LEGACY_CSV_COLLECTOR_PASSWORD"));
        var process=builder.start();String log=new String(process.getInputStream().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
        assertThat(process.waitFor()).as(log).isZero();
    }
}
