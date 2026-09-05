package org.mranked.query.web;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.ETagFactory;
import org.mranked.cache.application.PublicCacheRequest;
import org.mranked.cache.application.PublicDtoCache;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.application.PublicQueryService;
import org.mranked.query.domain.ActivityRatingQuery;
import org.mranked.query.domain.ComparisonSelection;
import org.mranked.query.domain.ComparisonSelectionType;
import org.mranked.query.domain.InvalidComparisonSelectionException;
import org.mranked.query.domain.OverviewQuery;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1")
public class PublicQueryController {
    private static final CacheControl PUBLIC_CACHE = CacheControl.maxAge(Duration.ofSeconds(30))
            .cachePublic().mustRevalidate();

    private final PublicQueryService queryService;
    private final PublicDtoCache responseCache;
    private final ETagFactory etagFactory;

    public PublicQueryController(
            PublicQueryService queryService,
            PublicDtoCache responseCache,
            ETagFactory etagFactory
    ) {
        this.queryService = queryService;
        this.responseCache = responseCache;
        this.etagFactory = etagFactory;
    }

    @GetMapping("/overview")
    public ResponseEntity<?> overview(
            @RequestParam(defaultValue = "all")
            @Pattern(regexp = "all|telegram|vk|max|rutube") String platform,
            @RequestParam(defaultValue = "1d")
            @Pattern(regexp = "3h|1d|7d|30d") String period,
            @RequestParam(defaultValue = "") @Size(max = 200) String q,
            @RequestParam(defaultValue = "median_reactions") @Size(max = 32) String sort,
            @RequestParam(required = false) @Size(max = 16) String direction,
            @RequestParam(defaultValue = "50") @Min(1) @Max(200) int limit,
            @RequestParam(required = false) @Size(max = 512) String cursor,
            @RequestHeader(value = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        validateOverviewParameters(q, limit, cursor);
        Platform parsedPlatform = Platform.fromApiValue(platform);
        PeriodKey parsedPeriod = PeriodKey.fromApiValue(period);
        OverviewQuery query = OverviewQuery.normalized(
                parsedPlatform, parsedPeriod, q, sort, direction
        );
        String normalizedCursor = queryService.normalizeCursor(cursor);
        PublicCacheRequest cacheRequest = responseCache.prepare("overview", Map.of(
                "platform", query.platform().databaseValue(),
                "period", query.period().databaseValue(),
                "q", query.search(),
                "sort", query.sort(),
                "direction", query.direction(),
                "limit", limit,
                "cursor", normalizedCursor == null ? "" : normalizedCursor
        ));
        return cached(cacheRequest, ifNoneMatch, PublicApiModels.OverviewPage.class, revision ->
                PublicApiModels.overview(queryService.overviewAtRevision(
                        query, limit, normalizedCursor, revision
                ))
        );
    }

    @GetMapping("/institutions/{legacyId}")
    public ResponseEntity<?> institution(
            @PathVariable @Positive long legacyId,
            @RequestParam(defaultValue = "all")
            @Pattern(regexp = "all|telegram|vk|max|rutube") String platform,
            @RequestParam(defaultValue = "1d")
            @Pattern(regexp = "3h|1d|7d|30d") String period,
            @RequestHeader(value = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        validateLegacyId(legacyId);
        Platform parsedPlatform = Platform.fromApiValue(platform);
        PeriodKey parsedPeriod = PeriodKey.fromApiValue(period);
        PublicCacheRequest cacheRequest = responseCache.prepare("institution", Map.of(
                "legacyId", legacyId,
                "platform", parsedPlatform.databaseValue(),
                "period", parsedPeriod.databaseValue()
        ));
        return cached(cacheRequest, ifNoneMatch, PublicApiModels.Institution.class, revision ->
                PublicApiModels.institution(queryService.institutionAtRevision(
                        legacyId, parsedPlatform, parsedPeriod, revision
                ))
        );
    }

    @GetMapping("/publications/{legacyId}")
    public ResponseEntity<?> publication(
            @PathVariable @Positive long legacyId,
            @RequestParam(defaultValue = "posts")
            @Pattern(regexp = "posts|platform_posts") String legacyType,
            @RequestHeader(value = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        validateLegacyId(legacyId);
        LegacyEntityType parsedLegacyType = LegacyEntityType.fromApiValue(legacyType);
        PublicCacheRequest cacheRequest = responseCache.prepare("publication", Map.of(
                "legacyId", legacyId,
                "legacyType", parsedLegacyType.databaseValue()
        ));
        return cached(cacheRequest, ifNoneMatch, PublicApiModels.Publication.class, revision ->
                PublicApiModels.publication(queryService.publicationAtRevision(
                        legacyId, parsedLegacyType, revision
                ))
        );
    }

    @GetMapping("/rating")
    public ResponseEntity<?> rating(
            @RequestParam(defaultValue = "telegram") @Size(max = 32) String platform,
            @RequestParam(defaultValue = "30d") @Size(max = 32) String period,
            @RequestParam(name = "channel_sort", defaultValue = "engagement")
            @Size(max = 32) String channelSort,
            @RequestParam(name = "channel_direction", defaultValue = "desc")
            @Size(max = 16) String channelDirection,
            @RequestParam(name = "post_sort", defaultValue = "view_share")
            @Size(max = 32) String postSort,
            @RequestParam(name = "post_direction", defaultValue = "desc")
            @Size(max = 16) String postDirection,
            @RequestParam(defaultValue = "200") @Min(1) @Max(200) int entityLimit,
            @RequestHeader(value = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        ActivityRatingQuery query = ActivityRatingQuery.normalized(
                ratingPlatform(platform), ratingPeriod(period),
                channelSort, channelDirection, postSort, postDirection
        );
        PublicCacheRequest cacheRequest = responseCache.prepare("rating", Map.of(
                "platform", query.platform().databaseValue(),
                "period", query.period().databaseValue(),
                "channelSort", query.channelSort(),
                "channelDirection", query.channelDirection(),
                "postSort", query.postSort(),
                "postDirection", query.postDirection(),
                "entityLimit", entityLimit
        ));
        return cached(cacheRequest, ifNoneMatch, PublicApiModels.Rating.class, revision ->
                PublicApiModels.rating(queryService.ratingAtRevision(
                        query, entityLimit, revision
                ))
        );
    }

    @GetMapping("/compare")
    public ResponseEntity<?> comparison(
            @RequestParam(defaultValue = "telegram")
            @Pattern(regexp = "telegram|vk|max|rutube") String platform,
            @RequestParam(defaultValue = "72")
            @Pattern(regexp = "24|48|72|168|336") String horizonHours,
            @RequestParam(defaultValue = "false") boolean includePartial,
            @RequestParam(defaultValue = "reactions")
            @Pattern(regexp = "views|reactions|comments|shares") String metric,
            @RequestParam(defaultValue = "median")
            @Pattern(regexp = "sum|median") String aggregation,
            @RequestParam(defaultValue = "25") @Min(1) @Max(50) int institutionLimit,
            @RequestParam(name = "institutions", required = false) List<String> institutions,
            @RequestParam(name = "channels", required = false) List<String> channels,
            @RequestHeader(value = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        int parsedHorizon = Integer.parseInt(horizonHours);
        Platform parsedPlatform = Platform.fromApiValue(platform);
        ComparisonSelection selection = comparisonSelection(
                parsedPlatform, channels, institutions
        );
        int effectiveInstitutionLimit = !selection.explicit()
                ? institutionLimit
                : selection.legacyIds().size();
        String entitySelection = !selection.explicit()
                ? "default"
                : selection.legacyIds().stream().map(String::valueOf)
                        .collect(java.util.stream.Collectors.joining(","));
        PublicCacheRequest cacheRequest = responseCache.prepare("comparison", Map.of(
                "platform", parsedPlatform.databaseValue(),
                "horizonHours", parsedHorizon,
                "includePartial", includePartial,
                "metric", metric,
                "aggregation", aggregation,
                "institutionLimit", effectiveInstitutionLimit,
                "selectionType", selection.type().apiValue(),
                "selection", entitySelection
        ));
        return cached(cacheRequest, ifNoneMatch, PublicApiModels.Comparison.class, revision ->
                PublicApiModels.comparison(queryService.comparisonAtRevision(
                        parsedPlatform, parsedHorizon, includePartial, metric,
                        aggregation, effectiveInstitutionLimit, selection, revision
                ))
        );
    }

    @GetMapping("/accounts/{legacyId}")
    public ResponseEntity<?> account(
            @PathVariable @Positive long legacyId,
            @RequestParam(defaultValue = "platform_accounts")
            @Pattern(regexp = "channels|platform_accounts") String legacyType,
            @RequestHeader(value = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        validateLegacyId(legacyId);
        LegacyEntityType parsedLegacyType = LegacyEntityType.accountFromApiValue(legacyType);
        PublicCacheRequest cacheRequest = responseCache.prepare("account", Map.of(
                "legacyId", legacyId,
                "legacyType", parsedLegacyType.databaseValue()
        ));
        return cached(cacheRequest, ifNoneMatch, PublicApiModels.Account.class, revision ->
                PublicApiModels.account(queryService.accountAtRevision(
                        legacyId, parsedLegacyType, revision
                ))
        );
    }

    private <T> ResponseEntity<?> cached(
            PublicCacheRequest cacheRequest,
            String ifNoneMatch,
            Class<T> dtoType,
            Function<DatasetRevision, T> loader
    ) {
        String etag = etagFactory.create(cacheRequest.key());
        if (etagFactory.matches(ifNoneMatch, etag)) {
            return notModified(etag);
        }
        T body = responseCache.getOrLoad(cacheRequest, dtoType, loader);
        return ResponseEntity.ok().cacheControl(PUBLIC_CACHE).eTag(etag).body(body);
    }

    private static ResponseEntity<Void> notModified(String etag) {
        return ResponseEntity.status(304).cacheControl(PUBLIC_CACHE).eTag(etag).build();
    }

    private static void validateOverviewParameters(String search, int limit, String cursor) {
        if (search.length() > 200 || limit < 1 || limit > 200
                || (cursor != null && cursor.length() > 512)) {
            throw new IllegalArgumentException("invalid overview parameters");
        }
    }

    private static void validateLegacyId(long legacyId) {
        if (legacyId <= 0) {
            throw new IllegalArgumentException("legacy id must be positive");
        }
    }

    private static Platform ratingPlatform(String value) {
        String normalized = value == null ? "telegram"
                : value.strip().toLowerCase(java.util.Locale.ROOT);
        if ("tg".equals(normalized)) {
            normalized = "telegram";
        }
        if ("all".equals(normalized) || "max".equals(normalized)) {
            throw new IllegalArgumentException("activity rating is pending for this platform");
        }
        return switch (normalized) {
            case "vk" -> Platform.VK;
            case "rutube" -> Platform.RUTUBE;
            default -> Platform.TELEGRAM;
        };
    }

    private static PeriodKey ratingPeriod(String value) {
        String normalized = value == null ? "30d"
                : value.strip().toLowerCase(java.util.Locale.ROOT);
        try {
            return PeriodKey.fromApiValue(normalized);
        } catch (IllegalArgumentException ignored) {
            return PeriodKey.ONE_DAY;
        }
    }

    private static ComparisonSelection comparisonSelection(
            Platform platform,
            List<String> channels,
            List<String> institutions
    ) {
        ComparisonSelectionType expected = ComparisonSelectionType.forPlatform(platform);
        List<String> supplied = expected == ComparisonSelectionType.CHANNELS
                ? channels : institutions;
        if (supplied == null) {
            return ComparisonSelection.defaults(expected);
        }
        return new ComparisonSelection(expected, parseLegacyIds(supplied, expected));
    }

    private static List<Long> parseLegacyIds(
            List<String> values,
            ComparisonSelectionType selectionType
    ) {
        String parameterName = selectionType.apiValue();
        String entityName = selectionType.entityValue();
        if (values.isEmpty()) {
            throw new InvalidComparisonSelectionException(
                    "At least one ID is required when " + parameterName + " is supplied"
            );
        }
        if (values.size() > ComparisonSelection.MAX_INSTITUTIONS) {
            throw new InvalidComparisonSelectionException(
                    "At most " + ComparisonSelection.MAX_INSTITUTIONS
                            + " " + entityName + " IDs may be selected"
            );
        }
        List<Long> parsed = new ArrayList<>(values.size());
        for (String value : values) {
            if (value == null || !value.matches("[0-9]+")) {
                throw new InvalidComparisonSelectionException(
                        capitalize(entityName) + " IDs must be positive integers"
                );
            }
            try {
                parsed.add(Long.parseLong(value));
            } catch (NumberFormatException exception) {
                throw new InvalidComparisonSelectionException(
                        capitalize(entityName) + " IDs must be positive integers"
                );
            }
        }
        return parsed;
    }

    private static String capitalize(String value) {
        return Character.toUpperCase(value.charAt(0)) + value.substring(1);
    }
}
