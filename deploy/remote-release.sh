#!/usr/bin/env bash
# Publica uma release na VPS. Recebe o SHA como primeiro argumento.
#
# Este script vivia embutido num heredoc dentro do workflow. Ali ele era
# invisivel: o passo terminava em 2 segundos, sem imprimir uma linha, e ainda
# assim era marcado como sucesso — ou seja, o pipeline dizia "publicado" sem ter
# publicado nada. Em arquivo ele pode ser lido, versionado e testado.
set -euo pipefail

SHA="${1:?informe o SHA da release}"
APP_DIR="${APP_DIR:-/opt/mapa-disponibilidade}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/mapa-disponibilidade}"
ARCHIVE="/tmp/mapa-disponibilidade-${SHA}.tar.gz"
RELEASE_DIR="/tmp/mapa-disponibilidade-${SHA}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="$BACKUP_DIR/pre-deploy-${STAMP}.sql"

echo "=== INICIO DA PUBLICACAO (${SHA}) ==="
echo "host: $(hostname)  data: $(date -u)"

test -f "$ARCHIVE" || { echo "ERRO: pacote $ARCHIVE nao chegou na VPS."; exit 1; }
test -f "$APP_DIR/.env" || { echo "ERRO: $APP_DIR/.env nao existe."; exit 1; }

rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"
test -f "$RELEASE_DIR/api.py" || { echo "ERRO: pacote sem api.py."; exit 1; }
echo "Pacote extraido. api.py: $(md5sum "$RELEASE_DIR/api.py" | cut -c1-12)"

# ---------------------------------------------------------------------------
# Rede de seguranca ANTES de qualquer coisa destrutiva. O rsync abaixo usa
# --delete e o container roda `alembic upgrade head` no boot.
# ---------------------------------------------------------------------------
echo "=== BACKUP DO POSTGRES ==="
cd "$APP_DIR"
sudo mkdir -p "$BACKUP_DIR"
if ! sudo docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        | sudo tee "$BACKUP_FILE" >/dev/null; then
  echo "ABORTADO: nao consegui gerar o backup do Postgres."
  exit 1
fi
if [ ! -s "$BACKUP_FILE" ]; then
  echo "ABORTADO: o dump saiu vazio."
  exit 1
fi
sudo gzip -f "$BACKUP_FILE"
echo "Backup: ${BACKUP_FILE}.gz ($(sudo du -h "${BACKUP_FILE}.gz" | cut -f1))"

echo "=== COPIA DA VERSAO ANTERIOR ==="
sudo rm -rf "$APP_DIR.previous"
sudo cp -a "$APP_DIR" "$APP_DIR.previous"
sudo find "$BACKUP_DIR" -name 'pre-deploy-*.sql.gz' -mtime +14 -delete || true

echo "=== SINCRONIZANDO ARQUIVOS ==="
sudo rsync -a --delete --exclude=.env "$RELEASE_DIR/" "$APP_DIR/"
sudo chown -R "$USER":"$USER" "$APP_DIR"
echo "api.py em producao: $(md5sum "$APP_DIR/api.py" | cut -c1-12)"

echo "=== SUBINDO OS CONTAINERS ==="
cd "$APP_DIR"
docker compose config -q
docker compose up -d --build --remove-orphans

echo "=== CONFERINDO SAUDE ==="
for attempt in $(seq 1 45); do
  if curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null; then
    echo "Aplicacao respondeu no loopback (tentativa ${attempt})."
    docker compose ps

    # A fila e um servico separado: web verde com worker morto significa
    # conversao que nunca termina, e o deploy passava assim.
    if [ "$(docker inspect -f '{{.State.Running}}' mapa-worker 2>/dev/null)" != "true" ]; then
      echo "FALHA: a aplicacao subiu mas o worker da fila nao esta rodando."
      docker compose logs --tail=80 worker
      exit 1
    fi

    # Confere que o codigo que subiu e o que foi enviado, e nao uma imagem
    # antiga reaproveitada pelo cache do Docker.
    ESPERADO="$(md5sum "$APP_DIR/api.py" | cut -d' ' -f1)"
    NO_CONTAINER="$(docker compose exec -T mapa-disponibilidade md5sum /app/api.py | cut -d' ' -f1)"
    if [ "$ESPERADO" != "$NO_CONTAINER" ]; then
      echo "FALHA: o container esta rodando um api.py diferente do publicado."
      echo "  no disco:    $ESPERADO"
      echo "  no container:$NO_CONTAINER"
      exit 1
    fi
    echo "Container confirmado com o codigo desta release."

    rm -rf "$RELEASE_DIR" "$ARCHIVE"
    echo "=== PUBLICADO COM SUCESSO ==="
    echo "Backup desta entrega: ${BACKUP_FILE}.gz"
    echo "Versao anterior preservada em: $APP_DIR.previous"
    exit 0
  fi
  sleep 4
done

echo "=== FALHA: a aplicacao nao respondeu em 180s ==="
docker compose ps
docker compose logs --tail=120 mapa-disponibilidade
cat <<ROLLBACK
----------------------------------------------------------
Para voltar ao estado anterior, na VPS:
  sudo rsync -a --delete $APP_DIR.previous/ $APP_DIR/
  cd $APP_DIR && sudo docker compose up -d --build
  gunzip -c ${BACKUP_FILE}.gz | sudo docker compose exec -T db psql -U \$POSTGRES_USER -d \$POSTGRES_DB
----------------------------------------------------------
ROLLBACK
exit 1
