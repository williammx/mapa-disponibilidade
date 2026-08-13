"""Regressao: arquivo de `frontend/public/` dava 404 em producao.

Existia uma rota codificada por arquivo (`/hero-loteamento-aereo.png`). Quando o
site novo passou a usar outra imagem, ela nunca foi servida — o site subiu com o
hero quebrado e o pipeline nao viu, porque so checa `/health`.
"""
import os

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture()
def dist(tmp_path, monkeypatch):
    pasta = tmp_path / "dist"
    pasta.mkdir()
    (pasta / "hero.webp").write_bytes(b"RIFF0000WEBPVP8 ")
    (pasta / "marca.svg").write_text("<svg/>")
    (pasta / "segredo.env").write_text("SENHA=123")
    (tmp_path / "fora.webp").write_bytes(b"nao deveria sair daqui")
    monkeypatch.setattr(api, "FRONTEND_DIST", str(pasta))
    return pasta


@pytest.fixture()
def client():
    return TestClient(api.app)


def test_imagem_da_pasta_public_e_servida(dist, client):
    resposta = client.get("/hero.webp")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/webp"


def test_svg_tambem_e_servido(dist, client):
    assert client.get("/marca.svg").status_code == 200


def test_extensao_fora_da_lista_nao_e_servida(dist, client):
    """Um .env dentro do dist nao pode virar download publico."""
    assert client.get("/segredo.env").status_code == 404


def test_arquivo_inexistente_da_404(dist, client):
    assert client.get("/nao-existe.webp").status_code == 404


@pytest.mark.parametrize("caminho", [
    "/../fora.webp",
    "/..%2ffora.webp",
    "/%2e%2e%2ffora.webp",
])
def test_nao_da_para_escapar_do_diretorio(dist, client, caminho):
    resposta = client.get(caminho)
    assert resposta.status_code == 404
    assert b"nao deveria sair daqui" not in resposta.content


def test_rotas_explicitas_continuam_ganhando(dist, client):
    """A rota curinga e a ultima registrada; /health nao pode ser engolida."""
    resposta = client.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_o_hero_do_site_existe_no_repositorio():
    """Sem isto, trocar o nome da imagem no React quebraria o site em silencio."""
    publico = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "frontend", "public")
    for esperado in ("hero-noturno-1600.webp", "hero-noturno-1000.webp"):
        assert os.path.isfile(os.path.join(publico, esperado)), (
            "%s e referenciada pelo site e precisa existir em frontend/public" % esperado)
