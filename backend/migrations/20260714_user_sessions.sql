-- Persisted user sessions for trajectory visualization.
-- Run from backend with a configured PostgreSQL connection, for example:
-- psql "$DATABASE_URL" -f migrations/20260714_user_sessions.sql

CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(150) UNIQUE NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    checkin_count INTEGER NOT NULL,
    dataset VARCHAR(20) NOT NULL DEFAULT 'TKY'
);

ALTER TABLE checkins
    ADD COLUMN IF NOT EXISTS session_id VARCHAR(150);

ALTER TABLE checkins
    ADD COLUMN IF NOT EXISTS sequence_no INTEGER;

CREATE INDEX IF NOT EXISTS idx_checkins_user_id
    ON checkins(user_id);

CREATE INDEX IF NOT EXISTS idx_checkins_venue_id
    ON checkins(venue_id);

CREATE INDEX IF NOT EXISTS idx_checkins_user_timestamp
    ON checkins(user_id, utc_timestamp);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id
    ON sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_checkins_session_sequence
    ON checkins(session_id, sequence_no);
