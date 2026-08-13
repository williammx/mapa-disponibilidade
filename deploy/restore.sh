#!/usr/bin/env sh
# Restore do Postgres e dos arquivos de /data.
#
# Este script rodava `gunzip -c ... | psql` puro. Sem ON_ERROR_STOP o psql segue
# em frente depois de um erro de SQL e ainda assim termina com codigo 0: o
# restore parava no meio, o banco ficava pela metade e a ultima linha da saida
# dizia "Restore concluido". Restore e o ultimo recurso depois de um desastre -
# a unica coisa que ele nao pode fazer e mentir sobre ter dado certo.
set -eu

DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
SQL_BACKUP="${1:?Informe o arquivo postgres-*.sql.gz}"
FILES_BACKUP="${2:-}"
DATA_DIR="${DATA_DIR:-/data}"

[ -r "$SQL_BACKUP" ] || { echo "ERRO: nao consigo ler $SQL_BACKUP"; exit 1; }
[ -s "$SQL_BACKUP" ] || { echo "ERRO: $SQL_BACKUP esta vazio"; exit 1; }
if [ -n "$FILES_BACKUP" ] && [ ! -r "$FILES_BACKUP" ]; then
  echo "ERRO: nao consigo ler $FILES_BACKUP"
  exit 1
fi

# ---------------------------------------------------------------------------
# Confirmacao explicita antes de sobrescrever um banco que ja tem dados.
# Apontar o restore para o banco errado e um erro de uma tecla, e ate agora o
# script obedecia calado.
# ---------------------------------------------------------------------------
TABELAS="$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -tAc \
  "select count(*) from information_schema.tables \
    where table_schema not in ('pg_catalog', 'information_schema')")"

if [ "$TABELAS" -gt 0 ]; then
  echo "ATENCAO: o banco de destino ja tem $TABELAS tabelas."
  echo "         Continuar sobrescreve o conteudo atual."
  if [ "${RESTORE_CONFIRM:-}" = "SOBRESCREVER" ]; then
    echo "Confirmado por RESTORE_CONFIRM."
  elif [ -t 0 ]; then
    printf 'Digite SOBRESCREVER para continuar: '
    read -r RESPOSTA
    if [ "$RESPOSTA" != "SOBRESCREVER" ]; then
      echo "Cancelado. Nada foi alterado."
      exit 1
    fi
  else
    # Sem terminal (cron, CI, ssh sem tty) nao da para perguntar, e assumir
    # "sim" seria justamente o comportamento perigoso que estamos removendo.
    echo "ERRO: sem terminal para confirmar."
    echo "      Rode de novo com RESTORE_CONFIRM=SOBRESCREVER na frente do comando."
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Restore do banco.
#
# ON_ERROR_STOP=1 faz o psql parar no primeiro erro e sair diferente de zero.
# --single-transaction envolve o dump inteiro em BEGIN/COMMIT: se algo falhar no
# meio, o banco volta sozinho ao estado anterior em vez de ficar pela metade.
# Descompactar para arquivo antes, em vez de usar pipe, tambem e de proposito:
# num pipe o codigo de saida do gunzip se perde e um .gz truncado passaria batido.
# ---------------------------------------------------------------------------
TMP_SQL="$(mktemp "${TMPDIR:-/tmp}/restore-XXXXXX")"
trap 'rm -f "$TMP_SQL"' EXIT INT TERM
gunzip -c "$SQL_BACKUP" > "$TMP_SQL"

if [ "${SINGLE_TRANSACTION:-1}" = "1" ]; then
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f "$TMP_SQL"
else
  # Escape para dump que nao aceita transacao unica. Sem ela, um erro no meio
  # deixa o banco parcial: confira o resultado na mao antes de subir o servico.
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$TMP_SQL"
fi

if [ -n "$FILES_BACKUP" ]; then
  mkdir -p "$DATA_DIR"
  tar -C "$DATA_DIR" -xzf "$FILES_BACKUP"
fi

echo "Restore concluido"
