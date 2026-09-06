# Disposable PostgreSQL recovery rehearsal

**Status:** pass. **Production acceptance:** false.

Source: `mranked-review-it-postgres-1 / visual_review_v2_it`. No source writes or stops.

| Measurement | Seconds |
|---|---:|
| baseBackupSeconds | 4.4835 |
| coldArchiveFallbackSeconds | 0.5008 |
| standbyControlledRpoSeconds | 0 |
| standbyPromotionRtoSeconds | 3.6015 |
| fullRestoreRtoSeconds | 9.7962 |
| pitrRestoreRtoSeconds | 9.7681 |
| pitrControlledRpoSeconds | 0.164436 |

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

Exact command descriptions, durations, canonical digests, WAL/basebackup checksums, Flyway manifest and controlled PITR boundary: [dr-c35dcdc2d398.json](dr-c35dcdc2d398.json).

RTO includes Docker start/restore and integrity/readiness checks. Standby RPO is zero only for the acknowledged catch-up marker. PITR RPO is the measured gap between included and intentionally excluded commits; this is a controlled failure drill, not observed production archive lag.

Remaining external acceptance gates:

- Separate physical DR host and encrypted channel
- Production-like capacity and concurrent workload
- pgBackRest encrypted multi-repository retention acceptance
- Provider immutable cold archive attestation
- Production RPO/RTO acceptance and named operator approval
