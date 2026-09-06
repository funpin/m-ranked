# Retained period history after disabling collection

The original generic-platform activity formulas continue to use retained
observations after a VK, MAX or Rutube account is disabled. V5 had applied the
polling `enabled` flag to both period dimensions and observation candidates,
which dropped that history from institution detail.

The representative frozen source exposed the difference for institution 207's
disabled Rutube account: the original 7-day window has 240 views and 48 reactions,
while the V26 period projection had no row and the institution API returned NULL.
The separate overview projection was already exact; the independent oracle was
not changed to ignore the inconsistent period projection.

Additive V27 changes exactly the two generic-platform eligibility predicates in
the period publisher. Telegram's enabled-channel policy, active platform coverage,
`visible_platform_account` and `visible_publication` filtering remain in place.
An existing published database receives a new configuration revision with the
same accepted source clock and a full coherent projection rebuild, so old ETags
cannot describe corrected results. V1–V26 files remain unchanged.

`DisabledPeriodPostgresIntegrationTest` installs a clean database and separately
upgrades a populated V26 database with real Flyway. Each case compares 288 cells
from original Python formulas with actual period rows, then 144 values returned
by the actual institution MVC endpoint using `api_read`. The fixture covers all
four windows and all three platforms, accounts that are disabled, mixed enabled
and disabled accounts, empty disabled accounts, exact zero and NULL. A populated
period-row deletion still fails the independent digest; Telegram and visibility
policies are asserted separately. No production database was used.
