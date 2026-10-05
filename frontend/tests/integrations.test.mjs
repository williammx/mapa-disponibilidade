import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:5175';
const metadata = { id: 'key-1', name: 'CRM', organization_id: 'org-1', project_id: null, scopes: ['jobs:read'], created_at: '2026-10-01T12:00:00Z', expires_at: '2099-10-01T12:00:00Z', revoked_at: null };

async function setup(role = 'platform_admin') {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.TEST_CHROMIUM_EXECUTABLE || undefined });
  const context = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  const calls = [];
  let keys = [{ ...metadata }];
  let failCreate = false;
  let failRevoke = false;
  let webhooks = [];
  let deliveries = [{ id: 'delivery-1', event_id: 'event-1', status: 'failed', attempts: 3, next_attempt_at: null, last_http_status: 503, last_error: 'Destino indisponivel' }];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push({ path: url.pathname, method: request.method(), body: request.postDataJSON(), authorization: request.headers().authorization });
    let body = {};
    let status = 200;
    if (url.pathname === '/api/auth/me') body = { user: { name: 'Admin', platform_role: role } };
    else if (url.pathname === '/api/v1/organizations') body = { organizations: [{ id: 'org-1', name: 'Horizonte', active: true }, { id: 'org-2', name: 'Outra organizacao', active: true }] };
    else if (url.pathname.startsWith('/api/v1/organizations/')) body = { projects: url.pathname.endsWith('org-1') ? [{ id: 'project-1', name: 'Residencial Horizonte' }, { id: 'project-2', name: 'Segundo projeto' }] : [{ id: 'project-3', name: 'Outro projeto' }] };
    else if (/^\/api\/v1\/projects\/[^/]+\/integration-webhooks$/.test(url.pathname)) {
      const projectId = url.pathname.split('/')[4];
      if (request.method() === 'GET') body = { webhooks: webhooks.filter(hook => hook.project_id === projectId) };
      else if (request.method() === 'POST') {
        if (failCreate) { status = 422; body = { detail: 'Destino invalido' }; }
        else { const webhook = { id: 'webhook-1', project_id: projectId, ...request.postDataJSON(), active: true, created_at: '2026-10-05T12:00:00Z' }; webhooks.push(webhook); status = 201; body = { webhook, secret: 'whsec_once_only' }; }
      }
    }
    else if (/^\/api\/v1\/integration-webhooks\/[^/]+\/deliveries\/[^/]+\/retry$/.test(url.pathname) && request.method() === 'POST') {
      if (failRevoke) { status = 503; body = { detail: 'Reenvio indisponivel' }; }
      else { deliveries = deliveries.map(delivery => ({ ...delivery, status: 'pending', next_attempt_at: '2026-10-05T12:01:00Z' })); body = { delivery: deliveries[0] }; }
    }
    else if (/^\/api\/v1\/integration-webhooks\/[^/]+\/deliveries$/.test(url.pathname) && request.method() === 'GET') body = { deliveries, total: deliveries.length, next_offset: null };
    else if (/^\/api\/v1\/integration-webhooks\/[^/]+$/.test(url.pathname) && request.method() === 'DELETE') {
      if (failRevoke) { status = 500; body = { detail: 'Falha ao desativar' }; }
      else { webhooks = webhooks.map(hook => ({ ...hook, active: false })); status = 204; }
    }
    else if (url.pathname === '/api/v1/integration-api-keys' && request.method() === 'GET') body = { api_keys: url.searchParams.get('organization_id') === 'org-1' ? keys : [] };
    else if (url.pathname === '/api/v1/integration-api-keys' && request.method() === 'POST') {
      if (failCreate) { status = 422; body = { detail: 'Nome invalido' }; }
      else { const data = request.postDataJSON(); const key = { ...metadata, ...data, id: 'key-2' }; keys = [...keys, key]; status = 201; body = { key: 'nlk_test_secret_shown_once', api_key: key }; }
    } else if (/^\/api\/v1\/integration-api-keys\/[^/]+$/.test(url.pathname) && request.method() === 'DELETE') {
      if (failRevoke) { status = 500; body = { detail: 'Falha ao revogar' }; }
      else { keys = keys.map(key => key.id === url.pathname.split('/').at(-1) ? { ...key, revoked_at: '2026-10-05T12:00:00Z' } : key); status = 204; }
    }
    await route.fulfill({ status, contentType: 'application/json', body: status === 204 ? '' : JSON.stringify(body) });
  });
  await page.goto(`${baseURL}/app/integracoes`);
  return { browser, page, calls, failCreation: () => { failCreate = true; }, failRevocation: () => { failRevoke = true; } };
}

test('admin can create a scoped project key, copy it once, dismiss it, and confirm revocation', async () => {
  const { browser, page, calls } = await setup();
  try {
    await page.getByRole('heading', { name: 'Integracoes', exact: true }).waitFor();
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-1');
    await page.getByText('CRM', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Nova chave' }).click();
    await page.getByLabel('Nome da chave').fill('ERP');
    await page.getByLabel('Projeto (opcional)').selectOption('project-1');
    await page.getByLabel('jobs:write', { exact: false }).check();
    await page.getByLabel('publications:write', { exact: false }).check();
    for (const scope of ['units:read', 'units:write', 'events:read', 'webhooks:write']) await page.getByLabel(scope, { exact: false }).check();
    await page.getByRole('button', { name: 'Criar chave', exact: true }).click();
    const secret = page.getByRole('dialog', { name: 'Copie sua chave agora' });
    await secret.waitFor();
    const payload = calls.find(call => call.method === 'POST').body;
    assert.equal(payload.organization_id, 'org-1');
    assert.equal(payload.project_id, 'project-1');
    assert.ok(payload.scopes.includes('jobs:write'));
    await secret.getByRole('button', { name: 'Copiar chave' }).click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'nlk_test_secret_shown_once');
    assert.equal(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage)), '{}{}');
    await secret.getByRole('button', { name: 'Ja salvei a chave' }).click();
    assert.equal(await page.getByText('nlk_test_secret_shown_once', { exact: true }).count(), 0);
    await page.getByRole('button', { name: 'Revogar CRM' }).click();
    assert.equal(calls.filter(call => call.method === 'DELETE').length, 0);
    await page.getByRole('alertdialog').getByRole('button', { name: 'Revogar chave', exact: true }).click();
    await page.getByText('Revogada', { exact: true }).waitFor();
    assert.equal(calls.filter(call => call.method === 'DELETE').length, 1);
    assert.ok(await page.getByRole('link', { name: 'Documentacao OpenAPI' }).getAttribute('href'));
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({ path: 'integrations-mobile.png', fullPage: true });
  } finally { await browser.close(); }
});

test('admin manages project-scoped outgoing webhooks with one-time secrets and delivery retry', async () => {
  const { browser, page, calls } = await setup();
  try {
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-1');
    await page.getByLabel('Projeto dos webhooks', { exact: true }).selectOption('project-1');
    await page.getByText('Nenhum webhook cadastrado', { exact: true }).waitFor();
    await page.getByLabel('URL de destino HTTPS').fill('https://crm.example.com/events');
    await page.getByRole('button', { name: 'Criar webhook', exact: true }).click();
    const secret = page.getByRole('dialog', { name: 'Copie o segredo do webhook agora' });
    await secret.waitFor();
    const created = calls.find(call => call.path.endsWith('/integration-webhooks') && call.method === 'POST');
    assert.equal(created.path, '/api/v1/projects/project-1/integration-webhooks');
    assert.deepEqual(created.body, { url: 'https://crm.example.com/events', event_types: ['unit.availability.changed'] });
    assert.equal(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage)), '{}{}');
    await secret.getByRole('button', { name: 'Copiar segredo' }).click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'whsec_once_only');
    await secret.getByRole('status').filter({ hasText: 'Segredo copiado.' }).waitFor();
    await secret.getByRole('button', { name: 'Ja salvei o segredo' }).click();
    assert.equal(await page.getByText('whsec_once_only', { exact: true }).count(), 0);
    await page.getByRole('button', { name: 'Ver entregas' }).click();
    await page.getByText('Destino indisponivel', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Reenviar entrega delivery-1' }).click();
    await page.getByText('pending', { exact: true }).waitFor();
    await page.screenshot({ path: 'integrations-webhooks-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: 'integrations-webhooks-mobile.png', fullPage: true });
    assert.ok(calls.some(call => call.path === '/api/v1/integration-webhooks/webhook-1/deliveries/delivery-1/retry' && call.method === 'POST'));
    await page.getByRole('button', { name: 'Desativar webhook' }).click();
    assert.equal(calls.filter(call => call.path.includes('integration-webhooks') && call.method === 'DELETE').length, 0);
    await page.getByRole('alertdialog').getByRole('button', { name: 'Desativar webhook', exact: true }).click();
    await page.getByText('Desativado', { exact: true }).waitFor();
    await page.getByLabel('Projeto dos webhooks', { exact: true }).selectOption('project-2');
    await page.getByText('Nenhum webhook cadastrado', { exact: true }).waitFor();
    assert.equal(await page.getByText('Destino indisponivel', { exact: true }).count(), 0);
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-2');
    assert.equal(await page.getByLabel('Projeto dos webhooks', { exact: true }).inputValue(), '');
    assert.equal(calls.filter(call => call.path.startsWith('/api/integrations/')).length, 0);
    assert.ok(calls.every(call => !call.authorization));
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  } finally { await browser.close(); }
});

test('webhook validation and server failures stay visible; deliveries paginate without crossing projects', async () => {
  const fixture = await setup();
  const { browser, page, calls } = fixture;
  try {
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-1');
    await page.getByLabel('Projeto dos webhooks', { exact: true }).selectOption('project-1');
    await page.getByLabel('URL de destino HTTPS').fill('http://crm.example.com/events');
    await page.getByRole('button', { name: 'Criar webhook', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'URL HTTPS sem credenciais' }).waitFor();
    assert.equal(calls.filter(call => call.path.includes('integration-webhooks') && call.method === 'POST').length, 0);
    fixture.failCreation();
    await page.getByLabel('URL de destino HTTPS').fill('https://crm.example.com/events');
    await page.getByRole('button', { name: 'Criar webhook', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Destino invalido' }).waitFor();
    await page.route('**/api/v1/projects/project-1/integration-webhooks', async route => {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ webhooks: [{ id: 'webhook-1', project_id: 'project-1', url: 'https://crm.example.com/events', event_types: ['unit.availability.changed'], active: true, created_at: '2026-10-05T12:00:00Z' }] }) });
    });
    await page.getByLabel('Projeto dos webhooks', { exact: true }).selectOption('project-2');
    await page.getByLabel('Projeto dos webhooks', { exact: true }).selectOption('project-1');
    await page.getByRole('button', { name: 'Ver entregas' }).click();
    await page.getByText('Destino indisponivel', { exact: true }).waitFor();
    fixture.failRevocation();
    await page.getByRole('button', { name: 'Reenviar entrega delivery-1' }).click();
    await page.getByRole('alert').filter({ hasText: 'Reenvio indisponivel' }).waitFor();
    await page.getByRole('button', { name: 'Desativar webhook', exact: true }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Desativar webhook', exact: true }).click();
    await page.getByRole('alertdialog').getByRole('alert').filter({ hasText: 'Falha ao desativar' }).waitFor();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Cancelar' }).click();
    let failList = true;
    const offsets = [];
    await page.route('**/api/v1/integration-webhooks/webhook-1/deliveries?**', async route => {
      const offset = new URL(route.request().url()).searchParams.get('offset'); offsets.push(offset);
      const delivery = { id: offset === '20' ? 'delivery-21' : 'delivery-1', event_id: 'event-page', status: 'delivered', attempts: 1, next_attempt_at: null, last_http_status: null, last_error: null };
      await route.fulfill({ status: failList ? 503 : 200, contentType: 'application/json', body: JSON.stringify(failList ? { detail: 'Entregas indisponiveis' } : { deliveries: [delivery], total: 21, next_offset: offset === '20' ? null : 20 }) });
    });
    await page.getByRole('button', { name: 'Atualizar entregas' }).click();
    await page.getByRole('alert').filter({ hasText: 'Entregas indisponiveis' }).waitFor();
    failList = false;
    await page.getByRole('button', { name: 'Tentar de novo' }).click();
    await page.getByText('Sem resposta', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Reenviar entrega delivery-1' }).isDisabled(), true);
    await page.getByRole('button', { name: 'Proximas entregas' }).click();
    await page.getByText('delivery-21', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Proximas entregas' }).isDisabled(), true);
    await page.getByRole('button', { name: 'Entregas anteriores' }).click();
    await page.getByText('delivery-1', { exact: true }).waitFor();
    assert.ok(offsets.includes('20'));
  } finally { await browser.close(); }
});

test('non-internal users cannot access keys or the integrations navigation', async () => {
  const { browser, page, calls } = await setup('client_admin');
  try {
    await page.getByRole('heading', { name: 'Acesso negado' }).waitFor();
    assert.equal(await page.getByRole('link', { name: 'Integracoes', exact: true }).count(), 0);
    assert.equal(calls.filter(call => call.path.includes('integration-api-keys') || call.path.includes('integration-webhooks')).length, 0);
  } finally { await browser.close(); }
});

test('operators cannot access administrative key management', async () => {
  const { browser, page, calls } = await setup('operator');
  try {
    await page.getByRole('heading', { name: 'Acesso negado' }).waitFor();
    assert.equal(await page.getByRole('link', { name: 'Integracoes', exact: true }).count(), 0);
    assert.equal(calls.filter(call => call.path.includes('integration-api-keys') || call.path.includes('integration-webhooks')).length, 0);
  } finally { await browser.close(); }
});

test('creation and revoke errors remain visible; changing organization clears project restrictions', async () => {
  const fixture = await setup();
  const { browser, page } = fixture;
  try {
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-1');
    await page.getByRole('button', { name: 'Nova chave' }).click();
    await page.getByLabel('Nome da chave').fill('ERP');
    fixture.failCreation();
    await page.getByRole('button', { name: 'Criar chave', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Nome invalido' }).waitFor();
    await page.getByRole('button', { name: 'Cancelar criacao' }).click();
    fixture.failRevocation();
    await page.getByRole('button', { name: 'Revogar CRM' }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Revogar chave', exact: true }).click();
    await page.getByRole('alertdialog').getByRole('alert').filter({ hasText: 'Falha ao revogar' }).waitFor();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Cancelar' }).click();
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-2');
    await page.getByText('Nenhuma chave cadastrada').waitFor();
    await page.getByRole('button', { name: 'Nova chave' }).click();
    assert.equal(await page.getByLabel('Projeto (opcional)').inputValue(), '');
  } finally { await browser.close(); }
});

test('expiry metadata is displayed and list failures can be retried', async () => {
  const { browser, page } = await setup();
  let fail = true;
  try {
    await page.route('**/api/v1/integration-api-keys?**', async route => {
      await route.fulfill({ status: fail ? 503 : 200, contentType: 'application/json', body: JSON.stringify(fail ? { detail: 'Lista indisponivel' } : { api_keys: [{ ...metadata, expires_at: '2020-01-01T00:00:00' }] }) });
    });
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-1');
    await page.getByRole('alert').filter({ hasText: 'Lista indisponivel' }).waitFor();
    fail = false;
    await page.getByRole('button', { name: 'Tentar de novo' }).click();
    await page.getByText('Expirada', { exact: true }).waitFor();
    await page.getByText('Expira em', { exact: true }).waitFor();
  } finally { await browser.close(); }
});

test('clipboard errors allow manual copying and Escape discards the one-time secret', async () => {
  const { browser, page, calls } = await setup();
  try {
    await page.getByLabel('Organizacao', { exact: true }).selectOption('org-1');
    await page.getByRole('button', { name: 'Nova chave' }).click();
    await page.getByLabel('Nome da chave').fill('ERP');
    await page.getByLabel('capabilities:read', { exact: false }).uncheck();
    assert.equal(await page.getByRole('button', { name: 'Criar chave', exact: true }).isDisabled(), true);
    await page.getByLabel('results:read', { exact: false }).check();
    await page.getByLabel('Expiracao (opcional)', { exact: false }).fill(new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 16));
    await page.getByRole('button', { name: 'Criar chave', exact: true }).click();
    const secret = page.getByRole('dialog', { name: 'Copie sua chave agora' });
    await secret.waitFor();
    const payload = calls.find(call => call.method === 'POST').body;
    assert.equal(payload.project_id, null);
    assert.ok(payload.expires_at.endsWith('Z'));
    assert.deepEqual(payload.scopes, ['results:read']);
    await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw new Error('Permission denied'); }; });
    await secret.getByRole('button', { name: 'Copiar chave' }).click();
    await secret.getByRole('alert').filter({ hasText: 'copie manualmente' }).waitFor();
    await page.keyboard.press('Escape');
    await secret.waitFor({ state: 'detached' });
    assert.equal(await page.getByText('nlk_test_secret_shown_once', { exact: true }).count(), 0);
    await page.reload();
    assert.equal(await page.getByText('nlk_test_secret_shown_once', { exact: true }).count(), 0);
  } finally { await browser.close(); }
});
