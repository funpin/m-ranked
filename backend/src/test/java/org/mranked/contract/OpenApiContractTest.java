package org.mranked.contract;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.yaml.snakeyaml.LoaderOptions;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.SafeConstructor;

class OpenApiContractTest {
    @Test
    void checkedInContractIsValidYamlAndListsOnlyImplementedRoutes() throws IOException {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        Path contract = backend.resolve("../contracts/openapi/m-ranked-v1.yaml").normalize();
        Map<String, Object> document;
        try (Reader reader = Files.newBufferedReader(contract)) {
            document = new Yaml(new SafeConstructor(new LoaderOptions())).load(reader);
        }

        assertThat(document.get("openapi")).isEqualTo("3.1.0");
        @SuppressWarnings("unchecked")
        Map<String, Object> paths = (Map<String, Object>) document.get("paths");
        assertThat(paths.keySet()).containsExactlyInAnyOrder(
                "/api/v1/health/live",
                "/api/v1/health/ready",
                "/api/v1/emoji/{emojiId}",
                "/api/v1/overview",
                "/api/v1/institutions/{legacyId}",
                "/api/v1/publications/{legacyId}",
                "/api/v1/rating",
                "/api/v1/compare",
                "/api/v1/accounts/{legacyId}",
                "/api/v1/exports/publications.csv",
                "/api/v1/admin/csrf",
                "/api/v1/admin/jobs",
                "/api/v1/admin/jobs/{jobId}",
                "/api/v1/admin/platform-accounts/{accountId}",
                "/api/v1/admin/platform-accounts/{accountId}/enabled"
        );

        @SuppressWarnings("unchecked")
        Map<String, Object> adminJobs = (Map<String, Object>) paths.get("/api/v1/admin/jobs");
        @SuppressWarnings("unchecked")
        Map<String, Object> getAdminJobs = (Map<String, Object>) adminJobs.get("get");
        assertThat(getAdminJobs.get("security").toString()).contains("basicAuth");
        @SuppressWarnings("unchecked")
        Map<String, Object> adminEnable = (Map<String, Object>) paths.get(
                "/api/v1/admin/platform-accounts/{accountId}/enabled"
        );
        assertThat(adminEnable.keySet()).containsExactly("put");
        assertThat(adminEnable.toString())
                .contains("X-XSRF-TOKEN")
                .contains("OptimisticLockConflict");
        @SuppressWarnings("unchecked")
        Map<String, Object> adminAccount = (Map<String, Object>) paths.get(
                "/api/v1/admin/platform-accounts/{accountId}"
        );
        assertThat(adminAccount.keySet()).containsExactly("get");
        assertThat(adminAccount.toString())
                .contains("AdminPlatformAccountState")
                .contains("AdminUnavailable")
                .doesNotContain("canonicalExternalId")
                .doesNotContain("currentUrl");

        @SuppressWarnings("unchecked")
        Map<String, Object> emojiPath = (Map<String, Object>) paths.get("/api/v1/emoji/{emojiId}");
        assertThat(emojiPath.toString())
                .contains("operationId=getCustomEmoji")
                .contains("pattern=^[0-9]{1,32}$")
                .contains("const=public, max-age=21600")
                .contains("image/webp")
                .contains("image/png")
                .contains("image/gif")
                .contains("image/jpeg")
                .contains("2,000,000 bytes");

        @SuppressWarnings("unchecked")
        Map<String, Object> components = (Map<String, Object>) document.get("components");
        @SuppressWarnings("unchecked")
        Map<String, Object> schemas = (Map<String, Object>) components.get("schemas");
        assertThat(schemas.get("AdminSetEnabledRequest").toString())
                .contains("expectedRowVersion")
                .contains("additionalProperties=false");
        @SuppressWarnings("unchecked")
        Map<String, Object> account = (Map<String, Object>) schemas.get("Account");
        @SuppressWarnings("unchecked")
        List<String> accountRequired = (List<String>) account.get("required");
        assertThat(accountRequired).contains("channelLegacyId", "platformAccountLegacyId");

        @SuppressWarnings("unchecked")
        Map<String, Object> publication = (Map<String, Object>) schemas.get("Publication");
        @SuppressWarnings("unchecked")
        List<String> publicationRequired = (List<String>) publication.get("required");
        assertThat(publicationRequired)
                .doesNotContain("channelLegacyId", "platformAccountLegacyId");

        @SuppressWarnings("unchecked")
        Map<String, Object> overviewPath = (Map<String, Object>) paths.get("/api/v1/overview");
        @SuppressWarnings("unchecked")
        Map<String, Object> overviewGet = (Map<String, Object>) overviewPath.get("get");
        assertThat(overviewGet.toString())
                .contains("name=sort")
                .contains("name=direction")
                .contains("globally sorted")
                .contains("Missing sort values stay last");
        @SuppressWarnings("unchecked")
        Map<String, Object> overview = (Map<String, Object>) schemas.get("OverviewRow");
        @SuppressWarnings("unchecked")
        List<String> overviewRequired = (List<String>) overview.get("required");
        assertThat(overviewRequired).contains(
                "entityId", "entityType", "institutionLegacyId", "accounts",
                "connectedPlatformCount", "ratingRank", "totalPublicationCount",
                "views", "reactions", "statusCode"
        );

        @SuppressWarnings("unchecked")
        Map<String, Object> ratingPath = (Map<String, Object>) paths.get("/api/v1/rating");
        @SuppressWarnings("unchecked")
        Map<String, Object> ratingGet = (Map<String, Object>) ratingPath.get("get");
        assertThat(ratingGet.toString())
                .contains("name=channel_sort")
                .contains("name=post_sort")
                .contains("name=entityLimit")
                .contains("top 50 publications")
                .doesNotContain("formulaKey");
        @SuppressWarnings("unchecked")
        Map<String, Object> rating = (Map<String, Object>) schemas.get("Rating");
        @SuppressWarnings("unchecked")
        List<String> ratingRequired = (List<String>) rating.get("required");
        assertThat(ratingRequired).contains(
                "platform", "period", "entityType", "entities", "publications",
                "entitiesTruncated", "datasetRevision"
        );

        @SuppressWarnings("unchecked")
        Map<String, Object> comparePath = (Map<String, Object>) paths.get("/api/v1/compare");
        @SuppressWarnings("unchecked")
        Map<String, Object> compareGet = (Map<String, Object>) comparePath.get("get");
        assertThat(compareGet.toString())
                .contains("name=channels")
                .contains("name=institutions")
                .contains("maxItems=50")
                .contains("de-duplicated")
                .contains("ignored")
                .contains("explode=true");
        @SuppressWarnings("unchecked")
        Map<String, Object> comparison = (Map<String, Object>) schemas.get("Comparison");
        @SuppressWarnings("unchecked")
        List<String> comparisonRequired = (List<String>) comparison.get("required");
        assertThat(comparisonRequired).contains("selectionType");
        @SuppressWarnings("unchecked")
        Map<String, Object> comparisonSeries = (Map<String, Object>) schemas.get(
                "ComparisonSeries"
        );
        @SuppressWarnings("unchecked")
        List<String> seriesRequired = (List<String>) comparisonSeries.get("required");
        assertThat(seriesRequired).contains(
                "selectionId", "selectionType", "selectionLegacyId", "selectionLabel",
                "primaryCohortSize", "engagementCohortSize", "engagementPoints"
        );
        assertThat(comparisonSeries.toString())
                .contains("per-publication percentages")
                .contains("does not interpolate")
                .contains("future values backward");
    }

    @Test
    void checkedInTypescriptClientIsLockedToTheContractAndEveryOperation() throws Exception {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        Path contract = backend.resolve("../contracts/openapi/m-ranked-v1.yaml").normalize();
        Path client = backend.resolve("../contracts/openapi/m-ranked-v1-client.ts").normalize();

        byte[] contractBytes = Files.readAllBytes(contract);
        String sourceHash = HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256").digest(contractBytes)
        );
        String generatedClient = Files.readString(client);
        assertThat(generatedClient).contains("Source-SHA256: " + sourceHash);
        assertThat(generatedClient)
                .contains("getAdminJobs(")
                .contains("getAdminPlatformAccount(")
                .contains("setAdminPlatformAccountEnabled(")
                .contains("getCustomEmoji(")
                .contains("channels?: readonly number[];")
                .contains("institutions?: readonly number[];")
                .contains("parameters.append(key, String(entry))")
                .contains("cache: \"no-store\"")
                .contains("credentials: \"include\"")
                .doesNotContain("password:");

        Map<String, Object> document;
        try (Reader reader = Files.newBufferedReader(contract)) {
            document = new Yaml(new SafeConstructor(new LoaderOptions())).load(reader);
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> paths = (Map<String, Object>) document.get("paths");
        for (Object pathItemValue : paths.values()) {
            @SuppressWarnings("unchecked")
            Map<String, Object> pathItem = (Map<String, Object>) pathItemValue;
            for (Object operationValue : pathItem.values()) {
                @SuppressWarnings("unchecked")
                Map<String, Object> operation = (Map<String, Object>) operationValue;
                Object operationId = operation.get("operationId");
                if (operationId != null) {
                    assertThat(generatedClient).contains(operationId + "(");
                }
            }
        }
    }
}
