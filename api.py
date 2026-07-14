#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api.py — Site + API do gerador de mapas.
  GET  /            -> pagina de upload (index.html)
  POST /converter   -> recebe um PDF e devolve o mapa interativo (HTML, com modo Editar)
  POST /render      -> recebe lotes (JSON) e devolve o mapa final (usado pelo botao "baixar")
Rodar:  python -m pip install -r requirements.txt ; python -m uvicorn api:app --port 8000
"""
import json, os, tempfile
from fastapi import FastAPI, UploadFile, File, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import pdf_to_map

app = FastAPI(title="Mapa de Disponibilidade")
HERE = os.path.dirname(os.path.abspath(__file__))


@app.get("/health")
def health():
    """Endpoint leve para monitoramento do container e da VPS."""
    return {"status": "ok"}


@app.get("/")
def home():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.post("/converter")
async def converter(arquivo: UploadFile = File(...), rotate: str = Query("auto"),
                    area_min: float = Query(800), area_max: float = Query(9000),
                    title: str = Query("Mapa de Disponibilidade"),
                    quality: str = Query("balanced")):
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "in.pdf"); out_html = os.path.join(tmp, "out.html")
        with open(pdf_path, "wb") as fh: fh.write(await arquivo.read())
        try:
            info = pdf_to_map.convert(pdf_path, out_html, rotate=rotate,
                                      area_min=area_min, area_max=area_max,
                                      title=title, quality=quality)
        except SystemExit as exc:
            return JSONResponse({"erro": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"erro": "Nao consegui processar este arquivo (%s)." % type(exc).__name__}, status_code=400)
        html = open(out_html, encoding="utf-8").read()
    return HTMLResponse(content=html, headers={"X-Mapa-Info": json.dumps(info, ensure_ascii=False)})


@app.post("/render")
async def render(payload: dict = Body(...)):
    """Reconstroi o mapa a partir dos lotes (apos edicao)."""
    try:
        html = pdf_to_map.build_html(payload["img"], int(payload["w"]), int(payload["h"]),
                                     payload.get("lots", []),
                                     payload.get("title", "Mapa de Disponibilidade"),
                                     payload.get("img_mime", "image/jpeg"),
                                     payload.get("opacity", pdf_to_map.DEFAULT_OPACITY),
                                     payload.get("stroke_width", pdf_to_map.DEFAULT_STROKE_WIDTH),
                                     payload.get("label_mode", pdf_to_map.DEFAULT_LABEL_MODE))
    except Exception as exc:
        return JSONResponse({"erro": str(exc)}, status_code=400)
    return HTMLResponse(content=html)
