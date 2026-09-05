package org.mranked.admin.infrastructure;

import jakarta.servlet.DispatcherType;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.security.test.web.servlet.setup.SecurityMockMvcConfigurers.springSecurity;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockServletContext;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.test.context.support.TestPropertySourceUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.support.AnnotationConfigWebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import tools.jackson.databind.ObjectMapper;

import java.util.concurrent.Callable;

class ApiSecurityConfigurationTest {
    private AnnotationConfigWebApplicationContext context;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        context = new AnnotationConfigWebApplicationContext();
        context.setServletContext(new MockServletContext());
        BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
        TestPropertySourceUtils.addInlinedPropertiesToEnvironment(
                context,
                "mranked.admin.auth.users[0].username=viewer",
                "mranked.admin.auth.users[0].password-hash={bcrypt}" + encoder.encode("viewer-pass"),
                "mranked.admin.auth.users[0].roles[0]=VIEWER",
                "mranked.admin.auth.users[1].username=editor",
                "mranked.admin.auth.users[1].password-hash={bcrypt}" + encoder.encode("editor-pass"),
                "mranked.admin.auth.users[1].roles[0]=EDITOR",
                "mranked.admin.auth.users[2].username=admin",
                "mranked.admin.auth.users[2].password-hash={bcrypt}" + encoder.encode("admin-pass"),
                "mranked.admin.auth.users[2].roles[0]=ADMIN"
        );
        context.register(TestConfiguration.class);
        context.refresh();
        mvc = MockMvcBuilders.webAppContextSetup(context)
                .apply(springSecurity())
                .build();
    }

    @AfterEach
    void closeContext() {
        context.close();
    }

    @Test
    void permitsImplementedPublicGetEndpoints() throws Exception {
        mvc.perform(get("/api/v1/public-test"))
                .andExpect(status().isOk())
                .andExpect(content().string("public"));
        mvc.perform(get("/api/v1/emoji/42"))
                .andExpect(status().isOk())
                .andExpect(content().string("emoji"));
    }

    @Test
    void challengesAnonymousAdminWithRfc9457MediaType() throws Exception {
        mvc.perform(get("/api/v1/admin/jobs"))
                .andExpect(status().isUnauthorized())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(header().string("WWW-Authenticate", "Basic realm=\"m-ranked-admin\""))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:unauthorized"))
                .andExpect(jsonPath("$.status").value(401))
                .andExpect(jsonPath("$.instance").value("/api/v1/admin/jobs"));
    }

    @Test
    void appliesViewerEditorAndAdminRbacWithCsrfForWrites() throws Exception {
        mvc.perform(get("/api/v1/admin/jobs").with(httpBasic("viewer", "viewer-pass")))
                .andExpect(status().isOk())
                .andExpect(content().string("admin"));

        mvc.perform(get("/api/v1/admin/platform-accounts/123")
                        .with(httpBasic("viewer", "viewer-pass")))
                .andExpect(status().isOk())
                .andExpect(content().string("account"));

        mvc.perform(get("/api/v1/admin/platform-accounts/123")
                        .with(httpBasic("editor", "editor-pass")))
                .andExpect(status().isOk());

        mvc.perform(get("/api/v1/admin/platform-accounts/123")
                        .with(httpBasic("admin", "admin-pass")))
                .andExpect(status().isOk());

        mvc.perform(put("/api/v1/admin/platform-accounts/123/enabled")
                        .with(httpBasic("viewer", "viewer-pass"))
                        .with(csrf()))
                .andExpect(status().isForbidden())
                .andExpect(header().string("Cache-Control", "no-store"));

        mvc.perform(put("/api/v1/admin/platform-accounts/123/enabled")
                        .with(httpBasic("editor", "editor-pass")))
                .andExpect(status().isForbidden())
                .andExpect(header().string("Cache-Control", "no-store"));

        mvc.perform(put("/api/v1/admin/platform-accounts/123/enabled")
                        .with(httpBasic("editor", "editor-pass"))
                        .with(csrf()))
                .andExpect(status().isOk())
                .andExpect(content().string("changed"));

        mvc.perform(put("/api/v1/admin/platform-accounts/123/enabled")
                        .with(httpBasic("admin", "admin-pass"))
                        .with(csrf()))
                .andExpect(status().isOk());
    }

    @Test
    void deniesUnimplementedMutationsAndNonApiRoutes() throws Exception {
        mvc.perform(post("/api/v1/public-test").with(csrf()))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/not-an-api"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void permitsAsyncDispatchForPublicStreamingEndpoints() throws Exception {
        MvcResult result = mvc.perform(get("/api/v1/async-test"))
                .andExpect(status().isOk())
                .andReturn();

        mvc.perform(asyncDispatch(result))
                .andExpect(status().isOk())
                .andExpect(content().string("async"));
    }

    @Test
    void permitsOnlyInternalErrorDispatchToTheErrorRenderer() throws Exception {
        mvc.perform(get("/error"))
                .andExpect(status().isUnauthorized());

        mvc.perform(get("/error").with(request -> {
                    request.setDispatcherType(DispatcherType.ERROR);
                    return request;
                }))
                .andExpect(status().isOk())
                .andExpect(content().string("error"));
    }

    @Configuration(proxyBeanMethods = false)
    @EnableWebMvc
    @Import({ApiSecurityConfiguration.class, ProblemSecurityHandler.class, TestRoutes.class})
    static class TestConfiguration {
        @Bean
        ObjectMapper objectMapper() {
            return new ObjectMapper();
        }

    }

    @RestController
    static class TestRoutes {
        @GetMapping("/api/v1/public-test")
        String publicGet() {
            return "public";
        }

        @GetMapping("/api/v1/emoji/{id}")
        String publicEmojiGet() {
            return "emoji";
        }

        @PostMapping("/api/v1/public-test")
        String publicPost() {
            return "mutation";
        }

        @GetMapping("/api/v1/admin/jobs")
        String adminGet() {
            return "admin";
        }

        @GetMapping("/api/v1/admin/platform-accounts/{id}")
        String adminAccountGet() {
            return "account";
        }

        @PutMapping("/api/v1/admin/platform-accounts/{id}/enabled")
        String adminPut() {
            return "changed";
        }

        @GetMapping("/api/v1/async-test")
        Callable<String> asyncGet() {
            return () -> "async";
        }

        @GetMapping("/error")
        String error() {
            return "error";
        }
    }
}
