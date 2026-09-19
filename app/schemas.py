from datetime import date as date_
from typing import Literal

from pydantic import BaseModel

Mode = Literal["arcade", "realistic", "simulator"]
VehicleClass = Literal["ground", "air", "naval"]


class VehicleOut(BaseModel):
    id: int
    name: str
    slug: str
    nation: str
    class_: VehicleClass
    br_arcade: float | None
    br_realistic: float | None
    br_sim: float | None

    model_config = {"populate_by_name": True}


class VehicleStatsOut(BaseModel):
    vehicle_id: int
    mode: Mode
    date: date_
    win_rate: float
    kd_ratio: float
    avg_kills: float
    sample_size: int


class VehicleDetailOut(VehicleOut):
    stats: list[VehicleStatsOut]  # one entry per mode, latest date


class HeatmapCell(BaseModel):
    nation: str
    br_bracket: str          # e.g. "7.3-8.7"
    win_rate: float
    sample_size: int


class HeatmapOut(BaseModel):
    mode: Mode
    vehicle_class: VehicleClass
    cells: list[HeatmapCell]


class CompareRequest(BaseModel):
    vehicle_ids: list[int]
    mode: Mode = "realistic"


class PlayerModeStatsOut(BaseModel):
    mode: Mode
    wins: int | None
    battles: int | None
    deaths: int | None
    win_rate: float | None
    kd_ratio: float | None
    kills_per_battle: float | None


class PlayerProfileOut(BaseModel):
    name: str
    stats: list[PlayerModeStatsOut]
    source_last_stat: str | None = None
