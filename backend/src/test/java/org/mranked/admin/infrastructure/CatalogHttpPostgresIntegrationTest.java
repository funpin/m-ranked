package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.security.test.web.servlet.setup.SecurityMockMvcConfigurers.springSecurity;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import java.util.UUID;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.admin.application.*;
import org.mranked.admin.web.*;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.*;
import org.springframework.mock.web.MockServletContext;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.test.context.support.TestPropertySourceUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.context.support.AnnotationConfigWebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import tools.jackson.databind.json.JsonMapper;

/** Real MVC, authentication, CSRF, service and api_write_admin PostgreSQL transaction. */
@EnabledIfEnvironmentVariable(named="MRANKED_CATALOG_TEST_POSTGRES_URL",matches=".+")
class CatalogHttpPostgresIntegrationTest {
    private AnnotationConfigWebApplicationContext context;
    private MockMvc mvc;
    private final JsonMapper json=new JsonMapper();
    @BeforeEach void start() {
        context=new AnnotationConfigWebApplicationContext();context.setServletContext(new MockServletContext());
        for(int index=0;index<3;index++) {
            String role=java.util.List.of("viewer","editor","admin").get(index);
            TestPropertySourceUtils.addInlinedPropertiesToEnvironment(context,
                "mranked.admin.auth.users["+index+"].username="+role,
                "mranked.admin.auth.users["+index+"].password-hash={bcrypt}"+new BCryptPasswordEncoder(4).encode("test-password"),
                "mranked.admin.auth.users["+index+"].roles[0]="+role.toUpperCase(java.util.Locale.ROOT));
        }
        context.register(ConfigurationForTest.class);context.refresh();
        mvc=MockMvcBuilders.webAppContextSetup(context).apply(springSecurity()).build();
    }
    @AfterEach void close() { context.close(); }
    @Test void statelessBasicSessionReadPreservesCookieCsrfToken() throws Exception {
        var initial=session("editor");
        for(int attempt=0;attempt<3;attempt++) {
            var response=mvc.perform(get("/api/v1/admin/catalog/session")
                    .with(httpBasic("editor","test-password")).cookie(initial.cookie()))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"))
                .andReturn().getResponse();
            String token=json.readTree(response.getContentAsString()).path("token").asString();
            assertThat(token.equals(initial.token())).as("Basic reauthentication must not invalidate an open HTML form").isTrue();
            assertThat(response.getHeaders("Set-Cookie").stream().noneMatch(value->value.startsWith("XSRF-TOKEN=")&&value.contains("Max-Age=0")))
                .as("Stateless session preflight must not clear CSRF cookie").isTrue();
        }
    }
    @Test void completeCookieCsrfRbacAndCorrelatedAuditedWriteFlow() throws Exception {
        String base="/api/v1/admin/catalog";
        mvc.perform(get(base+"/institutions")).andExpect(status().isUnauthorized()).andExpect(header().string("Cache-Control","no-store"));
        var viewer=session("viewer");var editor=session("editor");var admin=session("admin");
        mvc.perform(get(base+"/institutions").with(httpBasic("viewer","test-password"))).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));
        UUID correlation=UUID.randomUUID();
        String body="{\"name\":\"HTTP verified institution\",\"shortName\":\"HTTP\"}";
        mvc.perform(post(base+"/institutions").with(httpBasic("viewer","test-password")).cookie(viewer.cookie()).header("X-XSRF-TOKEN",viewer.token())
            .header("X-Correlation-Id",correlation).contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post(base+"/institutions").with(httpBasic("editor","test-password")).header("X-Correlation-Id",correlation)
            .contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post(base+"/institutions").with(httpBasic("editor","test-password")).cookie(editor.cookie()).header("X-XSRF-TOKEN","wrong-token")
            .header("X-Correlation-Id",correlation).contentType("application/json").content(body)).andExpect(status().isForbidden());
        var request=post(base+"/institutions").with(httpBasic("editor","test-password")).cookie(editor.cookie()).header("X-XSRF-TOKEN",editor.token())
            .header("X-Correlation-Id",correlation).header("X-Actor","spoofed-admin").contentType("application/json").content(body);
        var result=mvc.perform(request).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andReturn();
        var created=json.readTree(result.getResponse().getContentAsString());
        mvc.perform(request).andExpect(status().isOk()).andExpect(content().json(result.getResponse().getContentAsString()));
        var owner=JdbcClient.create(new DriverManagerDataSource(System.getenv("MRANKED_CATALOG_TEST_POSTGRES_URL"),System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD")));
        assertThat(owner.sql("SELECT subject FROM ops_and_admin.audit_log WHERE correlation_id=:id").param("id",correlation).query(String.class).list()).containsExactly("editor");
        UUID remove=UUID.randomUUID();
        mvc.perform(delete(base+"/institutions/"+created.path("targetId").asString()).param("expectedRowVersion","0").with(httpBasic("editor","test-password"))
            .cookie(editor.cookie()).header("X-XSRF-TOKEN",editor.token()).header("X-Correlation-Id",remove)).andExpect(status().isForbidden());
        mvc.perform(post(base+"/legacy-command").with(httpBasic("editor","test-password")).cookie(editor.cookie()).header("X-XSRF-TOKEN",editor.token())
            .header("X-Correlation-Id",remove).contentType("application/json").content("{\"path\":\"/manage/channels/1/delete\",\"fields\":{}}"))
            .andExpect(status().isForbidden()).andExpect(header().string("Cache-Control","no-store"));
        mvc.perform(delete(base+"/institutions/"+created.path("targetId").asString()).param("expectedRowVersion","0").with(httpBasic("admin","test-password"))
            .cookie(admin.cookie()).header("X-XSRF-TOKEN",admin.token()).header("X-Correlation-Id",remove)).andExpect(status().isOk());
        assertThat(owner.sql("SELECT subject FROM ops_and_admin.audit_log WHERE correlation_id=:id").param("id",remove).query(String.class).list()).containsExactly("admin");
    }
    private Session session(String role) throws Exception {
        var response=mvc.perform(get("/api/v1/admin/catalog/session").with(httpBasic(role,"test-password"))).andExpect(status().isOk())
            .andExpect(jsonPath("$.canEdit").value(!role.equals("viewer"))).andExpect(jsonPath("$.canDelete").value(role.equals("admin")))
            .andExpect(header().string("Cache-Control","no-store")).andReturn().getResponse();
        var cookie=response.getCookie("XSRF-TOKEN");assertThat(cookie).isNotNull();
        return new Session(cookie,json.readTree(response.getContentAsString()).path("token").asString());
    }
    private record Session(jakarta.servlet.http.Cookie cookie,String token) { }
    @Configuration(proxyBeanMethods=false) @EnableWebMvc
    @Import({ApiSecurityConfiguration.class,ProblemSecurityHandler.class,CatalogController.class,AdminRfc9457ExceptionHandler.class,
        CatalogService.class,LegacyCatalogService.class,OfficialRatingService.class})
    static class ConfigurationForTest {
        @Bean DriverManagerDataSource adminSource() { return new DriverManagerDataSource(System.getenv("MRANKED_CATALOG_TEST_POSTGRES_URL"),"api_write_admin",System.getenv("MRANKED_ADMIN_TEST_PASSWORD")); }
        @Bean CatalogRepository catalogRepository(DriverManagerDataSource source) { return new JdbcCatalogRepository(JdbcClient.create(source),new TransactionTemplate(new DataSourceTransactionManager(source))); }
        @Bean OfficialRatingRepository ratingRepository(DriverManagerDataSource source) { return new JdbcOfficialRatingRepository(JdbcClient.create(source),new TransactionTemplate(new DataSourceTransactionManager(source))); }
        @Bean OfficialRatingSource officialSource() { return ()->{throw new IllegalStateException("Synthetic offline source");}; }
        @Bean CatalogStatusPort catalogStatus() { return ()->{throw new AdminDatabaseUnavailableException();}; }
        @Bean tools.jackson.databind.ObjectMapper objectMapper() { return new JsonMapper(); }
    }
}
