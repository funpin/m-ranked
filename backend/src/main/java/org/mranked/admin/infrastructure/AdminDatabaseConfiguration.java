package org.mranked.admin.infrastructure;

import org.mranked.admin.application.AdminCommandRepository;
import org.mranked.admin.application.AdminQueryRepository;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AdminDatabaseProperties.class)
public class AdminDatabaseConfiguration {
    @Bean(destroyMethod="close")
    HttpOfficialRatingSource officialRatingSource(@org.springframework.beans.factory.annotation.Value("${mranked.admin.official-rating.enabled:true}") boolean enabled) {
        return new HttpOfficialRatingSource(enabled);
    }
    @Bean
    org.mranked.admin.application.OfficialRatingRepository officialRatingRepository(AdminJdbcContext context) {
        if(context.enabled()) return new JdbcOfficialRatingRepository(context.jdbcClient(),context.transactions());
        return new org.mranked.admin.application.OfficialRatingRepository() {
            public java.util.Optional<Result> previous(String actor,java.util.UUID id) { throw unavailable(); }
            public Result persist(org.mranked.admin.domain.OfficialRatingDataset dataset,String actor,java.util.UUID id) { throw unavailable(); }
            public void recordFailure(String actor,java.util.UUID id,String code) { throw unavailable(); }
            private RuntimeException unavailable() { return new org.mranked.admin.application.AdminDatabaseUnavailableException(); }
        };
    }
    @Bean
    org.mranked.admin.application.CatalogStatusPort catalogStatusPort(AdminJdbcContext context,
            org.mranked.query.application.ProviderConfiguration providers,
            @org.springframework.beans.factory.annotation.Value("${mranked.admin.project-directory:${user.dir}}") String project) {
        return context.enabled()?new JdbcCatalogStatus(context.jdbcClient(),providers,java.nio.file.Path.of(project)):
            ()->{throw new org.mranked.admin.application.AdminDatabaseUnavailableException();};
    }
    @Bean
    org.mranked.admin.application.CatalogRepository catalogRepository(AdminJdbcContext context,
            @org.springframework.beans.factory.annotation.Value("${mranked.admin.identity-receipt-directory:${MRANKED_IDENTITY_RECEIPT_DIR:data/identity-receipts}}") String receiptDirectory) {
        if(context.enabled()) return new JdbcCatalogRepository(context.jdbcClient(),context.transactions(),
            new IdentityCommandEvidence(java.nio.file.Path.of(receiptDirectory)));
        return new org.mranked.admin.application.CatalogRepository() {
            public java.util.List<org.mranked.admin.domain.ManagedInstitution> institutions(long after,int limit) { throw unavailable(); }
            public java.util.List<org.mranked.admin.domain.ManagedAccount> accounts(java.util.UUID institution,long after,int limit) { throw unavailable(); }
            public java.util.Optional<java.util.UUID> resolve(String type,long legacyId) { throw unavailable(); }
            public java.util.Optional<Long> version(String type,java.util.UUID id) { throw unavailable(); }
            public java.util.Optional<Long> parentLegacyId(java.util.UUID account) { throw unavailable(); }
            public <T> T atomic(java.util.function.Supplier<T> operation) { throw unavailable(); }
            public org.mranked.admin.domain.CatalogCommandResult command(String action,java.util.UUID target,Long version,
                    java.util.Map<String,Object> body,String actor,java.util.UUID correlation) { throw unavailable(); }
            private RuntimeException unavailable() { return new org.mranked.admin.application.AdminDatabaseUnavailableException(); }
        };
    }
    @Bean
    AdminJdbcContext adminJdbcContext(AdminDatabaseProperties properties) {
        if (!properties.enabled()) {
            return new AdminJdbcContext(null, null);
        }
        properties.validateEnabledConfiguration();
        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                properties.url(), properties.username(), properties.password()
        );
        dataSource.setDriverClassName("org.postgresql.Driver");
        return new AdminJdbcContext(
                JdbcClient.create(dataSource),
                new TransactionTemplate(new DataSourceTransactionManager(dataSource))
        );
    }

    @Bean
    AdminQueryRepository adminQueryRepository(AdminJdbcContext context) {
        return context.enabled()
                ? new JdbcAdminQueryRepository(context.jdbcClient())
                : new UnavailableAdminQueryRepository();
    }

    @Bean
    AdminCommandRepository adminCommandRepository(AdminJdbcContext context) {
        return context.enabled()
                ? new JdbcAdminCommandRepository(context.jdbcClient(), context.transactions())
                : new UnavailableAdminCommandRepository();
    }

    record AdminJdbcContext(JdbcClient jdbcClient, TransactionTemplate transactions) {
        boolean enabled() {
            return jdbcClient != null;
        }
    }
}
