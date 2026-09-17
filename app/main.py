"""
WT Stats public API.

Every route here reads ONLY from vehicle_stats_daily / vehicle_stats_latest —
never from the raw player_samples table — so response times stay flat no
matter how much history the collector has piled up. No auth, no tiers:
every endpoint below is free and unrestricted.

Run locally:
    uvicorn app.main:app --reload
"""
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    CompareRequest,
    HeatmapCell,
    HeatmapOut,
    Mode,
    VehicleClass,
    VehicleDetailOut,
    VehicleOut,
    VehicleStatsOut,
)

app = FastAPI(title="WT Stats API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to the frontend's origin before going live
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# BR brackets used by the heatmap — matches the wireframe's columns.
BR_BRACKETS = [
    (1.0, 2.0), (2.3, 3.7), (4.0, 5.3), (5.7, 7.0),
    (7.3, 8.7), (9.0, 10.3), (10.7, 12.0),
]


def _bracket_label(lo: float, hi: float) -> str:
    return f"{lo:.1f}\u2013{hi:.1f}"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(
    nation: str | None = None,
    vehicle_class: VehicleClass | None = Query(default=None, alias="class"),
    q: str | None = Query(default=None, description="fuzzy name search"),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    sql = "SELECT id, name, slug, nation, class, br_arcade, br_realistic, br_sim FROM vehicles WHERE true"
    params: dict = {}
    if nation:
        sql += " AND nation = :nation"
        params["nation"] = nation
    if vehicle_class:
        sql += " AND class = :vehicle_class"
        params["vehicle_class"] = vehicle_class
    if q:
        sql += " AND name ILIKE :q"
        params["q"] = f"%{q}%"
    sql += " ORDER BY name LIMIT :limit"
    params["limit"] = limit

    rows = db.execute(text(sql), params).mappings().all()
    return [dict(r) | {"class_": r["class"]} for r in rows]


@app.get("/vehicles/{slug}", response_model=VehicleDetailOut)
def get_vehicle(slug: str, db: Session = Depends(get_db)) -> dict:
    vehicle = db.execute(
        text("SELECT id, name, slug, nation, class, br_arcade, br_realistic, br_sim "
             "FROM vehicles WHERE slug = :slug"),
        {"slug": slug},
    ).mappings().first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="vehicle not found")

    stats = db.execute(
        text("SELECT vehicle_id, mode, date, win_rate, kd_ratio, avg_kills, sample_size "
             "FROM vehicle_stats_latest WHERE vehicle_id = :vid"),
        {"vid": vehicle["id"]},
    ).mappings().all()

    return dict(vehicle) | {"class_": vehicle["class"], "stats": [dict(s) for s in stats]}


@app.get("/heatmap", response_model=HeatmapOut)
def heatmap(
    mode: Mode = "realistic",
    vehicle_class: VehicleClass = Query(default="ground", alias="class"),
    db: Session = Depends(get_db),
) -> dict:
    """
    One row per nation, one cell per BR bracket, averaged (sample-weighted)
    across every vehicle of that nation/class whose BR falls in the bracket.
    """
    br_column = {"arcade": "br_arcade", "realistic": "br_realistic", "simulator": "br_sim"}[mode]

    cells: list[dict] = []
    nations = [r[0] for r in db.execute(
        text("SELECT DISTINCT nation FROM vehicles WHERE class = :c ORDER BY nation"),
        {"c": vehicle_class},
    ).all()]

    for nation in nations:
        for lo, hi in BR_BRACKETS:
            row = db.execute(
                text(f"""
                    SELECT
                        SUM(s.win_rate * s.sample_size) / NULLIF(SUM(s.sample_size), 0) AS win_rate,
                        SUM(s.sample_size) AS sample_size
                    FROM vehicle_stats_latest s
                    JOIN vehicles v ON v.id = s.vehicle_id
                    WHERE v.nation = :nation
                      AND v.class = :class
                      AND v.{br_column} BETWEEN :lo AND :hi
                      AND s.mode = :mode
                """),
                {"nation": nation, "class": vehicle_class, "lo": lo, "hi": hi, "mode": mode},
            ).mappings().first()

            if row and row["win_rate"] is not None:
                cells.append({
                    "nation": nation,
                    "br_bracket": _bracket_label(lo, hi),
                    "win_rate": round(float(row["win_rate"]), 1),
                    "sample_size": int(row["sample_size"]),
                })

    return {"mode": mode, "vehicle_class": vehicle_class, "cells": cells}


@app.post("/compare", response_model=list[VehicleDetailOut])
def compare(req: CompareRequest, db: Session = Depends(get_db)) -> list[dict]:
    if not (1 < len(req.vehicle_ids) <= 6):
        raise HTTPException(status_code=400, detail="pass between 2 and 6 vehicle_ids")

    out = []
    for vid in req.vehicle_ids:
        vehicle = db.execute(
            text("SELECT id, name, slug, nation, class, br_arcade, br_realistic, br_sim "
                 "FROM vehicles WHERE id = :vid"),
            {"vid": vid},
        ).mappings().first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"vehicle {vid} not found")

        stat = db.execute(
            text("SELECT vehicle_id, mode, date, win_rate, kd_ratio, avg_kills, sample_size "
                 "FROM vehicle_stats_latest WHERE vehicle_id = :vid AND mode = :mode"),
            {"vid": vid, "mode": req.mode},
        ).mappings().first()

        out.append(dict(vehicle) | {"class_": vehicle["class"], "stats": [dict(stat)] if stat else []})

    return out
