package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Real repository SQL under api_read; never writes or creates database objects. */
@EnabledIfEnvironmentVariable(named="MRANKED_PLAN_TEST_URL",matches=".+")
class QueryPlanEvidenceTest {
    @Test void publicPlansUseOnlyBoundedProjectionsAndRawHistoryIsDenied() throws Exception {
        String url=System.getenv("MRANKED_PLAN_TEST_URL");
        assertThat(url).matches("jdbc:postgresql://(?:127\\.0\\.0\\.1|localhost):[0-9]+/[a-z0-9_]+_it");
        var source=new DriverManagerDataSource(url,"api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD"));
        var jdbc=new NamedParameterJdbcTemplate(source);
        Long revision=jdbc.queryForObject("SELECT max(id) FROM analytics.dataset_revision",Map.of(),Long.class);
        assertThat(revision).isPositive();
        Path output=Path.of(System.getenv("MRANKED_PLAN_OUTPUT"));
        Files.createDirectories(output);
        var plans=new LinkedHashMap<String,JsonNode>();
        var mapper=new JsonMapper();
        var cases=new LinkedHashMap<String,String>();
        cases.put("overview-50",JdbcProjectionQueryRepository.OVERVIEW_SQL);
        cases.put("overview-200",JdbcProjectionQueryRepository.OVERVIEW_SQL);
        cases.put("rating-telegram",ActivityRatingSql.entityPageSql(ActivityRatingSql.TELEGRAM_ENTITIES));
        cases.put("rating-vk",ActivityRatingSql.entityPageSql(ActivityRatingSql.PLATFORM_ENTITIES));
        cases.put("rating-rutube",ActivityRatingSql.entityPageSql(ActivityRatingSql.PLATFORM_ENTITIES));
        cases.put("comparison-vk",ComparisonSql.INSTITUTIONS);
        for(var item:cases.entrySet()) {
            String platform=item.getKey().endsWith("vk")?"vk":item.getKey().endsWith("rutube")?"rutube":"telegram";
            var parameters=new MapSqlParameterSource().addValue("revision",revision).addValue("period","1d")
                .addValue("platform",platform).addValue("sort","median_reactions").addValue("direction","desc")
                .addValue("search","").addValue("afterId",null,java.sql.Types.OTHER)
                .addValue("fetchLimit",item.getKey().equals("overview-50")?51:201)
                .addValue("afterEntityId",null,java.sql.Types.OTHER).addValue("entityFetchLimit",201)
                .addValue("channelSort","reactions").addValue("channelDirection","desc")
                .addValue("horizonSeconds",86400).addValue("includePartial",false)
                .addValue("metric","reactions").addValue("aggregation","median")
                .addValue("institutionLimit",50).addValue("selectionLegacyIdsJson","[]");
            String sql="EXPLAIN (ANALYZE,BUFFERS,VERBOSE,FORMAT JSON) "+item.getValue();
            String raw=jdbc.queryForObject(sql,parameters,String.class);
            JsonNode plan=mapper.readTree(raw);assertNoRawHistory(plan);
            plans.put(item.getKey(),plan);
            Files.writeString(output.resolve(item.getKey()+".sql"),item.getValue());
            Files.writeString(output.resolve(item.getKey()+".json"),mapper.writerWithDefaultPrettyPrinter().writeValueAsString(plan));
        }
        // ingest.reaction_breakdown is readable by api_read since c29a8ad (bounded source-read API);
        // the plan assertions above still prove the projection-backed public plans never touch it.
        for(String relation:Set.of("ingest.publication_metric_snapshot","ingest.account_metric_snapshot")) {
            Boolean allowed=jdbc.queryForObject("SELECT has_table_privilege(current_user,:relation,'SELECT')",Map.of("relation",relation),Boolean.class);
            assertThat(allowed).as("public role must not read %s",relation).isFalse();
        }
        Files.writeString(output.resolve("report.json"),mapper.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of(
            "gate","PASS","productionAcceptance",false,"datasetRevision",revision,"role","api_read",
            "rawHistoryDenied",true,"plans",plans)));
    }

    private static void assertNoRawHistory(JsonNode node) {
        if(node.isObject()) {
            if(node.has("Relation Name")) {
                String name=node.get("Relation Name").asText();
                assertThat(name).doesNotStartWith("publication_metric_snapshot")
                        .doesNotStartWith("account_metric_snapshot").doesNotStartWith("reaction_breakdown");
            }
            for(JsonNode child:node)assertNoRawHistory(child);
        } else if(node.isArray()) for(JsonNode child:node)assertNoRawHistory(child);
    }
}
