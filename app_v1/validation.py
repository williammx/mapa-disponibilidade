import json
from collections import Counter

from models import Lot


def validate_lots(lots: list[Lot]) -> dict:
    issues = []
    names = [lot.name for lot in lots if lot.name]
    duplicate_names = {name for name, count in Counter(names).items() if count > 1}
    for lot in lots:
        if not lot.name:
            issues.append({"type": "missing_name", "severity": "warning", "lot_id": lot.id, "message": "Lote sem nome."})
        if lot.name in duplicate_names:
            issues.append({"type": "duplicate_name", "severity": "warning", "lot_id": lot.id, "message": f"Nome duplicado: {lot.name}."})
        try:
            geometry = json.loads(lot.geometry_json)
        except json.JSONDecodeError:
            issues.append({"type": "invalid_geometry_json", "severity": "error", "lot_id": lot.id, "message": "Geometria nao e JSON valido."})
            continue
        points = geometry.get("points") or geometry.get("coordinates") or []
        if len(points) < 3:
            issues.append({"type": "invalid_geometry", "severity": "error", "lot_id": lot.id, "message": "Geometria tem menos de 3 pontos."})
        if lot.area_m2 is not None and lot.area_m2 <= 0:
            issues.append({"type": "invalid_area", "severity": "warning", "lot_id": lot.id, "message": "Area invalida."})
    return {
        "lot_count": len(lots),
        "issue_count": len(issues),
        "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
        "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
        "issues": issues[:500],
    }
