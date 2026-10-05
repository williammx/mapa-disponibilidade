"""Project-scoped availability truth. Callers own commit/rollback."""
import hashlib
import json

from fastapi import HTTPException
from models import (IntegrationAvailabilityRequest, IntegrationEvent, IntegrationUnit,
                    IntegrationUnitLot, Lot, Project, utcnow)
from .serialization import dt

STATUSES = ('available', 'sold', 'reserved', 'blocked')


def lock_project(db, project_id):
    # Serialize every event allocation through commit, not just status CAS.
    db.query(Project).filter(Project.id == project_id).update(
        {'updated_at': Project.updated_at}, synchronize_session=False)
    db.expire_all()


def unit_dict(unit):
    return {key: getattr(unit, key) for key in ('id', 'organization_id', 'project_id',
        'external_system', 'external_unit_id', 'block', 'name', 'status', 'revision',
        'mapping_state', 'lot_id')} | {'created_at': dt(unit.created_at), 'updated_at': dt(unit.updated_at)}


def event_dict(event):
    return {'id': event.id, 'organization_id': event.organization_id, 'project_id': event.project_id,
            'event_type': event.event_type, 'payload': json.loads(event.payload_json), 'created_at': dt(event.created_at)}


def get_unit(db, project, unit_id):
    unit = db.get(IntegrationUnit, unit_id)
    if not unit or unit.project_id != project.id or unit.organization_id != project.organization_id:
        raise HTTPException(404, 'Unit not found.')
    return unit


def attach(db, unit, lot):
    link = db.get(IntegrationUnitLot, lot.id)
    if link and link.unit_id != unit.id:
        raise HTTPException(409, 'Lot is already bound to another unit.')
    existing = db.query(IntegrationUnitLot).filter_by(unit_id=unit.id, project_version_id=lot.project_version_id).first()
    if existing and existing.lot_id != lot.id:
        raise HTTPException(409, 'Unit already has a lot in this version.')
    if not link:
        db.add(IntegrationUnitLot(lot_id=lot.id, unit_id=unit.id, project_version_id=lot.project_version_id))
    unit.lot_id = lot.id
    unit.mapping_state = 'mapped'
    lot.status = unit.status
    db.flush()


def reference(db, unit, system, external_id):
    if unit.external_system and (unit.external_system, unit.external_unit_id) != (system, external_id):
        raise HTTPException(409, 'External reference is immutable once bound.')
    conflict = db.query(IntegrationUnit).filter_by(project_id=unit.project_id,
        external_system=system, external_unit_id=external_id).first()
    if conflict and conflict.id != unit.id:
        raise HTTPException(409, 'External reference is already bound.')
    unit.external_system, unit.external_unit_id = system, external_id
    db.flush()
    return unit


def bind(db, project, system, external_id, lot_id):
    lock_project(db, project.id)
    lot = db.get(Lot, lot_id)
    if not lot or lot.project_id != project.id:
        raise HTTPException(404, 'Lot not found.')
    unit = db.query(IntegrationUnit).filter_by(project_id=project.id,
        external_system=system, external_unit_id=external_id).first()
    link = db.get(IntegrationUnitLot, lot.id)
    if link:
        linked = get_unit(db, project, link.unit_id)
        if unit and unit.id != linked.id:
            provisional = (not linked.external_system and linked.revision == 0 and
                linked.mapping_state == 'needs_reconciliation' and
                db.query(IntegrationUnitLot).filter_by(unit_id=linked.id).count() == 1)
            if not provisional or (linked.status in ('sold', 'reserved') and unit.status != linked.status):
                raise HTTPException(409, 'Lot is already bound to another unit.')
            db.delete(link)
            db.flush()
            db.delete(linked)
            db.flush()
        else:
            unit = linked
    if not unit:
        unit = IntegrationUnit(organization_id=project.organization_id, project_id=project.id,
            block=lot.block, name=lot.name, status=lot.status)
        db.add(unit)
        db.flush()
    reference(db, unit, system, external_id)
    attach(db, unit, lot)
    return unit


def trusted_label(row):
    import re
    block, name = (row.block or '').strip(), (row.name or '').strip()
    # Converter synthesizes Lote N when no label exists: never use it as identity.
    if not block or not name or re.fullmatch(r'Lote\s+\d+', name, re.I):
        return None
    return block, name


def reconcile_version(db, project, version_id, converted=False):
    """Carry identity only by unique real block/name; keep uncertain shapes blocked."""
    from collections import Counter
    lock_project(db, project.id)
    lots = db.query(Lot).filter_by(project_id=project.id, project_version_id=version_id).all()
    units = db.query(IntegrationUnit).filter_by(project_id=project.id).all()
    lot_counts = Counter(trusted_label(lot) for lot in lots)
    unit_counts = Counter(trusted_label(unit) for unit in units)
    candidates = {trusted_label(unit): unit for unit in units if trusted_label(unit)}
    seen = set()
    for lot in lots:
        link = db.get(IntegrationUnitLot, lot.id)
        if link:
            unit = get_unit(db, project, link.unit_id)
        else:
            label = trusted_label(lot)
            unit = candidates.get(label) if label and lot_counts[label] == unit_counts[label] == 1 else None
            if unit:
                same_version = db.query(IntegrationUnitLot).filter_by(unit_id=unit.id, project_version_id=version_id).first()
                if same_version and same_version.lot_id != lot.id:
                    unit = None
            if not unit:
                uncertain = bool(units) or not label or lot_counts[label] != 1
                # Existing persisted sold/reserved/blocked is never reopened.
                status = lot.status if not converted else ('blocked' if uncertain else 'available')
                if uncertain and status == 'available':
                    status = 'blocked'
                unit = IntegrationUnit(organization_id=project.organization_id, project_id=project.id,
                    block=lot.block, name=lot.name, status=status,
                    mapping_state='needs_reconciliation' if uncertain else 'mapped')
                db.add(unit)
                db.flush()
        state = unit.mapping_state
        attach(db, unit, lot)
        unit.mapping_state = state
        seen.add(unit.id)
    for unit in units:
        if unit.id not in seen:
            unit.mapping_state = 'needs_reconciliation'
            unit.lot_id = None
    db.flush()
    return lots


def set_lot_status(db, project, lot, status, source='editor', expected_revision=None):
    from models import new_id
    lock_project(db, project.id)
    link = db.get(IntegrationUnitLot, lot.id)
    if not link:
        unit = IntegrationUnit(organization_id=project.organization_id, project_id=project.id,
            block=lot.block, name=lot.name, status=lot.status)
        db.add(unit)
        db.flush()
        attach(db, unit, lot)
    else:
        unit = get_unit(db, project, link.unit_id)
    if unit.status == status:
        return None
    return change(db, project, unit.id, status,
        unit.revision if expected_revision is None else expected_revision, new_id(), source)


def html_data(html):
    """Decode only converter JSON; never evaluate uploaded JavaScript."""
    import re
    match = re.search(r'\bINIT\s*=\s*', html)
    if not match:
        return None
    try:
        data, length = json.JSONDecoder().raw_decode(html[match.end():])
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return match.end(), match.end() + length, data


def render_live_html(db, version, html):
    """Read-only projection, leaving stored artifacts untouched."""
    decoded = html_data(html)
    if not decoded:
        return html
    start, end, data = decoded
    lots = db.query(Lot).filter_by(project_id=version.project_id, project_version_id=version.id).all()
    by_index = {lot.external_id: lot for lot in lots}
    colors = ['#26d07c', '#6e6d67', '#e0613b', '#7c8594']
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        lot = by_index.get(str(item.get('index', index)))
        if lot:
            status_index = STATUSES.index(lot.status) if lot.status in STATUSES else 3
            item.update(s=status_index, color=colors[status_index], availability=lot.status)
    # Script-safe JSON even for labels containing </script>.
    encoded = json.dumps(data, separators=(',', ':'), ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    html = html[:start] + encoded + html[end:]
    html = html.replace('NAMES=["Disponivel","Vendido","Reservado"]', 'NAMES=["Disponivel","Vendido","Reservado","Bloqueado"]')
    html = html.replace('STATUS_KEYS=["disponivel","vendido","reservado"]', 'STATUS_KEYS=["disponivel","vendido","reservado","bloqueado"]')
    html = html.replace('statusColors=["#26d07c","#6e6d67","#e0613b"]', 'statusColors=["#26d07c","#6e6d67","#e0613b","#7c8594"]')
    # Authoritative server state must not be replaced by a saved browser draft.
    import re
    html = re.sub(r'MAP_BUILT_AT=\d+', 'MAP_BUILT_AT=9007199254740991', html)
    return html


def persist_editor_lots(db, project, version, html, base_version_id=None, expected_revisions=None, items=None):
    from .worker import extract_lots_from_info
    from models import ProjectVersion
    expected_revisions = expected_revisions or {}
    lock_project(db, project.id)
    decoded = html_data(html)
    items = items if items is not None else (decoded[2] if decoded else [])
    if not items and db.query(IntegrationUnit).filter_by(project_id=project.id).first():
        raise HTTPException(422, 'A synchronized map must contain converter lot data.')
    base = db.get(ProjectVersion, base_version_id) if base_version_id else None
    if base_version_id and (not base or base.project_id != project.id):
        raise HTTPException(404, 'Base version not found.')
    base_lots = db.query(Lot).filter_by(project_id=project.id, project_version_id=base.id).all() if base else []
    by_index = {lot.external_id: lot for lot in base_lots}
    lots = extract_lots_from_info({'data': items}, project.id, version.id)
    if len({lot.external_id for lot in lots}) != len(lots):
        raise HTTPException(422, 'Editor lot indices must be unique within a version.')
    db.add_all(lots)
    db.flush()
    for lot, item in zip(lots, items):
        old = by_index.get(lot.external_id)
        if not old:
            continue
        link = db.get(IntegrationUnitLot, old.id)
        if not link:
            # Establish identity in the explicit base, not by cross-PDF index.
            unit = IntegrationUnit(organization_id=project.organization_id, project_id=project.id,
                block=old.block, name=old.name, status=old.status)
            db.add(unit)
            db.flush()
            attach(db, unit, old)
        else:
            unit = get_unit(db, project, link.unit_id)
        desired = STATUSES[int(item.get('s', 0))] if int(item.get('s', 0)) in range(len(STATUSES)) else 'blocked'
        if desired != unit.status:
            if unit.id not in expected_revisions:
                raise HTTPException(409, 'Reload editor to obtain unit revisions before changing availability.')
            set_lot_status(db, project, old, desired, expected_revision=expected_revisions[unit.id])
        attach(db, unit, lot)
    reconcile_version(db, project, version.id)
    version.lot_count = len(lots)
    return lots


def change(db, project, unit_id, status, expected_revision, event_id, source, reason=None):
    lock_project(db, project.id)
    unit = get_unit(db, project, unit_id)
    if status not in STATUSES:
        raise HTTPException(422, 'Invalid availability status.')
    digest = hashlib.sha256(json.dumps([unit_id, status, expected_revision, event_id, source, reason],
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    system = unit.external_system or source
    previous_request = db.query(IntegrationAvailabilityRequest).filter_by(
        project_id=project.id, external_system=system, event_id=event_id).first()
    if previous_request:
        if previous_request.request_hash != digest:
            raise HTTPException(409, 'Event ID was used with a different request.')
        return json.loads(previous_request.outcome_json) | {'replayed': True}
    before = unit.status
    changed = db.query(IntegrationUnit).filter_by(id=unit.id, revision=expected_revision).update(
        {'status': status, 'revision': IntegrationUnit.revision + 1, 'updated_at': utcnow()}, synchronize_session=False)
    if not changed:
        raise HTTPException(409, 'Stale unit revision.')
    db.refresh(unit)
    links = db.query(IntegrationUnitLot).filter_by(unit_id=unit.id).all()
    db.query(Lot).filter(Lot.id.in_([link.lot_id for link in links]), Lot.project_id == project.id).update(
        {'status': status, 'updated_at': utcnow()}, synchronize_session=False)
    event = IntegrationEvent(organization_id=project.organization_id, project_id=project.id,
        event_type='unit.availability.changed', payload_json=json.dumps({
            'event_id': event_id, 'unit_id': unit.id, 'external_system': unit.external_system,
            'external_unit_id': unit.external_unit_id, 'previous_status': before, 'new_status': status,
            'revision': unit.revision, 'source': source, 'timestamp': dt(utcnow())}))
    db.add(event)
    db.flush()
    result = {'unit': unit_dict(unit), 'event': event_dict(event), 'replayed': False}
    db.add(IntegrationAvailabilityRequest(project_id=project.id, external_system=system,
        event_id=event_id, request_hash=digest, outcome_json=json.dumps(result)))
    db.flush()
    return result
