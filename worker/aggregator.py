"""
Aggregator: rolls up player_samples into vehicle_stats_daily.

Run once a day (after the collector's runs for that day), or on-demand.
This is the ONLY writer of vehicle_stats_daily; the API only ever reads it.

Smoothing: a vehicle with very few sampled battles can show a wild win
rate (e.g. 2 battles, 2 wins = "100%"). We pull small-sample vehicles
toward the class+mode average using a simple Bayesian shrinkage:

    smoothed = (raw_win_rate * n + prior_mean * k) / (n + k)

where `k` is how many "phantom average battles" we blend in — bigger k
pulls small samples harder toward the mean. Tune k per mode once we have
real data; 50 is a reasonable starting point.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal

logger = logging.getLogger("wt_stats.aggregator")

SHRINKAGE_K = 50


def _prior_mean(db: Session, vehicle_class: str, mode: str) -> float:
    """Class+mode-wide average win rate, used as the shrinkage target."""
    row = db.execute(
        text("""
            SELECT AVG(win_rate) FROM (
                SELECT
                    100.0 * SUM(wins)::numeric / NULLIF(SUM(wins) + SUM(losses), 0) AS win_rate
                FROM player_samples ps
                JOIN vehicles v ON v.id = ps.vehicle_id
                WHERE v.class = :class AND ps.mode = :mode
                GROUP BY ps.vehicle_id
            ) per_vehicle
        """),
        {"class": vehicle_class, "mode": mode},
    ).scalar()
    return float(row) if row is not None else 50.0


def aggregate_for_date(target_date: date | None = None) -> None:
    target_date = target_date or date.today()
    db = SessionLocal()
    try:
        vehicles = db.execute(text("SELECT id, class FROM vehicles")).mappings().all()
        modes = ["arcade", "realistic", "simulator"]

        # cache prior means per (class, mode) so we don't recompute per vehicle
        priors: dict[tuple[str, str], float] = {}

        rows_written = 0
        for mode in modes:
            for vehicle in vehicles:
                key = (vehicle["class"], mode)
                if key not in priors:
                    priors[key] = _prior_mean(db, *key)
                prior_mean = priors[key]

                agg = db.execute(
                    text("""
                        SELECT
                            SUM(wins) AS wins,
                            SUM(losses) AS losses,
                            SUM(kills) AS kills,
                            SUM(deaths) AS deaths,
                            SUM(battles) AS battles,
                            COUNT(*) AS sample_size
                        FROM player_samples
                        WHERE vehicle_id = :vid AND mode = :mode
                    """),
                    {"vid": vehicle["id"], "mode": mode},
                ).mappings().first()

                if not agg or not agg["battles"]:
                    continue

                n = agg["wins"] + agg["losses"]
                raw_win_rate = 100.0 * agg["wins"] / n if n else 0.0
                smoothed = (raw_win_rate * n + prior_mean * SHRINKAGE_K) / (n + SHRINKAGE_K)
                kd_ratio = agg["kills"] / agg["deaths"] if agg["deaths"] else float(agg["kills"])
                avg_kills = agg["kills"] / agg["battles"] if agg["battles"] else 0.0

                db.execute(
                    text("""
                        INSERT INTO vehicle_stats_daily
                            (vehicle_id, mode, date, win_rate, kd_ratio, avg_kills, sample_size, raw_win_rate)
                        VALUES
                            (:vid, :mode, :date, :win_rate, :kd_ratio, :avg_kills, :sample_size, :raw_win_rate)
                        ON CONFLICT (vehicle_id, mode, date) DO UPDATE SET
                            win_rate = EXCLUDED.win_rate,
                            kd_ratio = EXCLUDED.kd_ratio,
                            avg_kills = EXCLUDED.avg_kills,
                            sample_size = EXCLUDED.sample_size,
                            raw_win_rate = EXCLUDED.raw_win_rate
                    """),
                    {
                        "vid": vehicle["id"],
                        "mode": mode,
                        "date": target_date,
                        "win_rate": round(smoothed, 2),
                        "kd_ratio": round(kd_ratio, 2),
                        "avg_kills": round(avg_kills, 2),
                        "sample_size": agg["sample_size"],
                        "raw_win_rate": round(raw_win_rate, 2),
                    },
                )
                rows_written += 1

        db.commit()
        logger.info("aggregation complete for %s: %d rows written", target_date, rows_written)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    aggregate_for_date()
