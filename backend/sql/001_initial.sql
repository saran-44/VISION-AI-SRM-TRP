-- Initial private application schema. Run ONCE as a database administrator.
-- This deliberately fails if the schema already exists; it never drops data.
-- Do not expose transport_portal through Supabase's Data API.
BEGIN;
CREATE SCHEMA transport_portal;
REVOKE ALL ON SCHEMA transport_portal FROM PUBLIC;

CREATE TABLE transport_portal.schema_version (
    version integer PRIMARY KEY
);
INSERT INTO transport_portal.schema_version (version) VALUES (1);

CREATE TABLE transport_portal.users (
    _id varchar(24) PRIMARY KEY,
    email varchar(254) NOT NULL UNIQUE,
    password_hash text,
    role varchar(32) NOT NULL,
    active boolean NOT NULL DEFAULT true,
    auth_provider text,
    firebase_uid text,
    demo_user boolean NOT NULL DEFAULT false,
    created_at timestamp,
    updated_at timestamp,
    last_sign_in_at timestamp
);
CREATE TABLE transport_portal.buses (
    _id varchar(24) PRIMARY KEY,
    bus_number varchar(20) NOT NULL UNIQUE,
    registration_number text,
    route text,
    capacity integer,
    insurance_expiry text,
    status text,
    notes text,
    demo boolean NOT NULL DEFAULT false,
    created_at timestamp,
    updated_at timestamp
);
CREATE TABLE transport_portal.drivers (
    _id varchar(24) PRIMARY KEY,
    name text NOT NULL,
    phone text,
    bus_number varchar(20) NOT NULL,
    license_number text,
    notes text,
    active boolean NOT NULL DEFAULT true,
    demo boolean NOT NULL DEFAULT false,
    created_at timestamp,
    updated_at timestamp
);
CREATE TABLE transport_portal.events (
    _id varchar(24) PRIMARY KEY,
    bus_number varchar(20) NOT NULL,
    direction varchar(3) NOT NULL,
    gate text NOT NULL,
    camera_id text NOT NULL,
    confidence double precision NOT NULL,
    timestamp timestamp NOT NULL,
    created_at timestamp,
    source text,
    flag_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    flagged boolean NOT NULL DEFAULT false,
    demo boolean NOT NULL DEFAULT false
);
CREATE TABLE transport_portal.audit_logs (
    _id varchar(24) PRIMARY KEY,
    timestamp timestamp NOT NULL,
    actor text,
    role text,
    action text,
    collection text,
    record_id text,
    "before" jsonb,
    "after" jsonb,
    ip text,
    user_agent text
);
CREATE INDEX drivers_name ON transport_portal.drivers (name);
CREATE INDEX drivers_bus_number ON transport_portal.drivers (bus_number);
CREATE INDEX events_timestamp ON transport_portal.events (timestamp DESC, _id DESC);
CREATE INDEX events_bus_timestamp ON transport_portal.events (bus_number, timestamp DESC);
CREATE INDEX events_gate_direction_timestamp ON transport_portal.events (gate, direction, timestamp DESC);
CREATE INDEX events_camera_timestamp ON transport_portal.events (camera_id, timestamp DESC);
CREATE INDEX events_flagged_timestamp ON transport_portal.events (flagged, timestamp DESC);
CREATE INDEX events_reasons ON transport_portal.events USING gin (flag_reasons);
CREATE INDEX audit_timestamp ON transport_portal.audit_logs (timestamp DESC);
CREATE INDEX audit_actor ON transport_portal.audit_logs (actor, timestamp DESC);
-- Supabase may set table default privileges for its API roles. Deny those
-- roles explicitly as well as PUBLIC; the Flask database login is granted
-- only the privileges it needs by scripts/configure_supabase.py.
REVOKE ALL ON ALL TABLES IN SCHEMA transport_portal FROM PUBLIC;
DO $$
DECLARE api_role text;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA transport_portal FROM %I', api_role);
            EXECUTE format('REVOKE ALL ON SCHEMA transport_portal FROM %I', api_role);
        END IF;
    END LOOP;
END $$;
COMMIT;
