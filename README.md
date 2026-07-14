---
title: Mapa de Disponibilidade
emoji: 🗺️
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
---

# Mapa de Disponibilidade

MVP que converte PDFs vetoriais de loteamentos em mapas interativos de disponibilidade.

## Local

```powershell
uvicorn api:app --port 8000
```

O backend oferece as rotas `/converter` e `/render`. O arquivo `app.py` inicia o FastAPI no ambiente do Hugging Face Spaces.

## Publicacao

O codigo principal esta no GitHub e o backend e publicado em um Space Docker/Gradio compativel com o plano gratuito.
