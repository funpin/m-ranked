package org.mranked.admin.application;

import static org.assertj.core.api.Assertions.*;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mranked.admin.domain.CatalogCommandResult;
import org.mranked.admin.domain.ManagedAccount;
import org.mranked.admin.domain.ManagedInstitution;

class LegacyCatalogServiceTest {
    private final Repository repository=new Repository();
    private final LegacyCatalogService legacy=new LegacyCatalogService(new CatalogService(repository),repository,null);
    private String execute(String path,Map<String,String> fields) { return legacy.execute(path,fields,"fixture-user",UUID.randomUUID()); }

    @Test void fixedValidationMessagesArePublicButArbitraryExceptionsAreNeverEchoed() {
        assertThatThrownBy(()->execute("/manage/institutions",Map.of("name"," ")))
            .isInstanceOf(LegacyFormException.class).hasMessage("Укажите название вуза");
        assertThatThrownBy(()->execute("/manage/channels",Map.of("channel","bad!")))
            .isInstanceOf(LegacyFormException.class).hasMessage("Invalid Telegram channel username");
        assertThatThrownBy(()->execute("/manage/institutions/7",Map.of("name","a","short_name","")))
            .isInstanceOf(LegacyFormException.class).hasMessage("Institution name and short name are required");
        assertThat(LegacyFormException.safe("database-password=secret").getMessage()).isEqualTo("One or more request parameters are invalid");
        assertThat(LegacyFormException.safe(null).getMessage()).doesNotContain("null");
        assertThat(repository.commands).isZero();
    }

    @Test void exactMissingResourceTextsAreSelectedByLegacyRoute() {
        repository.missing=true;
        assertThatThrownBy(()->execute("/manage/institutions/7",Map.of("name","a","short_name","b"))).hasMessage("Вуз не найден");
        assertThatThrownBy(()->execute("/manage/channels/7/enable",Map.of())).hasMessage("Канал не найден");
        assertThatThrownBy(()->execute("/manage/platform-accounts/7/enable",Map.of())).hasMessage("Аккаунт не найден");
        assertThat(repository.commands).isZero();
    }

    @Test void platformValidationPrecedesInstitutionLookupAsInLegacy() {
        assertThatThrownBy(()->execute("/manage/platform-accounts",Map.of("institution_id","0","platform","unsupported","reference","a")))
            .isInstanceOf(LegacyFormException.class).hasMessage("Telegram-каналы добавляются через основную форму мониторинга");
        assertThatThrownBy(()->execute("/manage/platform-accounts",Map.of("institution_id","0","platform","max","reference","a")))
            .isInstanceOf(AdminResourceNotFoundException.class).hasMessage("Вуз не найден");
    }

    @Test void maxNativeIdIsValidatedBeforeSqlWhileOtherPlatformsKeepTextAndEmptyClears() {
        assertThatThrownBy(()->execute("/manage/platform-accounts/7/native-id",Map.of("native_id","not-a-number")))
            .isInstanceOf(LegacyFormException.class).hasMessage("MAX chat_id должен быть числом");
        assertThat(repository.commands).isZero();
        assertThat(execute("/manage/platform-accounts/7/native-id",Map.of("native_id","-12345"))).contains("native-id-updated");
        assertThat(execute("/manage/platform-accounts/7/native-id",Map.of("native_id",""))).contains("native-id-updated");
        repository.platform="vk";
        assertThat(execute("/manage/platform-accounts/7/native-id",Map.of("native_id","some-name"))).contains("native-id-updated");
        assertThat(repository.commands).isEqualTo(3);
    }

    @Test void staleVersionAndIdempotencyConflictRetainTheirDistinctConflictType() {
        repository.outcome="version_conflict";
        assertThatThrownBy(()->execute("/manage/platform-accounts/7/disable",Map.of("expected_row_version","8")))
            .isInstanceOf(AdminOptimisticLockException.class);
        assertThat(repository.expectedVersion).isEqualTo(8);
        repository.outcome="idempotency_conflict";
        assertThatThrownBy(()->execute("/manage/institutions",Map.of("name","fixture")))
            .isInstanceOf(AdminOptimisticLockException.class);
    }

    private static final class Repository implements CatalogRepository {
        final UUID institution=UUID.randomUUID(),account=UUID.randomUUID();
        boolean missing; int commands; String platform="max",outcome="succeeded"; Long expectedVersion;
        public List<ManagedInstitution> institutions(long after,int limit) { return List.of(); }
        public List<ManagedAccount> accounts(UUID parent,long after,int limit) {
            assertThat(parent).isEqualTo(institution); assertThat(after).isEqualTo(6); assertThat(limit).isOne();
            return List.of(new ManagedAccount(account,7,null,institution,platform,"fixture","fixture",null,null,"public",true,0,null,null,"public",null));
        }
        public Optional<UUID> resolve(String type,long id) { return missing?Optional.empty():Optional.of(type.equals("institutions")?institution:account); }
        public Optional<Long> version(String type,UUID id) { return Optional.of(0L); }
        public Optional<Long> parentLegacyId(UUID id) { return Optional.of(9L); }
        public <T> T atomic(java.util.function.Supplier<T> operation) { return operation.get(); }
        public CatalogCommandResult command(String action,UUID target,Long version,Map<String,Object> body,String actor,UUID correlation) {
            commands++; expectedVersion=version;
            return new CatalogCommandResult(outcome,target==null?institution:target,7L,1L,1L,correlation);
        }
    }
}
