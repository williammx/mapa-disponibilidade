import json
from test_integrations_api import ctx, mint, bearer, PREFIX
from models import Lot, ProjectVersion


def seed_lot(ctx, name='01', block='A', status='available', project=None):
    _, db, _, _, own, _ = ctx
    project = project or own
    version = ProjectVersion(project_id=project.id, map_html_path='unused', lot_count=1)
    db.add(version)
    db.flush()
    lot = Lot(project_id=project.id, project_version_id=version.id, external_id='0', name=name, block=block,
              status=status, geometry_json='{"points": [[0,0],[10,0],[10,10]]}')
    db.add(lot)
    db.commit()
    return lot


def test_bind_stable_unit_and_change_availability(ctx):
    client, db, _, _, project, _ = ctx
    lot = seed_lot(ctx)
    headers = bearer(mint(ctx, ['units:read', 'units:write', 'events:read']))
    root = PREFIX + '/projects/' + project.id
    response = client.post(root + '/units/bind', headers=headers,
        json={'external_system': 'colmeia', 'external_unit_id': 'U-1', 'lot_id': lot.id})
    assert response.status_code == 200, response.text
    unit = response.json()['unit']
    assert unit['revision'] == 0 and unit['lot_id'] == lot.id
    changed = client.patch(root + '/units/' + unit['id'] + '/availability', headers=headers,
        json={'status': 'sold', 'expected_revision': 0, 'event_id': 'sale-1', 'source': 'colmeia'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['unit']['revision'] == 1
    assert changed.json()['event']['event_type'] == 'unit.availability.changed'
    db.refresh(lot)
    assert lot.status == 'sold'
    listing = client.get(root + '/units', headers=headers).json()
    assert listing['total'] == 1 and listing['units'][0]['status'] == 'sold'
    feed = client.get(root + '/events', headers=headers).json()
    assert feed['events'][-1]['payload']['new_status'] == 'sold'
    assert feed['next_cursor'] == feed['events'][-1]['id']


def test_versions_keep_sold_identity_but_never_trust_converter_indices(ctx):
    from app_v1 import availability
    from models import IntegrationUnit, IntegrationUnitLot
    _, db, _, _, project, _ = ctx
    first = seed_lot(ctx, status='sold')
    unit = availability.bind(db, project, 'colmeia', 'U-1', first.id)
    db.commit()
    second = seed_lot(ctx, status='available')
    availability.reconcile_version(db, project, second.project_version_id, converted=True)
    db.commit()
    db.refresh(unit)
    db.refresh(second)
    assert unit.lot_id == second.id and second.status == 'sold'
    assert db.get(IntegrationUnitLot, first.id).unit_id == unit.id
    unknown = seed_lot(ctx, name=None, block=None, status='available')
    availability.reconcile_version(db, project, unknown.project_version_id, converted=True)
    db.commit()
    db.refresh(unknown)
    db.refresh(unit)
    assert unknown.status == 'blocked'
    assert unit.status == 'sold' and unit.mapping_state == 'needs_reconciliation'
    assert unit.lot_id is None
    assert db.query(IntegrationUnit).filter_by(project_id=project.id).count() == 2


def test_replay_returns_recorded_outcome_without_regressing_current_status(ctx):
    from models import IntegrationEvent
    client, db, _, _, project, _ = ctx
    lot = seed_lot(ctx)
    headers = bearer(mint(ctx, ['units:write']))
    root = PREFIX + '/projects/' + project.id
    unit = client.post(root + '/units/bind', headers=headers, json={
        'external_system': 'colmeia', 'external_unit_id': 'U', 'lot_id': lot.id}).json()['unit']
    url = root + '/units/' + unit['id'] + '/availability'
    payload = {'status': 'sold', 'expected_revision': 0, 'event_id': 'e1', 'source': 'colmeia'}
    first = client.patch(url, headers=headers, json=payload).json()
    assert client.patch(url, headers=headers, json=payload | {'status': 'reserved'}).status_code == 409
    assert client.patch(url, headers=headers, json=payload | {'event_id': 'e2'}).status_code == 409
    second = client.patch(url, headers=headers, json=payload | {'event_id': 'e2', 'expected_revision': 1, 'status': 'blocked'})
    assert second.status_code == 200
    replay = client.patch(url, headers=headers, json=payload).json()
    assert replay == first | {'replayed': True}
    db.refresh(lot)
    assert lot.status == 'blocked' and db.query(IntegrationEvent).count() == 2


def test_binding_conflicts_are_atomic_and_tenant_scoped(ctx):
    from models import IntegrationUnit, IntegrationUnitLot
    client, db, _, _, project, foreign = ctx
    lot = seed_lot(ctx, status='sold')
    foreign_lot = seed_lot(ctx, project=foreign)
    headers = bearer(mint(ctx, ['units:write', 'units:read', 'events:read'], project_id=project.id))
    root = PREFIX + '/projects/' + project.id
    body = {'external_system': 'colmeia', 'external_unit_id': 'U', 'lot_id': lot.id}
    assert client.post(root + '/units/bind', headers=headers, json=body).status_code == 200
    assert client.post(root + '/units/bind', headers=headers, json=body | {'external_unit_id': 'OTHER'}).status_code == 409
    assert client.post(root + '/units/bind', headers=headers, json=body | {'lot_id': foreign_lot.id}).status_code == 404
    assert client.get(PREFIX + '/projects/' + foreign.id + '/units', headers=headers).status_code == 404
    assert db.query(IntegrationUnit).count() == db.query(IntegrationUnitLot).count() == 1
    assert client.get(root + '/events?limit=0', headers=headers).status_code == 422
    restricted = bearer(mint(ctx, ['capabilities:read']))
    assert client.get(root + '/units', headers=restricted).status_code == 403
    assert client.post(root + '/units/bind', headers=restricted, json=body).status_code == 403


def test_worker_conversion_discovers_real_units_without_demo_availability(ctx, monkeypatch):
    from app_v1 import worker
    from sqlalchemy.orm import sessionmaker
    from test_integrations_api import pdf_bytes
    client, db, _, _, project, _ = ctx
    monkeypatch.setattr(worker, 'SessionLocal', sessionmaker(bind=db.bind))
    monkeypatch.setenv('SYNC_PROCESSING', 'true')
    headers = bearer(mint(ctx, ['jobs:write', 'units:read']))
    response = client.post(PREFIX + '/projects/' + project.id + '/jobs', headers=headers,
        files={'upload': ('real.pdf', pdf_bytes(), 'application/pdf')})
    assert response.status_code == 202 and response.json()['job']['status'] == 'succeeded'
    units = client.get(PREFIX + '/projects/' + project.id + '/units', headers=headers).json()['units']
    assert len(units) > 0
    assert all(unit['status'] in ('available', 'blocked') for unit in units)
    assert all(unit['lot_id'] for unit in units)


def test_internal_lot_patch_uses_shared_availability_events(ctx):
    from auth import COOKIE_NAME
    from models import IntegrationEvent, IntegrationUnit
    client, db, _, _, project, _ = ctx
    lot = seed_lot(ctx)
    client.cookies.set(COOKIE_NAME, 'test-cookie')
    response = client.patch('/api/v1/lots/' + lot.id, json={'status': 'reserved'})
    assert response.status_code == 200
    unit = db.query(IntegrationUnit).filter_by(project_id=project.id).one()
    assert unit.status == 'reserved' and unit.revision == 1
    event = db.query(IntegrationEvent).one()
    assert json.loads(event.payload_json)['source'] == 'editor'


def test_published_and_downloaded_html_reflect_live_availability(ctx, tmp_path):
    import api
    import pdf_to_map
    from models import ShareLink
    from sqlalchemy.orm import sessionmaker
    client, db, _, _, project, _ = ctx
    lot = seed_lot(ctx)
    version = db.get(ProjectVersion, lot.project_version_id)
    path = tmp_path / 'map.html'
    path.write_text(pdf_to_map.build_html('', 100, 100, [
        {'nome': '01', 'quadra': 'A', 'pts': '0,0 10,0 10,10', 's': 0, 'index': 0}], project.name), encoding='utf-8')
    version.map_html_path = str(path)
    version.is_published = True
    project.status = 'published'
    link = ShareLink(project_id=project.id, token='availability-test-link', access_mode='token')
    db.add(link)
    db.commit()
    headers = bearer(mint(ctx, ['units:write']))
    root = PREFIX + '/projects/' + project.id
    unit = client.post(root + '/units/bind', headers=headers, json={
        'external_system': 'colmeia', 'external_unit_id': 'U', 'lot_id': lot.id}).json()['unit']
    client.patch(root + '/units/' + unit['id'] + '/availability', headers=headers,
        json={'status': 'blocked', 'expected_revision': 0, 'event_id': 'b1', 'source': 'colmeia'})
    api.app.dependency_overrides[api.get_db] = lambda: db
    try:
        from fastapi.testclient import TestClient
        with TestClient(api.app) as public:
            response = public.get('/s/availability-test-link')
        assert response.status_code == 200
        assert '"s":3' in response.text and 'Bloqueado' in response.text
        assert 'id="shared-viewer"' in response.text
        assert '"s":3' not in path.read_text(encoding='utf-8')
    finally:
        api.app.dependency_overrides.pop(api.get_db, None)


def test_download_html_uses_live_status(ctx):
    from test_integrations_api import seed_job
    from app_v1.storage import storage_path
    import pdf_to_map
    client, db, _, _, project, _ = ctx
    lot = seed_lot(ctx)
    version = db.get(ProjectVersion, lot.project_version_id)
    path = storage_path('projects/' + project.id + '/map.html')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pdf_to_map.build_html('', 100, 100, [
        {'nome': '01', 'quadra': 'A', 'pts': '0,0 10,0 10,10', 's': 0, 'index': 0}]), encoding='utf-8')
    version.map_html_path = str(path)
    job = seed_job(ctx, status='succeeded')
    job.project_version_id = version.id
    db.commit()
    headers = bearer(mint(ctx, ['units:write', 'results:read']))
    root = PREFIX + '/projects/' + project.id
    unit = client.post(root + '/units/bind', headers=headers, json={
        'external_system': 'colmeia', 'external_unit_id': 'U', 'lot_id': lot.id}).json()['unit']
    client.patch(root + '/units/' + unit['id'] + '/availability', headers=headers,
        json={'status': 'sold', 'expected_revision': 0, 'event_id': 's1', 'source': 'colmeia'})
    response = client.get(PREFIX + '/jobs/' + job.id + '/results/html', headers=headers)
    assert response.status_code == 200 and '"s":1' in response.text
    assert 'attachment' in response.headers['content-disposition']


def test_batch_status_changes_emit_events_atomically(ctx):
    from auth import COOKIE_NAME
    from models import IntegrationEvent
    client, db, _, _, project, _ = ctx
    first = seed_lot(ctx)
    second = seed_lot(ctx, name='02')
    client.cookies.set(COOKIE_NAME, 'test-cookie')
    response = client.patch('/api/v1/lots/batch', json={'lot_ids': [first.id, second.id], 'changes': {'status': 'sold'}})
    assert response.status_code == 200, response.text
    db.refresh(first)
    db.refresh(second)
    assert first.status == second.status == 'sold'
    assert db.query(IntegrationEvent).count() == 2


def test_unit_migration_preserves_legacy_sold_and_flags_uncertain_demo_status(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text, inspect
    path = tmp_path / 'unit-migration.db'
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(path))
    config = Config()
    config.set_main_option('script_location', 'alembic')
    command.upgrade(config, '20261005_0004')
    engine = create_engine('sqlite:///' + str(path))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id,name,slug,active,created_at) VALUES ('o','O','unit-migration',1,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO projects (id,organization_id,name,slug,status,access_mode,client_can_edit,created_at,updated_at) VALUES ('p','o','P','unit-migration','draft','private',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO project_versions (id,project_id,map_html_path,lot_count,quality,status,is_published,created_at) VALUES ('v','p','unused',1,'balanced','draft',0,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO lots (id,project_id,project_version_id,external_id,name,block,status,geometry_json,sort_order,created_at,updated_at) VALUES ('l','p','v','0','01','A','sold','{}',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    command.upgrade(config, '20261005_0005')
    with engine.connect() as conn:
        row = conn.execute(text('SELECT status,mapping_state,lot_id,revision FROM integration_units')).one()
        assert tuple(row) == ('sold', 'needs_reconciliation', 'l', 0)
        assert conn.execute(text('SELECT status FROM lots')).scalar() == 'sold'
    assert 'integration_events' in inspect(engine).get_table_names()
    command.downgrade(config, '20261005_0004')
    assert 'integration_units' not in inspect(engine).get_table_names()
    engine.dispose()


def test_legacy_editor_save_syncs_bound_unit_and_rejects_stale_reopening(ctx, tmp_path, monkeypatch):
    import api
    import pdf_to_map
    from auth import COOKIE_NAME
    from fastapi.testclient import TestClient
    from models import IntegrationUnit, IntegrationEvent
    from app_v1.availability import bind
    _, db, _, _, project, _ = ctx
    lot = seed_lot(ctx)
    unit = bind(db, project, 'colmeia', 'U', lot.id)
    db.commit()
    items = [{'nome': '01', 'quadra': 'A', 'pts': '0,0 10,0 10,10', 's': 1, 'index': 0}]
    html = pdf_to_map.build_html('', 100, 100, items)
    monkeypatch.setattr(api, 'DATA_DIR', str(tmp_path))
    api.app.dependency_overrides[api.get_db] = lambda: db
    try:
        with TestClient(api.app) as client:
            client.cookies.set(COOKIE_NAME, 'test-cookie')
            payload = {'html': html, 'lot_count': 1, 'base_version_id': lot.project_version_id,
                       'expected_revisions': {unit.id: 0}}
            saved = client.post('/api/projects/' + project.id + '/versions/html', json=payload)
            assert saved.status_code == 201, saved.text
            db.refresh(unit)
            assert unit.status == 'sold' and unit.revision == 1
            new_lot = db.query(Lot).filter_by(project_version_id=saved.json()['version']['id']).one()
            assert new_lot.status == 'sold'
            assert db.query(IntegrationEvent).count() == 1
            stale = payload | {'html': pdf_to_map.build_html('', 100, 100, [items[0] | {'s': 0}])}
            rejected = client.post('/api/projects/' + project.id + '/versions/html', json=stale)
            assert rejected.status_code == 409, rejected.text
            db.refresh(unit)
            assert unit.status == 'sold' and db.query(ProjectVersion).count() == 2
    finally:
        api.app.dependency_overrides.pop(api.get_db, None)


def test_editor_response_carries_explicit_base_and_revision_snapshot(ctx, tmp_path):
    import api
    import pdf_to_map
    from app_v1.availability import bind
    _, db, _, _, project, _ = ctx
    lot = seed_lot(ctx, status='sold')
    unit = bind(db, project, 'colmeia', 'U', lot.id)
    db.commit()
    version = db.get(ProjectVersion, lot.project_version_id)
    path = tmp_path / 'editor.html'
    path.write_text(pdf_to_map.build_html('', 100, 100, [{'index': 0, 's': 0, 'nome': '01', 'quadra': 'A'}]), encoding='utf-8')
    version.map_html_path = str(path)
    db.commit()
    response = api.project_editor_response(project, version, db=db)
    html = response.body.decode()
    assert 'base_version_id' in html and version.id in html
    assert 'expected_revisions' in html and unit.id in html
    assert '"s":1' in html


def test_optimistic_revision_is_atomic_across_concurrent_sessions(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import Organization, Project, IntegrationUnit, IntegrationEvent
    from app_v1.availability import change
    engine = create_engine('sqlite:///' + str(tmp_path / 'concurrency.db'), connect_args={'timeout': 20})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        org = Organization(name='Concurrency', slug='concurrency')
        db.add(org)
        db.flush()
        project = Project(organization_id=org.id, name='Concurrency', slug='concurrency')
        db.add(project)
        db.flush()
        unit = IntegrationUnit(organization_id=org.id, project_id=project.id, status='available')
        db.add(unit)
        db.commit()
        project_id, unit_id = project.id, unit.id
    def writer(index):
        with factory() as db:
            try:
                result = change(db, db.get(Project, project_id), unit_id, 'sold', 0, 'event-' + str(index), 'colmeia')
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(writer, range(12)))
    assert results.count(200) == 1 and results.count(409) == 11, results
    with factory() as db:
        assert db.get(IntegrationUnit, unit_id).revision == 1
        assert db.query(IntegrationEvent).count() == 1
    engine.dispose()


def test_binding_rejects_two_lots_in_one_version_without_partial_reference(ctx):
    from models import IntegrationUnit, IntegrationUnitLot
    client, db, _, _, project, _ = ctx
    first = seed_lot(ctx)
    second = Lot(project_id=project.id, project_version_id=first.project_version_id,
                 external_id='1', name='02', block='A', geometry_json='{}')
    db.add(second)
    db.commit()
    headers = bearer(mint(ctx, ['units:write']))
    root = PREFIX + '/projects/' + project.id + '/units/bind'
    body = {'external_system': 'colmeia', 'external_unit_id': 'U', 'lot_id': first.id}
    assert client.post(root, headers=headers, json=body).status_code == 200
    assert client.post(root, headers=headers, json=body | {'lot_id': second.id}).status_code == 409
    assert db.query(IntegrationUnit).count() == db.query(IntegrationUnitLot).count() == 1
    db.refresh(second)
    assert second.status == 'available'


def test_explicit_binding_reconciles_provisional_unknown_without_reopening_sale(ctx):
    from app_v1.availability import bind, reconcile_version
    from models import IntegrationUnit
    client, db, _, _, project, _ = ctx
    first = seed_lot(ctx, status='sold')
    unit = bind(db, project, 'colmeia', 'U', first.id)
    db.commit()
    unknown = seed_lot(ctx, name=None, block=None)
    reconcile_version(db, project, unknown.project_version_id, converted=True)
    db.commit()
    headers = bearer(mint(ctx, ['units:write']))
    response = client.post(PREFIX + '/projects/' + project.id + '/units/bind', headers=headers,
        json={'external_system': 'colmeia', 'external_unit_id': 'U', 'lot_id': unknown.id})
    assert response.status_code == 200, response.text
    assert response.json()['unit']['id'] == unit.id
    db.refresh(unknown)
    assert unknown.status == 'sold'
    assert db.query(IntegrationUnit).count() == 1


def test_legacy_generate_persists_canonical_units(ctx, tmp_path, monkeypatch):
    import api
    from auth import COOKIE_NAME
    from fastapi.testclient import TestClient
    from test_integrations_api import pdf_bytes
    from models import IntegrationUnit
    _, db, _, _, project, _ = ctx
    monkeypatch.setattr(api, 'DATA_DIR', str(tmp_path))
    api.app.dependency_overrides[api.get_db] = lambda: db
    try:
        with TestClient(api.app) as client:
            client.cookies.set(COOKIE_NAME, 'test-cookie')
            response = client.post('/api/projects/' + project.id + '/generate',
                files={'arquivo': ('real.pdf', pdf_bytes(), 'application/pdf')})
        assert response.status_code == 201, response.text
        assert db.query(IntegrationUnit).filter_by(project_id=project.id).count() > 0
    finally:
        api.app.dependency_overrides.pop(api.get_db, None)


def test_failed_conversion_reconciliation_does_not_commit_partial_unit_state(ctx, monkeypatch):
    from app_v1 import worker, availability
    from sqlalchemy.orm import sessionmaker
    from test_integrations_api import pdf_bytes
    from models import IntegrationUnit
    client, db, _, _, project, _ = ctx
    monkeypatch.setattr(worker, 'SessionLocal', sessionmaker(bind=db.bind))
    monkeypatch.setenv('SYNC_PROCESSING', 'true')
    original = availability.reconcile_version
    def fail_after_reconcile(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('reconciliation interrupted')
    monkeypatch.setattr(availability, 'reconcile_version', fail_after_reconcile)
    headers = bearer(mint(ctx, ['jobs:write']))
    response = client.post(PREFIX + '/projects/' + project.id + '/jobs', headers=headers,
        files={'upload': ('real.pdf', pdf_bytes(), 'application/pdf')})
    assert response.status_code == 202 and response.json()['job']['status'] == 'failed'
    db.expire_all()
    assert db.query(IntegrationUnit).count() == db.query(Lot).count() == 0


def test_discovered_unit_can_bind_external_reference_without_reusing_identity(ctx):
    from app_v1.availability import reconcile_version
    client, db, _, _, project, _ = ctx
    lot = seed_lot(ctx)
    reconcile_version(db, project, lot.project_version_id)
    db.commit()
    headers = bearer(mint(ctx, ['units:read', 'units:write']))
    root = PREFIX + '/projects/' + project.id + '/units'
    unit = client.get(root, headers=headers).json()['units'][0]
    response = client.put(root + '/' + unit['id'] + '/external-reference', headers=headers,
        json={'external_system': 'colmeia', 'external_unit_id': 'U'})
    assert response.status_code == 200 and response.json()['unit']['external_unit_id'] == 'U'
    assert client.put(root + '/' + unit['id'] + '/external-reference', headers=headers,
        json={'external_system': 'colmeia', 'external_unit_id': 'OTHER'}).status_code == 409


def test_project_lock_prevents_out_of_order_event_commits(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import Organization, Project, IntegrationUnit, IntegrationEvent
    from app_v1.availability import change
    engine = create_engine('sqlite:///' + str(tmp_path / 'ordered.db'), connect_args={'timeout': 20})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        org = Organization(name='Order', slug='event-order')
        db.add(org)
        db.flush()
        project = Project(organization_id=org.id, name='Order', slug='event-order')
        db.add(project)
        db.flush()
        units = [IntegrationUnit(organization_id=org.id, project_id=project.id, status='available') for _ in range(2)]
        db.add_all(units)
        db.commit()
        project_id, ids = project.id, [unit.id for unit in units]
    first_allocated, release, second_started, second_allocated = Event(), Event(), Event(), Event()
    def first():
        with factory() as db:
            result = change(db, db.get(Project, project_id), ids[0], 'sold', 0, 'first', 'editor')
            first_allocated.set()
            assert release.wait(10)
            db.commit()
            return result['event']['id']
    def second():
        assert first_allocated.wait(10)
        with factory() as db:
            second_started.set()
            result = change(db, db.get(Project, project_id), ids[1], 'reserved', 0, 'second', 'colmeia')
            second_allocated.set()
            db.commit()
            return result['event']['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(first), pool.submit(second)
        assert second_started.wait(10)
        try:
            assert not second_allocated.wait(.2), 'Allocated a later event before the earlier event committed.'
        finally:
            release.set()
        assert a.result() < b.result()
    with factory() as db:
        assert db.query(IntegrationEvent).count() == 2
    engine.dispose()


def test_internal_html_download_uses_live_lot_status(ctx):
    from auth import COOKIE_NAME
    from models import FileAsset
    from app_v1.storage import storage_path
    import pdf_to_map
    client, db, _, org, project, _ = ctx
    lot = seed_lot(ctx, status='sold')
    version = db.get(ProjectVersion, lot.project_version_id)
    key = 'projects/' + project.id + '/map.html'
    path = storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pdf_to_map.build_html('', 100, 100, [{'index': 0, 's': 0, 'nome': '01', 'quadra': 'A'}]), encoding='utf-8')
    version.map_html_path = str(path)
    asset = FileAsset(organization_id=org.id, project_id=project.id, project_version_id=version.id,
                      kind='map_html', storage_key=key, content_type='text/html', original_name='map.html')
    db.add(asset)
    db.commit()
    client.cookies.set(COOKIE_NAME, 'test-cookie')
    response = client.get('/api/v1/files/' + asset.id)
    assert response.status_code == 200 and '"s":1' in response.text
