import json

from app_v1.validation import validate_lots
from models import Lot


def make_lot(name: str | None, geometry: dict | None = None, area_m2: float | None = 100.0) -> Lot:
    return Lot(
        project_id="project",
        project_version_id="version",
        external_id=name or "missing",
        name=name,
        block="Q01",
        area_m2=area_m2,
        status="available",
        geometry_json=json.dumps(geometry or {"points": [[0, 0], [1, 0], [1, 1], [0, 1]]}),
    )


def test_validate_lots_flags_missing_duplicate_and_invalid_geometry():
    lots = [
        make_lot("L001"),
        make_lot("L001"),
        make_lot(None),
        make_lot("L004", {"points": [[0, 0], [1, 0]]}, -1),
    ]

    result = validate_lots(lots)

    assert result["lot_count"] == 4
    assert result["issue_count"] >= 4
    assert any(issue["type"] == "missing_name" for issue in result["issues"])
    assert any(issue["type"] == "duplicate_name" for issue in result["issues"])
    assert any(issue["type"] == "invalid_geometry" for issue in result["issues"])
    assert any(issue["type"] == "invalid_area" for issue in result["issues"])
