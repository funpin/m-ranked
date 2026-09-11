# Provider degradation semantics

Status: source/test analysis on 2026-09-08; no live-provider experiment was
performed. This is deliberately non-blocking for storage containment.

| Provider/capability | Canonical meaning | Deletion meaning |
|---|---|---|
| Telegram public preview views/reactions | rounded values; missing comments/shares remain `NULL`/`unknown` | only an exact point-lookup omission is `missing`; auth/transport is transient |
| Telegram synthetic publication baseline | explicit estimated zero at publication time only | never a deletion probe |
| VK metric below its stored high-water mark | value becomes `NULL` with `suspected_reset`; it is not persisted as zero | unrelated to deletion |
| VK exact post lookup returns no row | no metric snapshot for the missing object | authoritative `missing`, still requiring configured confirmation count |
| VK 401/403/429/transport | unknown current value; prior good data stays authoritative | transient/auth/rate result, never increments missing count |
| MAX views/reactions | provider values, including a real zero, are retained | exact lookup omission is `missing` |
| MAX comments/shares | unsupported capability remains `NULL` | unrelated to deletion |
| MAX auth/transport | unknown | transient, never deletion |
| RUTUBE views/likes | provider values; absent value remains `NULL`, real zero remains zero | HTTP 404 for exact video is `missing` |
| RUTUBE comments/shares and subscriber count when unavailable | unsupported/unknown remains `NULL` | unrelated to deletion |
| RUTUBE 401/403/429/transport | unknown | transient/auth/rate, never deletion |

The normalizer preserves the distinction in per-metric quality and evidence:
`unsupported_or_missing`, `suspected_reset`, `invalid`, and canonical `NULL`
are not interchangeable with zero. Semantic fingerprints include metric value,
quality, uncertainty and reaction state, so a change from exact zero to unknown
or suspected reset remains a meaningful historical transition.

Current unit tests cover VK suspected reset, MAX/RUTUBE unsupported `NULL`, and
Telegram/MAX/VK/RUTUBE point-lookup deletion contracts. Still required on a
production-like isolated account set: capture provider payload/status, compare
against previous high watermarks, confirm provider documentation/version, and
verify the public API renders unknown rather than zero. No live reset inference
or provider-capability assertion should be promoted to production evidence from
these source-level tests alone.
