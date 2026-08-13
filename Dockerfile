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

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Lista explicita de modulos era uma armadilha: qualquer arquivo .py novo na raiz
# ficava de fora da imagem e o container so quebrava no boot, em producao, com
# ModuleNotFoundError. O .dockerignore ja limita quais .html entram (index, login
# e portal), entao o glob nao traz lixo.
COPY *.py *.html alembic.ini ./
COPY app_v1 ./app_v1
COPY alembic ./alembic
COPY demo ./demo
COPY --from=frontend-build /frontend/dist ./frontend/dist

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=3)"
CMD ["sh", "-c", "alembic upgrade head && uvicorn api:app --host 0.0.0.0 --port ${PORT}"]
