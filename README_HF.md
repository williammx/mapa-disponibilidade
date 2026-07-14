---
title: Mapa de Disponibilidade
emoji: 🗺️
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Mapa de Disponibilidade

Docker Space para executar o conversor PDF → mapa interativo.

O Space usa o mesmo FastAPI do projeto local. O arquivo deve ser publicado em
um repositorio Hugging Face Space com os arquivos `Dockerfile`, `requirements.txt`,
`api.py`, `pdf_to_map.py` e `index.html`.
