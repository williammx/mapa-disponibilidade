"""Regressao: nenhum endpoint de senha tinha limite de tentativas.

Login, link de projeto (/s/{token}) e mapa do converter (/map/{token}) aceitavam
tentativas ilimitadas. Com senha de 6 digitos entregue por WhatsApp isso e
forca bruta em minutos. Estes testes trancam o comportamento novo: 8 falhas em
15 minutos por (identificador, IP) e a proxima responde 429 com Retry-After.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api
import rate_limit
from auth import hash_token, password_hash
from database import Base, get_db
from models import Organization, Project, ProjectVersion, ShareLink, User

SENHA_CERTA = "senha-longa-de-teste"
SENHA_ERRADA = "chute-do-atacante"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db, monkeypatch):
    # Sem REDIS_URL o limitador usa o contador em memoria do processo.
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("LOGIN_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("LOGIN_WINDOW_SECONDS", raising=False)
    rate_limit.reset()
    api.app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(api.app)
    finally:
        api.app.dependency_overrides.pop(get_db, None)
        rate_limit.reset()


def make_user(db, email: str) -> User:
    user = User(name="Cliente", email=email, password_hash=password_hash.hash(SENHA_CERTA))
    db.add(user)
    db.commit()
    return user


def make_share_link(db, slug: str = "mapa-protegido") -> ShareLink:
    organization = Organization(name="Cliente", slug=f"cliente-{slug}")
    db.add(organization)
    db.flush()
    project = Project(organization_id=organization.id, name="Mapa", slug=slug, status="published")
    db.add(project)
    db.flush()
    db.add(ProjectVersion(project_id=project.id, map_html_path="/tmp/map.html", lot_count=1, is_published=True))
    link = ShareLink(
        project_id=project.id,
        token=f"token-{slug}",
        token_hash=hash_token(f"token-{slug}"),
        password_hash=password_hash.hash(SENHA_CERTA),
    )
    db.add(link)
    db.commit()
    return link


def make_converter_job(tmp_path, monkeypatch, token: str) -> str:
    job_id = "b" * 32
    monkeypatch.setattr(api, "CONVERTER_JOB_DIR", str(tmp_path))
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "map.html").write_text("<html><body>mapa</body></html>", encoding="utf-8")
    (job_dir / "job.json").write_text(json.dumps({
        "id": job_id,
        "status": "completed",
        "published": True,
        "share_token": token,
        "password_hash": password_hash.hash(SENHA_CERTA),
        "allow_edit": False,
    }), encoding="utf-8")
    return job_id


def login_errado(client, email: str, ip: str | None = None):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": SENHA_ERRADA},
        headers=headers,
    )


def test_login_bloqueia_a_nona_tentativa_com_429_e_retry_after(client, db):
    make_user(db, "alvo@exemplo.com")
    for tentativa in range(8):
        resposta = login_errado(client, "alvo@exemplo.com")
        assert resposta.status_code == 401, f"tentativa {tentativa + 1}: {resposta.text}"

    bloqueada = login_errado(client, "alvo@exemplo.com")

    assert bloqueada.status_code == 429, bloqueada.text
    assert int(bloqueada.headers["Retry-After"]) > 0
    assert bloqueada.json()["detail"] == "Muitas tentativas. Tente novamente em 15 minutos."


def test_login_correto_zera_o_contador_de_falhas(client, db):
    make_user(db, "zera@exemplo.com")
    for _ in range(7):
        assert login_errado(client, "zera@exemplo.com").status_code == 401

    certo = client.post("/api/auth/login", json={"email": "zera@exemplo.com", "password": SENHA_CERTA})
    assert certo.status_code == 200, certo.text

    for tentativa in range(8):
        resposta = login_errado(client, "zera@exemplo.com")
        assert resposta.status_code == 401, f"tentativa {tentativa + 1} depois do acerto: {resposta.text}"


def test_contador_de_login_nao_e_compartilhado_entre_emails(client, db):
    make_user(db, "primeiro@exemplo.com")
    make_user(db, "segundo@exemplo.com")
    for _ in range(8):
        assert login_errado(client, "primeiro@exemplo.com").status_code == 401
    assert login_errado(client, "primeiro@exemplo.com").status_code == 429

    outro = login_errado(client, "segundo@exemplo.com")

    assert outro.status_code == 401, outro.text


def test_x_forwarded_for_separa_os_contadores_por_ip(client, db):
    make_user(db, "proxy@exemplo.com")
    for _ in range(8):
        assert login_errado(client, "proxy@exemplo.com", ip="203.0.113.10").status_code == 401
    assert login_errado(client, "proxy@exemplo.com", ip="203.0.113.10").status_code == 429

    outro_ip = login_errado(client, "proxy@exemplo.com", ip="198.51.100.20")

    assert outro_ip.status_code == 401, outro_ip.text


def test_link_compartilhado_bloqueia_a_nona_senha_errada(client, db):
    link = make_share_link(db)
    for tentativa in range(8):
        resposta = client.post(f"/s/{link.token}", data={"password": SENHA_ERRADA})
        assert resposta.status_code == 403, f"tentativa {tentativa + 1}: {resposta.text}"

    bloqueada = client.post(f"/s/{link.token}", data={"password": SENHA_ERRADA})

    assert bloqueada.status_code == 429, bloqueada.text
    assert int(bloqueada.headers["Retry-After"]) > 0
    assert bloqueada.json()["detail"] == "Muitas tentativas. Tente novamente em 15 minutos."


def test_contador_do_link_compartilhado_e_por_token(client, db):
    primeiro = make_share_link(db, "mapa-um")
    segundo = make_share_link(db, "mapa-dois")
    for _ in range(8):
        assert client.post(f"/s/{primeiro.token}", data={"password": SENHA_ERRADA}).status_code == 403
    assert client.post(f"/s/{primeiro.token}", data={"password": SENHA_ERRADA}).status_code == 429

    outro = client.post(f"/s/{segundo.token}", data={"password": SENHA_ERRADA})

    assert outro.status_code == 403, outro.text


def test_mapa_do_converter_bloqueia_a_nona_senha_errada(client, monkeypatch, tmp_path):
    token = "token-do-mapa-do-converter"
    make_converter_job(tmp_path, monkeypatch, token)
    for tentativa in range(8):
        resposta = client.post(f"/map/{token}", data={"password": SENHA_ERRADA})
        assert resposta.status_code == 200, f"tentativa {tentativa + 1}: {resposta.status_code}"
        assert "Senha incorreta." in resposta.text

    bloqueada = client.post(f"/map/{token}", data={"password": SENHA_ERRADA})

    assert bloqueada.status_code == 429
    assert int(bloqueada.headers["Retry-After"]) > 0
    assert "Muitas tentativas. Tente novamente em 15 minutos." in bloqueada.text


def test_limite_e_janela_saem_das_variaveis_de_ambiente(client, db, monkeypatch):
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("LOGIN_WINDOW_SECONDS", "120")
    make_user(db, "config@exemplo.com")
    for _ in range(2):
        assert login_errado(client, "config@exemplo.com").status_code == 401

    bloqueada = login_errado(client, "config@exemplo.com")

    assert bloqueada.status_code == 429, bloqueada.text
    assert 0 < int(bloqueada.headers["Retry-After"]) <= 120
    assert bloqueada.json()["detail"] == "Muitas tentativas. Tente novamente em 2 minutos."


def test_reset_zera_o_estado_do_limitador(client, db):
    make_user(db, "reset@exemplo.com")
    for _ in range(8):
        assert login_errado(client, "reset@exemplo.com").status_code == 401
    assert login_errado(client, "reset@exemplo.com").status_code == 429

    rate_limit.reset()

    assert login_errado(client, "reset@exemplo.com").status_code == 401


class FakeRedis:
    """Redis em memoria com os comandos de sorted set que o limitador usa.

    Nao existe redis-server no ambiente de teste, e o caminho com Redis e o que
    roda em producao — sem este duble ele ficaria sem cobertura nenhuma.
    """

    def __init__(self):
        self.sets: dict[str, dict[str, float]] = {}
        self.comandos: list[str] = []

    def pipeline(self):
        return FakePipeline(self)

    def zremrangebyscore(self, key, minimo, maximo):
        self.comandos.append("zremrangebyscore")
        membros = self.sets.get(key, {})
        sobrando = {membro: score for membro, score in membros.items() if not minimo <= score <= maximo}
        self.sets[key] = sobrando
        return len(membros) - len(sobrando)

    def zadd(self, key, mapping):
        self.comandos.append("zadd")
        alvo = self.sets.setdefault(key, {})
        novos = [membro for membro in mapping if membro not in alvo]
        alvo.update(mapping)
        return len(novos)

    def zrange(self, key, inicio, fim, withscores=False):
        self.comandos.append("zrange")
        itens = sorted(self.sets.get(key, {}).items(), key=lambda item: item[1])
        recorte = itens[inicio:] if fim == -1 else itens[inicio:fim + 1]
        return recorte if withscores else [membro for membro, _ in recorte]

    def expire(self, key, seconds):
        self.comandos.append("expire")
        return True

    def delete(self, *keys):
        for key in keys:
            self.sets.pop(key, None)
        return len(keys)

    def scan_iter(self, match="*"):
        prefixo = match.rstrip("*")
        return [key for key in list(self.sets) if key.startswith(prefixo)]


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.fila = []

    def __getattr__(self, nome):
        def enfileira(*args, **kwargs):
            self.fila.append((nome, args, kwargs))
            return self
        return enfileira

    def execute(self):
        resultados = [getattr(self.client, nome)(*args, **kwargs) for nome, args, kwargs in self.fila]
        self.fila = []
        return resultados


@pytest.fixture()
def fake_redis(monkeypatch):
    import redis as redis_pkg

    fake = FakeRedis()
    monkeypatch.setattr(redis_pkg.Redis, "from_url", classmethod(lambda cls, url, **kwargs: fake))
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    rate_limit.reset()
    return fake


def test_com_redis_url_o_contador_vive_no_redis(client, db, fake_redis):
    make_user(db, "redis@exemplo.com")
    for tentativa in range(8):
        resposta = login_errado(client, "redis@exemplo.com")
        assert resposta.status_code == 401, f"tentativa {tentativa + 1}: {resposta.text}"

    bloqueada = login_errado(client, "redis@exemplo.com")

    assert bloqueada.status_code == 429, bloqueada.text
    assert int(bloqueada.headers["Retry-After"]) > 0
    chave = next(chave for chave in fake_redis.sets if chave.startswith(rate_limit.KEY_PREFIX))
    assert len(fake_redis.sets[chave]) == 8
    assert {"zadd", "zrange", "zremrangebyscore", "expire"} <= set(fake_redis.comandos)


def test_acerto_apaga_a_chave_no_redis(client, db, fake_redis):
    make_user(db, "apaga@exemplo.com")
    for _ in range(3):
        assert login_errado(client, "apaga@exemplo.com").status_code == 401
    assert any(chave.startswith(rate_limit.KEY_PREFIX) for chave in fake_redis.sets)

    certo = client.post("/api/auth/login", json={"email": "apaga@exemplo.com", "password": SENHA_CERTA})

    assert certo.status_code == 200, certo.text
    assert not [chave for chave in fake_redis.sets if chave.startswith(rate_limit.KEY_PREFIX)]


def test_redis_fora_do_ar_nao_libera_forca_bruta(client, db, monkeypatch):
    import redis as redis_pkg

    class RedisMorto:
        def __getattr__(self, nome):
            def explode(*args, **kwargs):
                raise redis_pkg.RedisError("connection refused")
            return explode

    monkeypatch.setattr(redis_pkg.Redis, "from_url", classmethod(lambda cls, url, **kwargs: RedisMorto()))
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    rate_limit.reset()
    make_user(db, "queda@exemplo.com")
    for tentativa in range(8):
        resposta = login_errado(client, "queda@exemplo.com")
        assert resposta.status_code == 401, f"tentativa {tentativa + 1}: {resposta.text}"

    bloqueada = login_errado(client, "queda@exemplo.com")

    assert bloqueada.status_code == 429, bloqueada.text


def test_ultimo_ip_do_x_forwarded_for_e_o_usado_como_chave():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/auth/login",
        "raw_path": b"/api/auth/login",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"203.0.113.10, 10.0.0.7")],
        "client": ("127.0.0.1", 1234),
        "server": ("map.example.com", 443),
    }
    from fastapi import Request

    assert rate_limit.client_ip(Request(scope)) == "10.0.0.7"


def test_sem_x_forwarded_for_usa_o_ip_da_conexao():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/auth/login",
        "raw_path": b"/api/auth/login",
        "query_string": b"",
        "headers": [],
        "client": ("198.51.100.20", 1234),
        "server": ("map.example.com", 443),
    }
    from fastapi import Request

    assert rate_limit.client_ip(Request(scope)) == "198.51.100.20"


def test_x_forwarded_for_falsificado_nao_zera_o_limite():
    """O Nginx anexa o IP real ao fim do X-Forwarded-For.

    Se lessemos o PRIMEIRO elemento, bastaria mandar um valor aleatorio a cada
    requisicao para trocar de chave e nunca estourar o limite.
    """
    from starlette.datastructures import Headers

    class _Req:
        def __init__(self, headers):
            self.headers = Headers(headers)
            self.client = None

    forjado_1 = _Req({"x-forwarded-for": "1.1.1.1, 203.0.113.9"})
    forjado_2 = _Req({"x-forwarded-for": "2.2.2.2, 203.0.113.9"})
    assert rate_limit.client_ip(forjado_1) == rate_limit.client_ip(forjado_2) == "203.0.113.9"


def test_x_real_ip_tem_prioridade():
    from starlette.datastructures import Headers

    class _Req:
        def __init__(self, headers):
            self.headers = Headers(headers)
            self.client = None

    pedido = _Req({"x-real-ip": "203.0.113.9", "x-forwarded-for": "1.1.1.1, 9.9.9.9"})
    assert rate_limit.client_ip(pedido) == "203.0.113.9"
