-- Adds a table for whole-account, per-mode stat snapshots (not per-vehicle).
-- Backed by a confirmed live source: https://thunderskill.com/en/stat/<name>/export/json
-- This powers a player-profile page; it is NOT what feeds vehicle_stats_daily.

CREATE TABLE player_overall_stats (
    id              BIGSERIAL PRIMARY KEY,
    player_id       INTEGER NOT NULL REFERENCES players(id),
    mode            game_mode NOT NULL,
    wins            INTEGER,
    battles         INTEGER,
    deaths          INTEGER,
    win_rate        NUMERIC(5,2),
    kd_ratio        NUMERIC(5,2),
    kills_per_battle NUMERIC(5,2),   -- source field "kb"
    source_last_stat TIMESTAMPTZ,     -- the source's own "last_stat" timestamp, for staleness checks
    sampled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_player_overall_stats_player_mode_time
    ON player_overall_stats (player_id, mode, sampled_at);
