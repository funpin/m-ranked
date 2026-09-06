# Disposable PostgreSQL recovery rehearsal

**Status:** pass. **Production acceptance:** false.

Source: `mranked-review-it-postgres-1 / admin_review_visual_v7_it`. No source writes or stops.

| Measurement | Seconds |
|---|---:|
| baseBackupSeconds | 26.3696 |
| coldArchiveFallbackSeconds | 0.945 |
| standbyControlledRpoSeconds | 0 |
| standbyPromotionRtoSeconds | 7.8962 |
| fullRestoreRtoSeconds | 28.4913 |
| pitrRestoreRtoSeconds | 28.0681 |
| pitrControlledRpoSeconds | 0.7227 |

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

Exact command descriptions, durations, canonical digests, WAL/basebackup checksums, Flyway manifest and controlled PITR boundary: [dr-5e9a768fc9fe.json](dr-5e9a768fc9fe.json).

RTO includes Docker start/restore and integrity/readiness checks. Standby RPO is zero only for the acknowledged catch-up marker. PITR RPO is the measured gap between included and intentionally excluded commits; this is a controlled failure drill, not observed production archive lag.

Remaining external acceptance gates:

- Separate physical DR host and encrypted channel
- Production-like capacity and concurrent workload
- pgBackRest encrypted multi-repository retention acceptance
- Provider immutable cold archive attestation
- Production RPO/RTO acceptance and named operator approval
