#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_mapa.py — Mede a qualidade da extracao de lotes contra o gabarito do proprio PDF.

Nao adivinha nada: usa tres fontes de verdade que ja estao impressas na planta.

  1. Rotulos de lote (L001, L002...)  -> quantos lotes existem de fato.
  2. Area impressa em cada lote        -> se a geometria extraida tem o tamanho certo.
  3. "QNNN - NN LOTES"                 -> quantos lotes cada quadra deveria ter.

Uso:
    python tools/qa_mapa.py planta.pdf [outra.pdf ...]
    python tools/qa_mapa.py --json planta.pdf     # saida legivel por maquina
    python tools/qa_mapa.py --baseline base.json planta.pdf   # compara e falha se regrediu

Codigo de saida 1 quando alguma planta regride em relacao ao baseline.
"""
import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf
from shapely.geometry import Point
from shapely.strtree import STRtree

import pdf_to_map as engine


LOT_LABEL_RE = re.compile(r"^L\s*\d{1,3}[A-Z]?$", re.I)
AREA_TEXT_RE = re.compile(r"(\d+(?:[,.]\d+)?)\s*m(?:²|2|Â²)", re.I)
DECLARED_RE = re.compile(r"([A-Z]{1,3}\d{1,4}[A-Z]?)\s*[-–—]\s*(\d{1,4})\s*LOTES", re.I)
GROUP_RE = re.compile(r"([A-ZÀ-Ú][A-ZÀ-Ú \.]{3,40}?)\s*[-–—]?\s*(\d{2,4})\s*LOTES", re.I)

# Tolerancias de aprovacao por lote (fracao do desvio em relacao a mediana).
TIGHT = 0.03
LOOSE = 0.05


def _text_rows(page):
    rows = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in spans).strip()
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            rows.append((text, Point((x0 + x1) / 2, (y0 + y1) / 2)))
    return rows


def ground_truth(page):
    """Le o gabarito impresso na planta."""
    rows = _text_rows(page)
    labels = [pt for text, pt in rows if LOT_LABEL_RE.match(re.sub(r"\s+", "", text))]

    areas = []
    for text, pt in rows:
        match = AREA_TEXT_RE.search(text)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if value > 0:
            areas.append((pt, value))

    page_text = page.get_text()
    declared = {}
    for name, count in DECLARED_RE.findall(page_text):
        declared[name.upper()] = int(count)
    groups = {}
    for name, count in GROUP_RE.findall(page_text):
        clean = " ".join(name.split())
        if DECLARED_RE.match("%s - %s LOTES" % (clean, count)):
            continue
        groups[clean.upper()] = int(count)
    return labels, areas, declared, groups


def measure(pdf_path, area_min=200.0, area_max=6000.0):
    doc = pymupdf.open(pdf_path)
    page = doc[0]
    labels, areas, declared, groups = ground_truth(page)

    lots = engine.extract_lots(page, area_min, area_max)
    metas = engine.extract_lot_metadata(page, lots) if lots else []

    report = {
        "arquivo": os.path.basename(pdf_path),
        "rotulos_na_planta": len(labels),
        "lotes_extraidos": len(lots),
        "declarado_por_quadra": sum(declared.values()) if declared else None,
        "quadras_declaradas": len(declared),
        "grupos_declarados": groups or None,
    }

    if not lots or not labels:
        report["cobertura_pct"] = 0.0
        report["area_ate_3pct"] = 0.0
        report["area_ate_5pct"] = 0.0
        report["area_acima_20pct"] = 100.0
        report["quadras_preenchidas_pct"] = 0.0
        return report

    # Cobertura: quantos rotulos cairam dentro de exatamente um lote extraido.
    tree = STRtree(lots)
    covered = 0
    duplicated = 0
    for point in labels:
        hits = [i for i in tree.query(point) if lots[int(i)].covers(point)]
        if len(hits) == 1:
            covered += 1
        elif len(hits) > 1:
            duplicated += 1
    report["cobertura_pct"] = round(100.0 * covered / len(labels), 1)
    report["rotulos_em_lote_duplicado"] = duplicated
    report["lotes_a_mais_que_rotulos"] = len(lots) - len(labels)

    # Precisao de forma: area do poligono contra a area impressa dentro dele.
    if areas:
        area_points = [a[0] for a in areas]
        area_tree = STRtree(area_points)
        ratios = []
        for poly in lots:
            found = [areas[int(i)][1] for i in area_tree.query(poly)
                     if poly.covers(area_points[int(i)])]
            if len(found) == 1:
                ratios.append(poly.area / found[0])
        if len(ratios) >= 20:
            median = statistics.median(ratios)
            deviation = sorted(abs(r / median - 1.0) for r in ratios)
            total = len(deviation)
            under = lambda t: 100.0 * sum(1 for d in deviation if d <= t) / total
            report["lotes_com_area_impressa"] = total
            report["area_ate_3pct"] = round(under(TIGHT), 1)
            report["area_ate_5pct"] = round(under(LOOSE), 1)
            report["area_acima_20pct"] = round(100.0 - under(0.20), 1)

    # Quadra: o metadado precisa identificar o lote de forma unica.
    if metas:
        with_quadra = sum(1 for m in metas if str(m.get("quadra") or "").strip())
        report["quadras_preenchidas_pct"] = round(100.0 * with_quadra / len(metas), 1)
        keys = set()
        collisions = 0
        for meta in metas:
            key = (str(meta.get("nome")), str(meta.get("quadra")))
            if key in keys:
                collisions += 1
            keys.add(key)
        report["lotes_com_nome_ambiguo"] = collisions

    # Conferencia contra a contagem declarada por quadra.
    if declared and metas:
        by_quadra = {}
        for meta in metas:
            name = str(meta.get("quadra") or "").strip().upper()
            if name:
                by_quadra[name] = by_quadra.get(name, 0) + 1
        exact = sum(1 for name, count in declared.items() if by_quadra.get(name) == count)
        report["quadras_com_contagem_exata"] = "%d/%d" % (exact, len(declared))

    return report


HIGHER_IS_BETTER = ("cobertura_pct", "area_ate_3pct", "area_ate_5pct",
                    "quadras_preenchidas_pct")
LOWER_IS_BETTER = ("area_acima_20pct", "lotes_com_nome_ambiguo")


def compare(current, baseline, tolerance=0.5):
    """Retorna a lista de regressoes encontradas."""
    problems = []
    index = {b["arquivo"]: b for b in baseline}
    for report in current:
        old = index.get(report["arquivo"])
        if not old:
            continue
        for key in HIGHER_IS_BETTER:
            if key in report and key in old and report[key] < old[key] - tolerance:
                problems.append("%s: %s caiu de %s para %s"
                                % (report["arquivo"], key, old[key], report[key]))
        for key in LOWER_IS_BETTER:
            if key in report and key in old and report[key] > old[key] + tolerance:
                problems.append("%s: %s subiu de %s para %s"
                                % (report["arquivo"], key, old[key], report[key]))
    return problems


def render(report):
    print("\n" + "=" * 74)
    print(report["arquivo"])
    print("=" * 74)
    order = [
        ("rotulos_na_planta", "rotulos de lote na planta"),
        ("lotes_extraidos", "lotes extraidos"),
        ("lotes_a_mais_que_rotulos", "lotes a mais que rotulos"),
        ("cobertura_pct", "cobertura dos rotulos (%)"),
        ("lotes_com_area_impressa", "lotes com area impressa"),
        ("area_ate_3pct", "area correta ate 3% (%)"),
        ("area_ate_5pct", "area correta ate 5% (%)"),
        ("area_acima_20pct", "area errada acima de 20% (%)"),
        ("quadras_preenchidas_pct", "lotes com quadra preenchida (%)"),
        ("lotes_com_nome_ambiguo", "lotes com nome ambiguo"),
        ("quadras_declaradas", "quadras com contagem declarada"),
        ("quadras_com_contagem_exata", "quadras batendo com o declarado"),
    ]
    for key, label in order:
        if key in report and report[key] is not None:
            print("  %-38s %s" % (label, report[key]))
    if report.get("grupos_declarados"):
        print("  grupos declarados na planta:")
        for name, count in sorted(report["grupos_declarados"].items()):
            print("      %-32s %d lotes" % (name, count))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+")
    parser.add_argument("--json", metavar="ARQUIVO",
                        help="grava o relatorio completo em JSON")
    parser.add_argument("--baseline", metavar="ARQUIVO",
                        help="compara com um JSON anterior e falha se regrediu")
    parser.add_argument("--area-min", type=float, default=200.0)
    parser.add_argument("--area-max", type=float, default=6000.0)
    args = parser.parse_args()

    reports = []
    for path in args.pdfs:
        try:
            report = measure(path, args.area_min, args.area_max)
        except Exception as exc:  # noqa: BLE001 - o relatorio precisa continuar
            report = {"arquivo": os.path.basename(path), "erro": str(exc)}
        reports.append(report)
        render(report)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(reports, handle, ensure_ascii=False, indent=2)
        print("\nrelatorio gravado em %s" % args.json)

    if args.baseline:
        with open(args.baseline, encoding="utf-8") as handle:
            baseline = json.load(handle)
        problems = compare(reports, baseline)
        print("\n" + "=" * 74)
        if problems:
            print("REGRESSAO DETECTADA")
            for item in problems:
                print("  - %s" % item)
            return 1
        print("Nenhuma regressao em relacao ao baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
