"""Canonical unit identity, durable availability requests and event cursor."""
from collections import Counter
from datetime import datetime
import re
import uuid

from alembic import op
import sqlalchemy as sa

revision = '20261005_0005'
down_revision = '20261005_0004'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if 'integration_units' not in existing:
        op.create_table('integration_units',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('external_system', sa.String(120)), sa.Column('external_unit_id', sa.String(160)),
            sa.Column('block', sa.String(120)), sa.Column('name', sa.String(160)),
            sa.Column('status', sa.String(32), nullable=False),
            sa.Column('revision', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('mapping_state', sa.String(32), nullable=False),
            sa.Column('lot_id', sa.String(36), sa.ForeignKey('lots.id', ondelete='SET NULL'), unique=True),
            sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('project_id', 'external_system', 'external_unit_id', name='uq_unit_external'))
    if 'integration_unit_lots' not in existing:
        op.create_table('integration_unit_lots',
            sa.Column('lot_id', sa.String(36), sa.ForeignKey('lots.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('unit_id', sa.String(36), sa.ForeignKey('integration_units.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('project_version_id', sa.String(36), sa.ForeignKey('project_versions.id', ondelete='CASCADE'), nullable=False),
            sa.UniqueConstraint('unit_id', 'project_version_id', name='uq_unit_version'))
    if 'integration_events' not in existing:
        op.create_table('integration_events',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('organization_id', sa.String(36), nullable=False, index=True),
            sa.Column('project_id', sa.String(36), nullable=False, index=True),
            sa.Column('event_type', sa.String(80), nullable=False),
            sa.Column('payload_json', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False),
            sqlite_autoincrement=True)
    if 'integration_availability_requests' not in existing:
        op.create_table('integration_availability_requests',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
            sa.Column('external_system', sa.String(120), nullable=False), sa.Column('event_id', sa.String(160), nullable=False),
            sa.Column('request_hash', sa.String(64), nullable=False), sa.Column('outcome_json', sa.Text(), nullable=False),
            sa.UniqueConstraint('project_id', 'external_system', 'event_id', name='uq_availability_request'))
    if 'integration_units' not in existing:
        _backfill(bind)


def _backfill(bind):
    """Legacy converter statuses cannot be distinguished from real sales: preserve,
    flag for reconciliation, and never let a newer demo available reopen a sale.
    Frozen SQL/data contract, deliberately independent of live application models.
    """
    meta = sa.MetaData()
    units = sa.Table('integration_units', meta, autoload_with=bind)
    links = sa.Table('integration_unit_lots', meta, autoload_with=bind)
    lots_table = sa.Table('lots', meta, autoload_with=bind)
    rows = list(bind.execute(sa.text('SELECT l.*, p.organization_id, v.created_at AS version_created '
        'FROM lots l JOIN projects p ON p.id=l.project_id JOIN project_versions v '
        'ON v.id=l.project_version_id ORDER BY l.project_id,v.created_at,v.id,l.sort_order,l.id')).mappings())
    def label(row):
        block, name = (row['block'] or '').strip(), (row['name'] or '').strip()
        return (block, name) if block and name and not re.fullmatch(r'Lote\s+\d+', name, re.I) else None
    counts = Counter((row['project_version_id'], label(row)) for row in rows)
    groups = {}
    rank = {'available': 0, 'reserved': 1, 'blocked': 2, 'sold': 3}
    now = datetime.utcnow()
    for row in rows:
        identity = label(row)
        key = (row['project_id'], identity) if identity and counts[(row['project_version_id'], identity)] == 1 else (row['project_id'], row['id'])
        state = groups.get(key)
        status = row['status'] if row['status'] in rank else 'blocked'
        if state is None:
            state = {'id': str(uuid.uuid4()), 'organization_id': row['organization_id'], 'project_id': row['project_id'],
                     'external_system': None, 'external_unit_id': None, 'block': row['block'], 'name': row['name'],
                     'status': status, 'revision': 0, 'mapping_state': 'needs_reconciliation', 'lot_id': row['id'],
                     'created_at': now, 'updated_at': now}
            groups[key] = state
            bind.execute(units.insert().values(**state))
        else:
            status = max((status, state['status']), key=rank.get)
            state.update(status=status, lot_id=row['id'])
            bind.execute(units.update().where(units.c.id == state['id']).values(status=status, lot_id=row['id']))
        bind.execute(links.insert().values(lot_id=row['id'], unit_id=state['id'], project_version_id=row['project_version_id']))
    for state in groups.values():
        ids = sa.select(links.c.lot_id).where(links.c.unit_id == state['id'])
        bind.execute(lots_table.update().where(lots_table.c.id.in_(ids)).values(status=state['status']))


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ('integration_availability_requests', 'integration_events', 'integration_unit_lots', 'integration_units'):
        if table in existing:
            op.drop_table(table)
