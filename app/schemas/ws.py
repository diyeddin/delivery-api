"""
Pydantic models for WebSocket message validation.
"""
from pydantic import BaseModel, field_validator
from typing import Literal, Optional, Union
from enum import Enum


class WSMessageType(str, Enum):
    ping = "ping"
    location_update = "location_update"
    status_update = "status_update"


class PingMessage(BaseModel):
    type: Literal["ping"]


class LocationUpdateMessage(BaseModel):
    type: Literal["location_update"]
    latitude: float
    longitude: float
    heading: Optional[float] = None

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("latitude must be between -90 and 90")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("longitude must be between -180 and 180")
        return v


class StatusUpdateMessage(BaseModel):
    type: Literal["status_update"]
    status: str


# Discriminated union for all incoming WS messages
IncomingWSMessage = Union[PingMessage, LocationUpdateMessage, StatusUpdateMessage]


def parse_ws_message(data: dict) -> IncomingWSMessage:
    """
    Validate and parse a raw dict into a typed WS message.
    Raises ValueError with a descriptive message on invalid input.
    """
    msg_type = data.get("type")
    if msg_type is None:
        raise ValueError("Missing required field: 'type'")

    parsers = {
        "ping": PingMessage,
        "location_update": LocationUpdateMessage,
        "status_update": StatusUpdateMessage,
    }

    parser = parsers.get(msg_type)
    if parser is None:
        raise ValueError(f"Unknown message type: '{msg_type}'")

    return parser.model_validate(data)
