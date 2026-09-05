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
