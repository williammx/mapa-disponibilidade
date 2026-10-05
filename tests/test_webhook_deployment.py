"""Keep webhook delivery running independently from PDF conversions."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class WebhookDeploymentTests(unittest.TestCase):
    def test_app_and_dispatcher_share_private_persistent_signing_key(self):
        import yaml
        services = yaml.safe_load((ROOT / 'compose.yaml').read_text(encoding='utf-8'))['services']
        for name in ('mapa-disponibilidade', 'webhook-dispatcher'):
            self.assertEqual(services[name]['environment'].get('WEBHOOK_MASTER_KEY_FILE'),
                             '/data/private/webhook-master.key')
            self.assertIn('mapa_project_data:/data', services[name]['volumes'])

    def test_release_checks_dispatcher_before_claiming_success(self):
        release = (ROOT / 'deploy' / 'remote-release.sh').read_text(encoding='utf-8')
        self.assertIn('mapa-webhook-dispatcher', release)

    def test_dispatcher_is_a_bounded_persistent_service_after_app_migrations(self):
        compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        match = re.search(r'^  webhook-dispatcher:\n(.*?)(?=^  [\w-]+:|^volumes:)', compose, re.M | re.S)
        self.assertIsNotNone(match, 'Missing persistent webhook dispatcher service')
        block = match.group(1)
        self.assertIn('app_v1.webhook_dispatch', block)
        self.assertIn('restart: unless-stopped', block)
        self.assertIn('mapa_project_data:/data', block)
        self.assertIn('PRIVATE_STORAGE_DIR: /data/storage', block)
        self.assertIn('service_healthy', block)
        self.assertIn('service_completed_successfully', block)
        self.assertIn('memory:', block)
        self.assertIn('cpus:', block)
        self.assertNotIn('user: "0:0"', block)
        self.assertNotIn('ports:', block)

if __name__ == '__main__':
    unittest.main()
