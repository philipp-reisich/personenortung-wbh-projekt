# path: personenortung-wbh-projekt/api/schemas.py
"""Pydantic models for request and response payloads.

These classes define the structure of data exchanged via the API. By using
Pydantic models we ensure that incoming and outgoing JSON is validated and
well-defined. Many of the fields correspond to database columns but may omit
internal details such as primary keys or hashes.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
import json


class Role(str, Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class AnchorBase(BaseModel):
    id: str = Field(..., description="Identifier of the anchor, e.g. A-01")
    name: Optional[str] = Field(None, description="Human‑readable name")
    x: float
    y: float
    z: float = 0.0


class AnchorCreate(AnchorBase):
    pass


class AnchorOut(AnchorBase):
    created_at: datetime


class WearableBase(BaseModel):
    uid: str = Field(..., description="Unique identifier of the wearable device")
    person_ref: Optional[str] = Field(
        None, description="Reference to associated person"
    )
    role: Optional[str] = Field(None, description="User role or tag type")


class WearableCreate(WearableBase):
    pass


class WearableOut(WearableBase):
    created_at: datetime


class PositionOut(BaseModel):
    id: int
    ts: datetime
    uid: str
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    method: Optional[str] = None
    q_score: Optional[float] = None
    zone: Optional[str] = None
    # Neue Felder aus der DB
    nearest_anchor_id: Optional[str] = None
    dist_m: Optional[float] = None
    num_anchors: Optional[int] = None
    dists: Optional[Dict[str, float]] = None

    @validator("dists", pre=True)
    def convert_dists(cls, v):
        """Convert JSONB string to dict if necessary"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except:
                return {}
        elif isinstance(v, dict):
            return v
        return {}


class ScanOut(BaseModel):
    """Schema für letzte Scan-Daten eines Wearables"""

    uid: str
    last_rssi: Optional[float] = None
    last_battery: Optional[float] = None
    last_temp_c: Optional[float] = None
    last_tx_power: Optional[int] = None
    last_emergency: Optional[bool] = None
    last_seen: Optional[datetime] = None


class AnchorStatusOut(BaseModel):
    """Schema für Anchor-Status"""

    anchor_id: str
    ts: Optional[datetime] = None
    ip: Optional[str] = None
    fw: Optional[str] = None
    uptime_s: Optional[int] = None
    wifi_rssi: Optional[int] = None
    heap_free: Optional[int] = None
    heap_min: Optional[int] = None
    chip_temp_c: Optional[float] = None
    tx_power_dbm: Optional[int] = None
    ble_scan_active: Optional[bool] = None

    @validator("ip", pre=True)
    def convert_ip(cls, v):
        """Convert INET/IPv4Address to string"""
        if v is None:
            return None
        return str(v)


class EventType(str, Enum):
    emergency = "emergency"
    geofence_enter = "geofence_enter"
    geofence_exit = "geofence_exit"
    battery_low = "battery_low"


class EventOut(BaseModel):
    id: int
    ts: datetime
    uid: str
    type: EventType
    severity: int
    details: Optional[str]
    handled_by: Optional[str]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str
    password: str
    role: Role


class UserOut(BaseModel):
    uid: str
    username: str
    role: Role
    created_at: datetime


class GeofencePolygon(BaseModel):
    name: str
    points: List[tuple]


class ZoneOut(BaseModel):
    id: int
    name: str
    polygon: List[tuple]
    created_at: datetime
