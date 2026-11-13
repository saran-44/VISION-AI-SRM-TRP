-- Incremental hardening schema migration for existing deployments on schema v1.
-- Safe to run once as the database administrator after 001_initial.sql.
-- Does not drop data or overwrite existing rows.
BEGIN;

CREATE INDEX IF NOT EXISTS users_firebase_uid
    ON transport_portal.users (firebase_uid)
    WHERE firebase_uid IS NOT NULL;

CREATE INDEX IF NOT EXISTS audit_collection_action_timestamp
    ON transport_portal.audit_logs (collection, action, timestamp DESC);

COMMIT;
