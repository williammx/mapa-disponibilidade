# Mapa de Disponibilidade

MVP que converte PDFs vetoriais de loteamentos em mapas interativos de disponibilidade. Os lotes podem receber status, cor, opacidade, etiquetas e ajustes manuais.

## Rotas

- `GET /`: pagina de envio do PDF.
- `POST /converter`: recebe um PDF e devolve o mapa HTML.
- `POST /render`: reconstroi o mapa apos as edicoes.
- `GET /health`: verificacao leve para a VPS.

## Desenvolvimento local

```powershell
python -m pip install -r requirements.txt
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

## VPS

O deploy de producao usa Docker Compose e Nginx. A aplicacao fica em `127.0.0.1:8000`; o Nginx recebe o trafego publico e encaminha as requisicoes.

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

O plano de evolucao esta em [ROADMAP.md](ROADMAP.md). A visao de produto, perfis e regras de entrega esta em [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md).
