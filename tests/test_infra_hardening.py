"""Travas da infraestrutura que so quebrariam em producao.

Cada teste aqui existe por causa de uma falha que nao aparece em nenhum teste de
aplicacao: container sem limite de memoria derrubando o Postgres, imagem sem
privilegio esbarrando num volume de root, dependencia sem trava trocando o motor
de geometria sozinha no proximo deploy e restore que mente sobre ter dado certo.
"""
import os
import re
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
COMPOSE = RAIZ / "compose.yaml"
DOCKERFILE = RAIZ / "Dockerfile"
LOCK = RAIZ / "requirements.lock.txt"
RESTORE = RAIZ / "deploy" / "restore.sh"

# Servicos que rodam codigo nosso ou guardam estado: todos precisam de teto.
SERVICOS_COM_LIMITE = ("db", "redis", "mapa-disponibilidade", "worker")

# UID sem privilegio da imagem. Se mudar no Dockerfile, tem que mudar no
# compose.yaml junto, senao o volume fica ilegivel para a aplicacao.
APP_UID = "10001"


def carregar_compose():
    yaml = pytest.importorskip("yaml", reason="PyYAML nao e dependencia do projeto")
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def bytes_de(valor: str) -> int:
    """Converte '2g' / '1536m' / '384m' em bytes, como o Docker faz."""
    casado = re.fullmatch(r"(\d+)\s*([kmgb]?)b?", str(valor).strip().lower())
    assert casado, f"valor de memoria fora do formato do Docker: {valor!r}"
    fator = {"": 1, "b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
    return int(casado.group(1)) * fator[casado.group(2)]


# ---------------------------------------------------------------------------
# Limites de recurso
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("servico", SERVICOS_COM_LIMITE)
def test_todo_servico_de_aplicacao_tem_teto_de_memoria_e_cpu(servico):
    """Sem teto, um PDF grande consome a RAM do host e leva o banco junto."""
    compose = carregar_compose()
    limites = compose["services"][servico]["deploy"]["resources"]["limits"]

    assert bytes_de(limites["memory"]) > 0
    assert float(limites["cpus"]) > 0


def test_limites_usam_a_sintaxe_que_o_compose_up_aplica():
    """`deploy.resources.limits` vale no `docker compose up`; replicas e
    reservations de cpu seriam ignoradas fora do Swarm e dariam falsa seguranca."""
    compose = carregar_compose()
    for servico in SERVICOS_COM_LIMITE:
        deploy = compose["services"][servico]["deploy"]
        assert set(deploy) == {"resources"}, f"{servico}: chave de Swarm em deploy"
        assert set(deploy["resources"]) == {"limits"}, f"{servico}: reservations nao valem aqui"


def test_worker_tem_o_maior_teto_por_ser_quem_converte_o_pdf():
    compose = carregar_compose()

    def memoria(servico):
        return bytes_de(compose["services"][servico]["deploy"]["resources"]["limits"]["memory"])

    assert memoria("worker") == max(memoria(s) for s in SERVICOS_COM_LIMITE)
    # O banco e o que estamos protegendo: apertar ele trocaria o problema de
    # hoje por um OOM do Postgres.
    assert memoria("db") >= 512 * 1024 ** 2


# ---------------------------------------------------------------------------
# Container sem privilegio + volume que ja existe com arquivos de root
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason="USER desligado de proposito nesta entrega: o volume de producao ainda "
           "pertence ao root e so o mapa-storage-init desta mesma entrega conserta "
           "isso. Quando a proxima entrega descomentar o USER no Dockerfile, este "
           "teste passa e o strict acusa o XPASS — a hora de remover este marcador.",
)
def test_dockerfile_nao_roda_como_root():
    conteudo = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^USER\s+", conteudo, re.MULTILINE), "imagem ainda roda como root"
    assert f"APP_UID={APP_UID}" in conteudo


def test_storage_init_conserta_o_dono_do_volume_como_root():
    """O Docker so copia dono e permissao da imagem em volume VAZIO. O volume de
    producao ja tem arquivos de root, entao alguem precisa acertar o dono."""
    compose = carregar_compose()
    init = compose["services"]["mapa-storage-init"]

    assert str(init["user"]) == "0:0", "sem root o chown nao tem como funcionar"
    comando = " ".join(init["command"]) if isinstance(init["command"], list) else init["command"]
    assert f"chown -R {APP_UID}:{APP_UID} /data" in comando
    assert any(v.startswith("mapa_project_data:") for v in init["volumes"])


@pytest.mark.parametrize("servico", ("mapa-disponibilidade", "worker"))
def test_app_e_worker_so_sobem_depois_do_conserto_do_volume(servico):
    compose = carregar_compose()
    dependencia = compose["services"][servico]["depends_on"]["mapa-storage-init"]

    assert dependencia["condition"] == "service_completed_successfully"


def test_converter_job_dir_aponta_para_o_volume_e_nao_para_dentro_de_app():
    """O default do codigo e /app/data/converter_jobs, e /app pertence ao root.
    Sem sobrescrever, as rotas /converter e /converter/jobs morrem com
    PermissionError no primeiro upload depois que a imagem virou sem privilegio."""
    compose = carregar_compose()
    ambiente = compose["services"]["mapa-disponibilidade"]["environment"]

    assert ambiente["CONVERTER_JOB_DIR"].startswith("/data/")


def test_todo_diretorio_de_escrita_fica_sob_o_volume_montado():
    compose = carregar_compose()
    servicos = compose["services"]
    for nome in ("mapa-disponibilidade", "worker"):
        montagens = [v.split(":")[1] for v in servicos[nome]["volumes"]]
        assert "/data" in montagens
        for chave, valor in servicos[nome]["environment"].items():
            if chave.endswith("_DIR") or chave.endswith("_STORAGE_DIR"):
                assert str(valor).startswith("/data/"), f"{nome}.{chave} escreve fora do volume"


# ---------------------------------------------------------------------------
# Dependencias travadas
# ---------------------------------------------------------------------------
def versoes_do_lock() -> dict:
    versoes = {}
    for linha in LOCK.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        nome, _, versao = linha.partition("==")
        versoes[nome.strip().lower().replace("_", "-")] = versao.strip()
    return versoes


def test_dockerfile_instala_do_arquivo_travado():
    conteudo = DOCKERFILE.read_text(encoding="utf-8")
    assert "requirements.lock.txt" in conteudo
    assert not re.search(r"pip install[^\n]*-r requirements\.txt", conteudo), \
        "instalar dos pisos faz cada deploy re-resolver as versoes"


def test_lock_fixa_versao_exata_de_toda_linha():
    versoes = versoes_do_lock()
    assert versoes, "arquivo travado vazio"
    for nome, versao in versoes.items():
        assert re.fullmatch(r"[\w.\-+!]+", versao), f"{nome} sem versao exata"
    bruto = LOCK.read_text(encoding="utf-8")
    for linha in bruto.splitlines():
        if linha.strip() and not linha.startswith("#"):
            assert "==" in linha, f"linha sem trava: {linha!r}"
            assert ">=" not in linha, f"piso sobrou no lock: {linha!r}"


def test_lock_cobre_o_motor_de_geometria_e_a_pilha_da_api():
    """Estes sao os pacotes cuja troca silenciosa muda a precisao de area medida
    ou derruba o boot."""
    versoes = versoes_do_lock()
    for pacote in ("pymupdf", "shapely", "opencv-python-headless", "numpy", "pillow",
                   "fastapi", "uvicorn", "sqlalchemy", "psycopg", "alembic", "redis", "rq"):
        assert pacote in versoes, f"{pacote} ficou sem trava"


def test_requirements_continua_legivel_como_declaracao_de_intencao():
    conteudo = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
    assert "pymupdf" in conteudo
    assert "requirements.lock.txt" in conteudo, "sem apontar para o lock, o piso engana quem le"


def test_todo_pacote_do_requirements_aparece_travado():
    declarados = []
    for linha in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        nome = re.split(r"[><=\[]", linha, maxsplit=1)[0].strip().lower().replace("_", "-")
        declarados.append(nome)

    versoes = versoes_do_lock()
    faltando = [nome for nome in declarados if nome not in versoes]
    assert not faltando, f"declarado em requirements.txt mas sem trava: {faltando}"


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def test_restore_para_no_primeiro_erro_de_sql():
    conteudo = RESTORE.read_text(encoding="utf-8")
    assert "ON_ERROR_STOP=1" in conteudo, \
        "sem isto o psql segue depois do erro e sai 0 com o banco pela metade"
    assert "--single-transaction" in conteudo


def test_restore_e_executavel_com_fim_de_linha_unix():
    bruto = RESTORE.read_bytes()
    assert b"\r\n" not in bruto, "CRLF quebra o shebang na VPS"
    if os.name != "nt":
        assert os.stat(RESTORE).st_mode & stat.S_IXUSR


PSQL_FALSO = """\
#!/bin/sh
for a in "$@"; do
  case "$a" in -tAc) echo "${FAKE_TABELAS:-0}"; exit 0;; esac
done
echo "$@" >> "$FAKE_LOG"
exit "${FAKE_PSQL_EXIT:-0}"
"""


@pytest.fixture
def bancada(tmp_path):
    """Monta um PATH com um psql falso para exercitar o script de verdade."""
    if os.name == "nt" or not shutil.which("sh") or not shutil.which("gzip"):
        pytest.skip("precisa de shell POSIX")
    binario = tmp_path / "bin"
    binario.mkdir()
    psql = binario / "psql"
    psql.write_text(textwrap.dedent(PSQL_FALSO), encoding="utf-8")
    psql.chmod(0o755)

    dump = tmp_path / "dump.sql.gz"
    subprocess.run(f"printf 'select 1;\\n' | gzip > {dump}", shell=True, check=True)

    log = tmp_path / "psql.log"
    log.write_text("", encoding="utf-8")

    def rodar(tabelas="0", confirm=None, psql_exit="0", arquivo=None):
        ambiente = dict(os.environ)
        ambiente.update({
            "PATH": f"{binario}{os.pathsep}{ambiente['PATH']}",
            "DATABASE_URL": "postgresql://fake/fake",
            "FAKE_TABELAS": tabelas,
            "FAKE_PSQL_EXIT": psql_exit,
            "FAKE_LOG": str(log),
        })
        ambiente.pop("RESTORE_CONFIRM", None)
        if confirm is not None:
            ambiente["RESTORE_CONFIRM"] = confirm
        processo = subprocess.run(
            ["sh", str(RESTORE), str(arquivo or dump)],
            capture_output=True, text=True, env=ambiente, stdin=subprocess.DEVNULL,
        )
        return processo, log.read_text(encoding="utf-8")

    rodar.tmp_path = tmp_path
    return rodar


def test_restore_em_banco_vazio_nao_pede_confirmacao(bancada):
    processo, chamadas = bancada(tabelas="0")

    assert processo.returncode == 0, processo.stderr
    assert "ON_ERROR_STOP=1" in chamadas


def test_restore_recusa_sobrescrever_banco_com_dados_sem_confirmacao(bancada):
    processo, chamadas = bancada(tabelas="7")

    assert processo.returncode != 0
    assert chamadas == "", "o banco foi tocado mesmo sem confirmacao"
    assert "SOBRESCREVER" in processo.stdout


def test_restore_prossegue_com_confirmacao_explicita(bancada):
    processo, chamadas = bancada(tabelas="7", confirm="SOBRESCREVER")

    assert processo.returncode == 0, processo.stderr
    assert "ON_ERROR_STOP=1" in chamadas


def test_restore_recusa_confirmacao_errada(bancada):
    processo, chamadas = bancada(tabelas="7", confirm="sim")

    assert processo.returncode != 0
    assert chamadas == ""


def test_restore_propaga_falha_do_psql(bancada):
    """O sintoma original: falhar no meio e ainda assim imprimir sucesso."""
    processo, _ = bancada(tabelas="0", psql_exit="3")

    assert processo.returncode != 0
    assert "Restore concluido" not in processo.stdout


def test_restore_rejeita_backup_corrompido(bancada):
    ruim = bancada.tmp_path / "ruim.sql.gz"
    ruim.write_bytes(b"isso nao e gzip")

    processo, chamadas = bancada(tabelas="0", arquivo=ruim)

    assert processo.returncode != 0
    assert "Restore concluido" not in processo.stdout
    assert chamadas == ""
