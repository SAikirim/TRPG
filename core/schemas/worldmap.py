"""
World Map Agent — coordinate/geography verification, route calculation.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class RouteSegment(BaseModel):
    """Single segment of a travel route."""
    from_location: str
    to_location: str
    distance_km: float = 0.0
    travel_hours: float = 0.0
    terrain_type: str = "road"             # road / forest / mountain / river / sea
    difficulty: str = "normal"             # easy / normal / hard / dangerous


class WorldMapRequest(BaseModel):
    """Request to World Map agent."""
    validate_coordinates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{location_id, world_pos: [x,y]}] — verify positions"
    )
    calculate_route: Optional[dict[str, Any]] = Field(
        default=None,
        description="{from_location, to_location, travel_method}"
    )
    new_location_placement: Optional[dict[str, Any]] = Field(
        default=None,
        description="{location_id, proposed_pos, type} — verify placement is valid"
    )
    travel_method: str = "foot"            # foot / horse / carriage / ship
    check_terrain_consistency: bool = False


class WorldMapResponse(BaseModel):
    """Response from World Map agent."""
    coordinate_issues: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{location_id, issue, suggestion}]"
    )
    route: Optional[list[RouteSegment]] = None
    total_distance_km: float = 0.0
    total_travel_hours: float = 0.0
    placement_valid: Optional[bool] = None
    placement_issues: list[str] = Field(default_factory=list)
    terrain_warnings: list[str] = Field(default_factory=list)
    neighbor_directions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{location_id, neighbor_id, direction}] — auto-generated adjacency"
    )
