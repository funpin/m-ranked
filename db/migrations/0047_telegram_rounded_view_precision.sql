-- Preserve the display unit of rounded Telegram views on bounded poll receipts.
-- Existing receipts lack this information and remain unknown (NULL).
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE ingest.publication_poll_receipt
    ADD COLUMN views_display_unit integer;

ALTER TABLE ingest.publication_poll_receipt
    ADD CONSTRAINT publication_poll_receipt_views_display_unit_ck
    CHECK (views_display_unit IS NULL OR (
        views_quality = 'rounded'::ingest.observation_quality
        AND views_count IS NOT NULL
        AND views_display_unit IN (
            1, 10, 100, 1000, 10000, 100000, 1000000,
            10000000, 100000000, 1000000000
        )
    )) NOT VALID;

COMMENT ON COLUMN ingest.publication_poll_receipt.views_display_unit IS
    'Unit of the last visible digit; NULL when the rounded display precision was not retained';

COMMIT;
