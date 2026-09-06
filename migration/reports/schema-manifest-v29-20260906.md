# Flyway V1–V29

V — последовательный номер изменения схемы/SQL-функций/grants. Это не версия приложения.

V1–V8 побайтово совпали с HEAD `a7a2f09ff156eb72445f04f40dbe0e93d3378911`. Полный JSON: [schema-manifest](schema-manifest-v29-20260906.json).

| Version / migration | Flyway CRC32 | SHA-256 |
|---|---:|---|
| [V1__target_baseline.sql](../../backend/src/main/resources/db/migration/V1__target_baseline.sql) | -1636077697 | `dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1` |
| [V2__rebuild_core_projections.sql](../../backend/src/main/resources/db/migration/V2__rebuild_core_projections.sql) | 839607018 | `113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd` |
| [V3__collector_observation_times_and_identity_grants.sql](../../backend/src/main/resources/db/migration/V3__collector_observation_times_and_identity_grants.sql) | -1456658399 | `5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1` |
| [V4__admin_collection_run_status_grants.sql](../../backend/src/main/resources/db/migration/V4__admin_collection_run_status_grants.sql) | 1318350062 | `d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82` |
| [V5__legacy_activity_period_projection.sql](../../backend/src/main/resources/db/migration/V5__legacy_activity_period_projection.sql) | -1313754193 | `d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41` |
| [V6__comparison_valid_observation_hourly_projection.sql](../../backend/src/main/resources/db/migration/V6__comparison_valid_observation_hourly_projection.sql) | -290358219 | `4ac99091046d40345c7024d3fab96ceb779fafb836c18c6a750f748f7bd29c64` |
| [V7__activity_rating_read_grants.sql](../../backend/src/main/resources/db/migration/V7__activity_rating_read_grants.sql) | -1228913579 | `95244a71a992fb8d9de387622224ddb52365120ac47c4d0cf4cbb20f4e36f0eb` |
| [V8__legacy_overview_projection.sql](../../backend/src/main/resources/db/migration/V8__legacy_overview_projection.sql) | -574188650 | `dc855dde66a705808e1565e3f56c4555995d370805cee68ee9293ae7fa0aec9c` |
| [V9__immutable_observations_quality_archive_fence.sql](../../backend/src/main/resources/db/migration/V9__immutable_observations_quality_archive_fence.sql) | 1058556652 | `2e165a561c9f839ec36af5bcc4c88b967778a9f11fb69e28dc71bbe5e053db50` |
| [V10__consistent_public_queries_and_formula_guards.sql](../../backend/src/main/resources/db/migration/V10__consistent_public_queries_and_formula_guards.sql) | -1148603410 | `126bc5263ecc56eb6a09342bc92f62bf74ef32d1bf1ca285e54454d7e9cf3b0b` |
| [V11__bridge_identity_lineage_and_reconciliation.sql](../../backend/src/main/resources/db/migration/V11__bridge_identity_lineage_and_reconciliation.sql) | 1679789143 | `1e804126491b16f77be5af6db60ac45947d7ba782f5829de39f42d62f5240cff` |
| [V12__detail_history_projection.sql](../../backend/src/main/resources/db/migration/V12__detail_history_projection.sql) | 1453326243 | `60dc3c9fd9d4997959f5b168e12f63a9553b93146023e826a0b57b607a43b100` |
| [V13__immutable_account_identity_history.sql](../../backend/src/main/resources/db/migration/V13__immutable_account_identity_history.sql) | -185639607 | `ab306bda84d76d4239e67d33232247c1d318d306ebd183962eda5d2b2a4b2cd0` |
| [V14__public_archived_publication_text.sql](../../backend/src/main/resources/db/migration/V14__public_archived_publication_text.sql) | -956321170 | `261c257e7816c93ea84cb7d1318b711cbb0e6c518b30df57877cef92afb5f9e6` |
| [V15__verified_source_preservation.sql](../../backend/src/main/resources/db/migration/V15__verified_source_preservation.sql) | -1953543117 | `07891ccbeb0cfcf881b090f91c6efd2da5c0fc9fd45b49e4dc1bd9a90e15d941` |
| [V16__audited_catalog_commands.sql](../../backend/src/main/resources/db/migration/V16__audited_catalog_commands.sql) | -888916335 | `a350e3564567c4fd9e99ff69f0b541cc5de2d8c661dbb505c9efe4abfc2b35ad` |
| [V17__legacy_csv_compatibility_projection.sql](../../backend/src/main/resources/db/migration/V17__legacy_csv_compatibility_projection.sql) | 2060863494 | `44696090aabda6ba3c971aa27b933b7f31a4d9392d2266d8294e158015a52b83` |
| [V18__official_rating_commands.sql](../../backend/src/main/resources/db/migration/V18__official_rating_commands.sql) | 875583974 | `481fde448839a5a164cf7aea16d9c109126f0005fb227d97ab8e2b521b4e60c9` |
| [V19__safe_health_operational_snapshot.sql](../../backend/src/main/resources/db/migration/V19__safe_health_operational_snapshot.sql) | -1653532549 | `85cb7579c6c1c91f47a250014f4d522a4a2e9a3d785afbe490516d5b5f86a503` |
| [V20__catalog_url_and_version_compatibility.sql](../../backend/src/main/resources/db/migration/V20__catalog_url_and_version_compatibility.sql) | 925593865 | `e8e96cf550e31311a0d0b96a915c09bf4f93cec69ff3cce84b932dbd29cb4aa2` |
| [V21__legacy_period_first_observation_policy.sql](../../backend/src/main/resources/db/migration/V21__legacy_period_first_observation_policy.sql) | -900669350 | `6270ec9827ec901728b309eb537f06ab4f2487d541bd4b8e32f92c26cc840ba8` |
| [V22__durable_legacy_csv_archive_facts.sql](../../backend/src/main/resources/db/migration/V22__durable_legacy_csv_archive_facts.sql) | 2064364640 | `a645b247e1fd6055e17e05636f7f0ec05ed240ac95106178fc7fdfe9d5c0921f` |
| [V23__official_rating_entity_context.sql](../../backend/src/main/resources/db/migration/V23__official_rating_entity_context.sql) | 890722389 | `dcea6278b2c218803984d27e4828fcb8f7d42af34cf357e619b7ae93768b652c` |
| [V24__ordered_history_reaction_details.sql](../../backend/src/main/resources/db/migration/V24__ordered_history_reaction_details.sql) | 1889276383 | `0f0886c8804b7bc4329c7f7461322ad9eb62924412cac02b24caca06942863db` |
| [V25__safe_legacy_account_presentation.sql](../../backend/src/main/resources/db/migration/V25__safe_legacy_account_presentation.sql) | 381330844 | `c6497ad2f0bd4ceeb39efff48ad62cbbf625d64969cd68b15dd36e30031d7fa1` |
| [V26__independent_projection_verifier_reads.sql](../../backend/src/main/resources/db/migration/V26__independent_projection_verifier_reads.sql) | -1482835665 | `1ff9ed8a785641972a290b7f9fcc48dff6e1130fdf7e83d0adf9e572b9b96ea8` |
| [V27__retained_disabled_platform_period_metrics.sql](../../backend/src/main/resources/db/migration/V27__retained_disabled_platform_period_metrics.sql) | -1466195806 | `95736d8f4d4f7be9c5904f7118b85532e508f93b6fc94130e5395fb31e92ed97` |
| [V28__identity_command_receipt_verifier_acl.sql](../../backend/src/main/resources/db/migration/V28__identity_command_receipt_verifier_acl.sql) | 1374125493 | `215a382daced28ca93dd6580f68c768ee050964fc57ab9591d76b63da5c83020` |
| [V29__monotonic_native_identity_transitions.sql](../../backend/src/main/resources/db/migration/V29__monotonic_native_identity_transitions.sql) | -1547328464 | `b608a4ccfa204348033203bdd9b6dd3eea2b0d79ff72f2af8fbb776687b095de` |
