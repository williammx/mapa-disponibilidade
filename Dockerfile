FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

# Runtime libraries required by OpenCV/PyMuPDF in the slim image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# UID/GID fixos: o volume mapa_project_data guarda arquivos de clientes entre
# releases, entao o dono precisa ser o mesmo em toda imagem futura. Um UID
# sorteado pelo sistema tornaria o volume ilegivel no proximo rebuild.
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --gid ${APP_GID} nexolote \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --no-create-home --shell /usr/sbin/nologin nexolote

# O build roda na VPS a cada release. Instalar de requirements.txt, que so tem
# pisos (">="), fazia cada deploy re-resolver as versoes: um release novo do
# PyMuPDF ou do OpenCV entrava sozinho e mexia no motor de geometria recem
# calibrado. O lock traz as versoes exatas que a suite de testes verifica.
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

# Lista explicita de modulos era uma armadilha: qualquer arquivo .py novo na raiz
# ficava de fora da imagem e o container so quebrava no boot, em producao, com
# ModuleNotFoundError. O .dockerignore ja limita quais .html entram (index, login
# e portal), entao o glob nao traz lixo.
COPY *.py *.html alembic.ini ./
COPY templates ./templates
COPY app_v1 ./app_v1
COPY alembic ./alembic
COPY demo ./demo
COPY --from=frontend-build /frontend/dist ./frontend/dist

# /data existe na imagem so para carimbar o dono: quando o Docker popula um
# volume nomeado VAZIO, ele copia o conteudo e as permissoes daqui. Isso cobre
# instalacao nova. Volume que ja existe com arquivos de root nao e tocado pelo
# Docker — quem conserta esse caso e o servico mapa-storage-init do compose.yaml.
RUN mkdir -p /data/storage && chown -R ${APP_UID}:${APP_GID} /data

# /app fica de root: a aplicacao nunca escreve no proprio codigo, e o container
# nao poder reescrever os .py que executa e uma barreira barata.
#
# Ligado numa entrega separada da que subiu o mapa-storage-init, de proposito: o
# volume de producao pertencia ao root e nenhum teste prova a troca de dono, so o
# boot na VPS. Com o chown ja feito e confirmado, esta linha entra sozinha — se
# quebrar, o culpado e uma linha e nao trinta arquivos.
USER ${APP_UID}:${APP_GID}

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=3)"
CMD ["sh", "-c", "alembic upgrade head && uvicorn api:app --host 0.0.0.0 --port ${PORT}"]
