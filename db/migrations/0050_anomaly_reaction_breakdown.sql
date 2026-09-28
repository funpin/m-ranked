-- Read retained compact reaction components for conservative count bounds.
-- This grants read access only; no measurements or saved verdicts are rewritten.
GRANT SELECT ON TABLE ingest.reaction_breakdown TO analytics_worker;
