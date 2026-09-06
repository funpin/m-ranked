# Disposable PostgreSQL recovery rehearsal

**Status:** pass. **Production acceptance:** false.

Source: `mranked-review-it-postgres-1 / admin_review_visual_v7_it`. No source writes or stops.

| Measurement | Seconds |
|---|---:|
| baseBackupSeconds | 8.5242 |
| coldArchiveFallbackSeconds | 0.6203 |
| standbyControlledRpoSeconds | 0 |
| standbyPromotionRtoSeconds | 5.5501 |
| fullRestoreRtoSeconds | 16.4231 |
| pitrRestoreRtoSeconds | 16.5255 |
| pitrControlledRpoSeconds | 0.314674 |

| Check | Result |
|---|---|
| independentSourceClone | True |
| physicalBackupVerified | True |
| streamingStandbyCaughtUp | True |
| coldArchiveFallbackWithPrimaryStopped | True |
| standbyPromotion | True |
| fullRestorePageChecksumsAndAmcheck | True |
| pitrBoundaryPageChecksumsAndAmcheck | True |
| promotedStandbyPageChecksums | True |
| sameExactFlywayManifest | True |
| localRpoBudget | True |
| localRtoBudget | True |
| ownedResourcesCleaned | True |

Exact command descriptions, durations, canonical digests, WAL/basebackup checksums, Flyway manifest and controlled PITR boundary: [dr-fc5064bf7d2c.json](dr-fc5064bf7d2c.json).

RTO includes Docker start/restore and integrity/readiness checks. Standby RPO is zero only for the acknowledged catch-up marker. PITR RPO is the measured gap between included and intentionally excluded commits; this is a controlled failure drill, not observed production archive lag.

Remaining external acceptance gates:

- Separate physical DR host and encrypted channel
- Production-like capacity and concurrent workload
- pgBackRest encrypted multi-repository retention acceptance
- Provider immutable cold archive attestation
- Production RPO/RTO acceptance and named operator approval
