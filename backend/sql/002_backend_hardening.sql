-- Incremental hardening schema migration for existing deployments on schema v1.
-- Safe to run once as the database administrator after 001_initial.sql.
-- Does not drop data or overwrite existing rows.
BEGIN;

CREATE INDEX IF NOT EXISTS users_firebase_uid
    ON transport_portal.users (firebase_uid)
    WHERE firebase_uid IS NOT NULL;

CREATE INDEX IF NOT EXISTS audit_collection_action_timestamp
    ON transport_portal.audit_logs (collection, action, timestamp DESC);

CREATE TABLE IF NOT EXISTS transport_portal.bus_states (
    _id varchar(24) PRIMARY KEY,
    bus_number varchar(20) NOT NULL UNIQUE,
    direction varchar(3) NOT NULL,
    last_timestamp timestamp NOT NULL,
    last_event_id varchar(24) NOT NULL,
    gate text,
    camera_id text,
    demo boolean NOT NULL DEFAULT false,
    updated_at timestamp NOT NULL
);

CREATE INDEX IF NOT EXISTS bus_states_direction
    ON transport_portal.bus_states (direction);

CREATE INDEX IF NOT EXISTS bus_states_updated_at
    ON transport_portal.bus_states (updated_at);

ALTER TABLE transport_portal.buses
    ADD COLUMN IF NOT EXISTS plate_key varchar(20);

UPDATE transport_portal.buses
SET plate_key = regexp_replace(upper(bus_number), '[^A-Z0-9]', '', 'g')
WHERE plate_key IS NULL;

CREATE INDEX IF NOT EXISTS buses_plate_key
    ON transport_portal.buses (plate_key);

ALTER TABLE transport_portal.events
    ADD COLUMN IF NOT EXISTS idempotency_key varchar(128);

CREATE UNIQUE INDEX IF NOT EXISTS events_idempotency_key
    ON transport_portal.events (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS events_dedup
    ON transport_portal.events (bus_number, direction, camera_id, timestamp DESC);

DO $$
DECLARE api_role text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'transport_portal_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON transport_portal.bus_states TO transport_portal_app;
    END IF;
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON transport_portal.bus_states FROM %I', api_role);
        END IF;
    END LOOP;
END $$;

COMMIT;
