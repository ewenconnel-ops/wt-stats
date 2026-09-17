-- WT Stats: initial schema
-- Run with: psql $DATABASE_URL -f migrations/001_init.sql

CREATE TYPE vehicle_class AS ENUM ('ground', 'air', 'naval');
CREATE TYPE game_mode AS ENUM ('arcade', 'realistic', 'simulator');

-- Reference table of vehicles, seeded from War Thunder Wiki data / static export.
CREATE TABLE vehicles (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,          -- url-safe identifier, e.g. "leopard-2a6"
    nation          TEXT NOT NULL,                  -- "Germany", "USSR", etc.
    class           vehicle_class NOT NULL,
    br_arcade       NUMERIC(3,1),
    br_realistic    NUMERIC(3,1),
    br_sim          NUMERIC(3,1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_vehicles_nation_class ON vehicles (nation, class);

-- Known squadrons, populated lazily as we encounter them.
CREATE TABLE squadrons (
    id              SERIAL PRIMARY KEY,
    tag             TEXT NOT NULL,
    name            TEXT NOT NULL,
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tag, name)
);

-- Known players, populated lazily by the collector.
CREATE TABLE players (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    squadron_id     INTEGER REFERENCES squadrons(id),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Raw per-player, per-vehicle snapshots as scraped by the collector.
-- Intentionally append-only / immutable: each row is "as of sampled_at",
-- so the aggregator can compute deltas between successive snapshots
-- for the same player+vehicle instead of trusting cumulative counters blindly.
CREATE TABLE player_samples (
    id              BIGSERIAL PRIMARY KEY,
    player_id       INTEGER NOT NULL REFERENCES players(id),
    vehicle_id      INTEGER NOT NULL REFERENCES vehicles(id),
    mode            game_mode NOT NULL,
    wins            INTEGER NOT NULL,
    losses          INTEGER NOT NULL,
    kills           INTEGER NOT NULL,
    deaths          INTEGER NOT NULL,
    battles         INTEGER NOT NULL,
    sampled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_player_samples_vehicle_mode_time
    ON player_samples (vehicle_id, mode, sampled_at);
CREATE INDEX idx_player_samples_player_vehicle_time
    ON player_samples (player_id, vehicle_id, sampled_at);

-- Rolled-up daily stats per vehicle+mode. This is the ONLY table the
-- public API reads from — never player_samples directly — so page
-- loads stay fast regardless of how much raw data has piled up.
CREATE TABLE vehicle_stats_daily (
    vehicle_id      INTEGER NOT NULL REFERENCES vehicles(id),
    mode            game_mode NOT NULL,
    date            DATE NOT NULL,
    win_rate        NUMERIC(5,2) NOT NULL,   -- smoothed, 0-100
    kd_ratio        NUMERIC(5,2) NOT NULL,
    avg_kills       NUMERIC(5,2) NOT NULL,
    sample_size     INTEGER NOT NULL,         -- distinct player_samples contributing
    raw_win_rate    NUMERIC(5,2) NOT NULL,    -- pre-smoothing, for transparency
    PRIMARY KEY (vehicle_id, mode, date)
);
CREATE INDEX idx_vehicle_stats_daily_mode_date ON vehicle_stats_daily (mode, date);

-- Convenience view: latest date per vehicle+mode, what the API queries by default.
CREATE VIEW vehicle_stats_latest AS
SELECT DISTINCT ON (vehicle_id, mode)
    vehicle_id, mode, date, win_rate, kd_ratio, avg_kills, sample_size, raw_win_rate
FROM vehicle_stats_daily
ORDER BY vehicle_id, mode, date DESC;
