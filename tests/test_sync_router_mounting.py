"""Production app must mount both authentication boundaries and document only external routes."""
from fastapi.testclient import TestClient


def test_external_schema_contains_availability_and_webhooks():
    import api
    with TestClient(api.app) as client:
        result = client.get('/api/integrations/v1/openapi.json')
    assert result.status_code == 200
    paths = result.json()['paths']
    assert '/api/integrations/v1/projects/{project_id}/units' in paths
    assert '/api/integrations/v1/projects/{project_id}/webhooks' in paths
    assert all(path.startswith('/api/integrations/v1/') for path in paths)
    assert paths['/api/integrations/v1/projects/{project_id}/webhooks']['post']['security'] == [{'IntegrationBearer': []}]


def test_production_app_mounts_cookie_only_webhook_management():
    import api
    paths = api.app.openapi()['paths']
    assert '/api/v1/projects/{project_id}/integration-webhooks' in paths
    assert '/api/v1/integration-webhooks/{webhook_id}/deliveries' in paths


def test_all_webhook_models_are_registered_before_metadata_creation():
    import api
    from database import Base
    assert 'integration_webhooks' in Base.metadata.tables
    assert 'integration_webhook_deliveries' in Base.metadata.tables
