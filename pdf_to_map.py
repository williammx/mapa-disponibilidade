#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_to_map.py — PDF de loteamento (CAD) -> mapa interativo (HTML).
Inclui um modo EDITAR: desenhar os lotes que faltam por cima do mapa.
100% deterministico. Nao usa IA.  Deps: python -m pip install -r requirements.txt
"""
import argparse, base64, csv, io, json, math, os, re, sys, time, unicodedata
try:
    import pymupdf
    from shapely.geometry import MultiLineString, Point, Polygon
    from shapely.strtree import STRtree
    from shapely.ops import unary_union, polygonize
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except ImportError as exc:  # pragma: no cover
    sys.exit("Faltam dependencias. Rode:\n    python -m pip install -r requirements.txt\n(detalhe: %s)" % exc)

try:
    import cv2
    import numpy as np
except ImportError:  # A extracao vetorial continua disponivel sem OpenCV.
    cv2 = None
    np = None

STATUS_NAMES = ["disponivel", "vendido", "reservado"]
STATUS_FILL = [(38, 208, 124), (110, 109, 103), (224, 97, 59)]
STATUS_HEX = ["#26d07c", "#6e6d67", "#e0613b"]
DEFAULT_OPACITY = 0.70
DEFAULT_STROKE_WIDTH = 0.60
DEFAULT_LABEL_MODE = "auto"
class MapConversionError(RuntimeError):
    """Erro esperado de entrada ou de extração, exibível no job do usuário."""


QUALITY_PRESETS = {
    "light": {"max_px": 2000, "quality": 78},
    "optimized": {"max_px": 3000, "quality": 86},
    "balanced": {"max_px": 3000, "quality": 86},
    "normal": {"max_px": 4200, "quality": 90},
    "sharp": {"max_px": 4200, "quality": 92},
    "high": {"max_px": 6800, "quality": 94},
}


def _clamp_float(value, default, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _clean_label_mode(value):
    value = str(value or DEFAULT_LABEL_MODE).strip().lower()
    return value if value in ("auto", "always", "hidden") else DEFAULT_LABEL_MODE


def _quality_settings(name):
    key = str(name or "balanced").strip().lower()
    if key not in QUALITY_PRESETS:
        key = "balanced"
    settings = dict(QUALITY_PRESETS[key])
    settings["name"] = key
    return settings


def _encode_background(image, settings):
    quality = int(settings["quality"])
    buf = io.BytesIO()
    try:
        image.save(buf, "WEBP", quality=quality, method=4)
        return base64.b64encode(buf.getvalue()).decode(), "image/webp"
    except Exception:
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=min(95, quality + 4), optimize=True)
        return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def _segments(page):
    """Malha vetorial completa da pagina, com as curvas preservadas.

    Loteamentos radiais tem frente e fundo de lote em arco. Reduzir cada curva a
    corda entre o primeiro e o ultimo ponto deforma o lote inteiro, entao aqui a
    tesselacao segue a tolerancia de achatamento (ver ``_bezier_steps``).
    """
    segs = []
    for d in page.get_drawings():
        for it in d["items"]:
            segs.extend(_significant_item_segments(it))
    return segs


def _legacy_segments(page):
    """Malha com curvas reduzidas a cordas para compatibilidade.

    Algumas plantas antigas foram validadas com esta representacao. Ela entra
    apenas como candidata em PDFs com camadas; o ranking decide entre ela e a
    malha curva atual usando qualidade e cobertura dos rotulos.
    """
    segments = []
    for drawing in page.get_drawings():
        for item in drawing.get("items") or []:
            segments.extend(_drawing_item_segments(item, curve_steps=1))
    return [segment for segment in segments
            if ((segment[0][0] - segment[1][0]) ** 2 +
                (segment[0][1] - segment[1][1]) ** 2 > 1.0)]


CAD_LOT_LAYERS = {"lote"}
CAD_LOT_LAYER_PREFIXES = ("4_fnc_",)
CAD_LAYER_SNAP = 0.75
CAD_LAYER_SNAP_CANDIDATES = (0.75, 1.25, 1.75, 2.25, 2.75)
CAD_LOCAL_RECOVERY_SNAPS = (0.50, 0.75, 1.00, 1.25)
ANCHOR_GUIDED_SNAPS = (None, 0.50, 0.75, 1.00, 1.25, 1.75)
_AUXILIARY_LAYER_MARKERS = (
    "veget", "texto", "text", "txt", "label", "simbol", "symbol", "dim",
    "sector", "lake", "area_net", "app lagoa", "etapa",
)


def _is_cad_lot_layer(layer):
    name = str(layer or "").strip().lower()
    return name in CAD_LOT_LAYERS or name.startswith(CAD_LOT_LAYER_PREFIXES)


def _append_segment(segments, a, b, min_length_sq=0.0001):
    if (a[0]-b[0])**2 + (a[1]-b[1])**2 > min_length_sq:
        segments.append((a, b))


CURVE_FLATNESS_TOL = 0.08     # pt de afastamento maximo entre a curva e a corda
MAX_CURVE_STEPS = 64
_MIN_SEGMENT_LENGTH_SQ = 0.01  # ~0,1 pt: so remove segmento degenerado


def _bezier_steps(p0, p1, p2, p3, tolerance=CURVE_FLATNESS_TOL):
    """Quantos segmentos a curva precisa para ficar dentro da tolerancia.

    Estima a flecha (distancia maxima entre a curva e a corda) pelos pontos de
    controle. Curva quase reta continua valendo um segmento; arco fechado ganha
    quantos pontos forem necessarios. Sem isso, uma frente de lote em arco vira
    uma corda reta e o lote inteiro sai com a area errada.
    """
    chord = math.hypot(p3.x - p0.x, p3.y - p0.y)
    if chord <= 1e-6:
        return 1
    first = abs((p1.x - p0.x) * (p3.y - p0.y) - (p1.y - p0.y) * (p3.x - p0.x))
    second = abs((p2.x - p0.x) * (p3.y - p0.y) - (p2.y - p0.y) * (p3.x - p0.x))
    sagitta = (first + second) / chord
    if sagitta <= tolerance:
        return 1
    return min(MAX_CURVE_STEPS,
               max(2, int(math.ceil(math.sqrt(sagitta / tolerance) * 4))))


def _drawing_item_segments(item, curve_steps=None):
    """Converte um item vetorial do PDF em segmentos, preservando curvas.

    ``curve_steps=None`` usa a tesselacao adaptativa, que e o comportamento
    correto. Um numero fixo so deve ser usado em teste.
    """
    segments = []
    kind = item[0]
    if kind == "l":
        a, b = item[1], item[2]
        _append_segment(segments, (a.x, a.y), (b.x, b.y))
    elif kind == "c":
        p0, p1, p2, p3 = item[1], item[2], item[3], item[4]
        steps = curve_steps or _bezier_steps(p0, p1, p2, p3)
        previous = (p0.x, p0.y)
        for step in range(1, steps + 1):
            t = step / steps
            u = 1.0 - t
            current = (
                u**3*p0.x + 3*u*u*t*p1.x + 3*u*t*t*p2.x + t**3*p3.x,
                u**3*p0.y + 3*u*u*t*p1.y + 3*u*t*t*p2.y + t**3*p3.y,
            )
            _append_segment(segments, previous, current)
            previous = current
    elif kind == "re":
        rect = item[1]
        corners = [(rect.x0, rect.y0), (rect.x1, rect.y0),
                   (rect.x1, rect.y1), (rect.x0, rect.y1)]
        for index in range(4):
            _append_segment(segments, corners[index], corners[(index + 1) % 4])
    elif kind == "qu":
        quad = item[1]
        corners = [(quad.ul.x, quad.ul.y), (quad.ur.x, quad.ur.y),
                   (quad.lr.x, quad.lr.y), (quad.ll.x, quad.ll.y)]
        for index in range(4):
            _append_segment(segments, corners[index], corners[(index + 1) % 4])
    return segments


def _significant_item_segments(item, min_total_length_sq=1.0):
    """Segmentos de um item, descartando o item inteiro se ele for irrelevante.

    O filtro precisa olhar o item como um todo, nao pedaco por pedaco. Um arco
    tesselado vira varios segmentos curtos que, isolados, pareceriam ruido e
    seriam jogados fora justamente na parte curva do lote.
    """
    segments = _drawing_item_segments(item)
    if not segments:
        return []
    total = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in segments)
    if total * total <= min_total_length_sq:
        return []
    return segments


def _normalized_layer_name(layer):
    value = unicodedata.normalize("NFKD", str(layer or ""))
    return value.encode("ascii", "ignore").decode("ascii").strip().lower()


def _is_auxiliary_geometry_layer(layer):
    """Identifica camadas de anotacao que nao podem dividir lotes."""
    name = _normalized_layer_name(layer)
    return any(marker in name for marker in _AUXILIARY_LAYER_MARKERS)


def _geometry_only_segments(page):
    """Le a malha vetorial sem textos, rotulos, cotas e simbolos do CAD.

    Alguns projetos nao usam as camadas cadastrais ``4_fnc_*`` / ``LOTE``.
    Neles, polygonizar todos os desenhos mistura as divisas com setas, mascaras
    brancas e identificadores de quadra. A separacao acontece em memoria para
    manter o PDF original intacto e os textos disponiveis para metadados.
    """
    try:
        drawings = page.get_drawings(extended=True)
    except TypeError:
        return []
    segments = []
    for drawing in drawings:
        if _is_auxiliary_geometry_layer(drawing.get("layer")):
            continue
        for item in drawing.get("items") or []:
            segments.extend(_significant_item_segments(item))
    return segments


def _layered_lot_segments(page, curve_steps=None):
    """Le somente as camadas cadastrais; ignora textos, ruas e hachuras."""
    segments = []
    layers = set()
    try:
        drawings = page.get_drawings(extended=True)
    except TypeError:  # PyMuPDF antigo: sem informacao de OCG/camada.
        return [], set()
    for drawing in drawings:
        layer = str(drawing.get("layer") or "").strip()
        if not _is_cad_lot_layer(layer):
            continue
        layers.add(layer)
        for item in drawing.get("items") or []:
            segments.extend(_drawing_item_segments(item, curve_steps=curve_steps))
    return segments, layers


def _layered_lots(page, label_points, area_min, area_max, curve_steps=None):
    """Extrai lotes das OCGs do CAD sem cruzar linhas de outras camadas."""
    segments, layers = _layered_lot_segments(page, curve_steps=curve_steps)
    if not segments or not label_points:
        return []

    # Fecha lotes recortados exatamente na borda fisica da prancha. Alguns PDFs
    # CAD declaram a pagina em paisagem, mas mantem a malha em coordenadas de
    # retrato: nesses casos a geometria ultrapassa page.rect e essa borda viraria
    # uma linha artificial atravessando lotes validos.
    x0, y0, x1, y1 = page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1
    content_exceeds_page = any(
        point[0] < x0 - 0.5 or point[0] > x1 + 0.5 or
        point[1] < y0 - 0.5 or point[1] > y1 + 0.5
        for segment in segments for point in segment)
    if not content_exceeds_page:
        segments.extend([((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                         ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))])
    label_tree = STRtree(label_points)
    min_area = min(float(area_min), 80.0)
    max_area = max(float(area_max), 15000.0)

    def lots_for_snap(grid):
        snapped = _snapped_segments(segments, grid, min_length_sq=0.0001)
        found = []
        for candidate in polygonize(unary_union(MultiLineString(snapped))):
            if not min_area <= candidate.area <= max_area:
                continue
            hits = [point for point in _tree_hits(label_tree, label_points, candidate)
                    if candidate.contains(point)]
            if len(hits) == 1:
                found.append(_clean_lot_polygon(candidate))
        return _dedupe_polygons(found, tol=0.20)

    lots = lots_for_snap(CAD_LAYER_SNAP)
    # Pranchas maiores ou exportadas com menor precisao deixam frestas acima de
    # 0,75 pt. So ampliamos a busca quando a primeira passagem ficou incompleta;
    # as camadas cadastrais continuam isoladas das ruas, textos e hachuras.
    if len(lots) < len(label_points) * 0.95:
        for grid in CAD_LAYER_SNAP_CANDIDATES[1:]:
            candidate_lots = lots_for_snap(grid)
            if len(candidate_lots) > len(lots):
                lots = candidate_lots
    # Um PDF pode ter uma camada chamada LOTE sem que ela represente a malha
    # inteira. So trocamos de motor quando as OCGs explicam a maior parte do mapa.
    minimum_coverage = max(40, int(len(label_points) * 0.70))
    return lots if len(layers) >= 2 and len(lots) >= minimum_coverage else []


def _snapped_segments(segs, grid, min_length_sq=1.0):
    if not grid:
        return segs
    snapped = []
    for a, b in segs:
        aa = (round(a[0]/grid)*grid, round(a[1]/grid)*grid)
        bb = (round(b[0]/grid)*grid, round(b[1]/grid)*grid)
        if (aa[0]-bb[0])**2 + (aa[1]-bb[1])**2 > min_length_sq:
            snapped.append((aa, bb))
    return snapped


def _dedupe_polygons(polys, tol=1.0):
    seen, out = set(), []
    for p in sorted(polys, key=lambda g: (round(g.centroid.y/tol), round(g.centroid.x/tol), -g.area)):
        c = p.centroid
        key = (round(c.x/tol), round(c.y/tol))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _corner_count(poly, tolerance=0.5):
    """Cantos reais do lote, ignorando os pontos de tesselacao de arco.

    Contar vertice bruto castiga justamente o lote correto: numa praca de
    retorno a frente e um arco e, com a curva preservada, ela sozinha traz
    dezenas de pontos. A simplificacao devolve a forma em cantos — uma fatia de
    pizza tem 4 ou 5, nao 60.
    """
    try:
        simplified = poly.simplify(tolerance, preserve_topology=True)
        if simplified.is_empty or simplified.geom_type != "Polygon":
            return len(poly.exterior.coords)
        return len(simplified.exterior.coords)
    except Exception:
        return len(poly.exterior.coords)


def _looks_like_lot(poly):
    try:
        rect = poly.minimum_rotated_rectangle
        rect_area = rect.area
    except Exception:
        return False
    if rect_area <= 0:
        return False
    fill_ratio = poly.area / rect_area
    return _corner_count(poly) <= 20 and fill_ratio >= 0.62


def _clean_lot_polygon(poly):
    if poly.is_valid and poly.area > 0:
        return poly
    fixed = poly.buffer(0)
    if fixed.is_empty:
        return poly
    if fixed.geom_type == "Polygon":
        return fixed
    if fixed.geom_type == "MultiPolygon":
        return max(fixed.geoms, key=lambda g: g.area)
    return poly


def _lot_label_points(page):
    return [Point(item["cx"], item["cy"])
            for item in _text_items(page) if _extract_lot_name(item["text"])]


def _tree_hits(tree, geometries, geometry):
    hits = []
    for hit in tree.query(geometry):
        idx = int(hit) if not hasattr(hit, "contains") else geometries.index(hit)
        if 0 <= idx < len(geometries):
            hits.append(geometries[idx])
    return hits


def _anchor_guided_lots_from_segments(segments, label_points, area_min, area_max,
                                      snap_candidates=ANCHOR_GUIDED_SNAPS):
    """Escolhe no maximo uma face compacta para cada rotulo de lote.

    O rotulo funciona somente como ancora. Ele nunca vira geometria e faces sem
    rotulo sao descartadas, eliminando letras vazadas, setas e mascaras de CAD.
    """
    if not segments or not label_points:
        return []
    label_tree = STRtree(label_points)
    minimum = min(float(area_min), 80.0)
    maximum = max(float(area_max), 15000.0)
    chosen = {}

    for snap_rank, grid in enumerate(snap_candidates):
        snapped = (segments if grid is None else
                   _snapped_segments(segments, grid, min_length_sq=0.0001))
        if not snapped:
            continue
        try:
            faces = polygonize(unary_union(MultiLineString(snapped)))
            for candidate in faces:
                if not minimum <= candidate.area <= maximum:
                    continue
                hit_indexes = []
                for hit in label_tree.query(candidate):
                    index = (int(hit) if not hasattr(hit, "contains") else
                             label_points.index(hit))
                    if candidate.covers(label_points[index]):
                        hit_indexes.append(index)
                if len(hit_indexes) != 1:
                    continue

                try:
                    rectangle_area = candidate.minimum_rotated_rectangle.area
                    fill_ratio = candidate.area / max(rectangle_area, 1.0)
                    # Cantos, nao vertices: o arco da praca de retorno traz
                    # dezenas de pontos e reprovaria um lote perfeitamente valido.
                    vertex_count = _corner_count(candidate)
                    centered = (candidate.centroid.distance(label_points[hit_indexes[0]]) /
                                max(candidate.area ** 0.5, 1.0))
                except Exception:
                    continue
                if fill_ratio < 0.55 or vertex_count > 32 or centered > 0.65:
                    continue

                score = (snap_rank, abs(1.0 - fill_ratio), centered,
                         vertex_count, candidate.area)
                previous = chosen.get(hit_indexes[0])
                if previous is None or score < previous[0]:
                    chosen[hit_indexes[0]] = (score, _clean_lot_polygon(candidate))
        except Exception:
            continue
    return [chosen[index][1] for index in sorted(chosen)]


_NON_LOT_AREA_RE = re.compile(
    r"(?:\bA\s*\.?\s*V\s*\.?\s*\d|\bOPUB\s*\d*|\bAPP\b)", re.I)


def _is_non_lot_area_text(text):
    """Reconhece identificadores de areas comuns que se parecem com lotes."""
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = value.encode("ascii", "ignore").decode("ascii")
    return bool(_NON_LOT_AREA_RE.search(value))


def _rotated_lot_profile(poly):
    """Retorna largura, comprimento e angulo do retangulo orientado."""
    coords = list(poly.minimum_rotated_rectangle.exterior.coords)
    edges = []
    for start, end in zip(coords, coords[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        edges.append((length, math.degrees(math.atan2(dy, dx)) % 180.0))
    if not edges:
        return 0.0, 0.0, 0.0
    longest = max(edges, key=lambda edge: edge[0])
    return min(edge[0] for edge in edges), longest[0], longest[1]


def _angle_distance(first, second):
    difference = abs(first - second) % 180.0
    return min(difference, 180.0 - difference)


def _has_compatible_lot_geometry(candidate, references, strict=True):
    """Confirma que a face tem as duas dimensoes de um lote local."""
    try:
        short, long, angle = _rotated_lot_profile(candidate)
    except Exception:
        return False
    if short <= 0 or long <= 0:
        return False
    short_limit, long_limit, angle_limit = (
        (0.75, 0.70, 14.0) if strict else (0.60, 0.60, 20.0))
    for reference in references:
        try:
            ref_short, ref_long, ref_angle = _rotated_lot_profile(reference)
        except Exception:
            continue
        if ref_short <= 0 or ref_long <= 0:
            continue
        short_ratio = min(short / ref_short, ref_short / short)
        long_ratio = min(long / ref_long, ref_long / long)
        if (short_ratio >= short_limit and long_ratio >= long_limit and
                _angle_distance(angle, ref_angle) <= angle_limit):
            return True
    return False


def _page_rgb_image(page):
    try:
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.0, 1.0), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except Exception:
        return None


def _is_blue_road_candidate(image, page, candidate):
    """Rejeita faces que pertencem as vias azuis do desenho urbanistico."""
    if image is None:
        return False
    try:
        point = candidate.representative_point()
        scale_x = image.width / max(float(page.rect.width), 1.0)
        scale_y = image.height / max(float(page.rect.height), 1.0)
        center_x = max(0, min(image.width - 1, round(point.x * scale_x)))
        center_y = max(0, min(image.height - 1, round(point.y * scale_y)))
        samples = []
        for offset_y in (-2, 0, 2):
            for offset_x in (-2, 0, 2):
                x = max(0, min(image.width - 1, center_x + offset_x))
                y = max(0, min(image.height - 1, center_y + offset_y))
                samples.append(image.getpixel((x, y)))
        red = sorted(pixel[0] for pixel in samples)[len(samples) // 2]
        green = sorted(pixel[1] for pixel in samples)[len(samples) // 2]
        blue = sorted(pixel[2] for pixel in samples)[len(samples) // 2]
        return blue >= 220 and blue - red >= 20 and blue - green >= 10
    except Exception:
        return False


def _recover_unlabelled_neighbor_lots(page, trusted_lots, label_points, segments,
                                      area_min, area_max):
    """Recupera faces sem texto quando a vizinhanca prova que sao lotes.

    Titulos e mascaras de CAD podem apagar o pequeno identificador ``Lxx`` sem
    apagar toda a divisa. A face so entra quando encosta em dois lotes ja
    validados, tem escala local compativel e nao representa uma area comum.
    """
    if not trusted_lots or not segments:
        return []

    minimum = min(float(area_min), 80.0)
    maximum = max(float(area_max), 15000.0)
    label_tree = STRtree(label_points) if label_points else None
    trusted_tree = STRtree(trusted_lots)
    trusted_union = unary_union(trusted_lots)
    page_image = _page_rgb_image(page)
    represented_labels = {
        index for index, point in enumerate(label_points)
        if trusted_union.covers(point)
    }
    excluded_points = [
        Point(item["cx"], item["cy"])
        for item in _text_items(page)
        if _is_non_lot_area_text(item["text"])
    ]
    candidates = []

    try:
        faces = polygonize(unary_union(MultiLineString(segments)))
        for candidate in faces:
            if not minimum <= candidate.area <= maximum:
                continue
            candidate_labels = []
            if label_tree:
                candidate_labels = [
                    label_points.index(point)
                    for point in _tree_hits(
                        label_tree, label_points, candidate)
                    if candidate.covers(point)
                ]
            # Uma face com mais de um rotulo ainda esta agrupada. Uma face com
            # um rotulo ja representado sobrepoe um lote confiavel.
            if (len(candidate_labels) > 1 or
                    any(index in represented_labels
                        for index in candidate_labels)):
                continue
            if any(candidate.covers(point) for point in excluded_points):
                continue

            try:
                rectangle_area = candidate.minimum_rotated_rectangle.area
                fill_ratio = candidate.area / max(rectangle_area, 1.0)
                vertex_count = len(candidate.exterior.coords)
            except Exception:
                continue
            if fill_ratio < 0.55 or vertex_count > 32:
                continue
            if candidate.intersection(trusted_union).area / candidate.area > 0.08:
                continue
            if _is_blue_road_candidate(page_image, page, candidate):
                continue
            references = [
                lot for lot in _tree_hits(
                    trusted_tree, trusted_lots, candidate.buffer(12.0))
                if candidate.distance(lot) <= 12.0
            ]
            if not _has_compatible_lot_geometry(
                    candidate, references, strict=not bool(candidate_labels)):
                continue
            candidates.append((_clean_lot_polygon(candidate), candidate_labels))
    except Exception:
        return []

    # Propaga a confianca ao longo de uma fileira. Isso recupera sequencias de
    # lotes ocultadas por um titulo grande, mas exige duas bordas conhecidas para
    # faces sem rotulo. Um rotulo unico e ainda nao usado vale como uma ancora.
    recovered = []
    current_lots = list(trusted_lots)
    pending = candidates
    for _pass in range(6):
        if not pending:
            break
        current_tree = STRtree(current_lots)
        accepted = []
        remaining = []
        for candidate, candidate_labels in pending:
            local_lots = [
                lot for lot in _tree_hits(
                    current_tree, current_lots, candidate.buffer(2.01))
                if candidate.distance(lot) <= 2.0
            ]
            minimum_neighbors = 1 if candidate_labels else 2
            if len(local_lots) < minimum_neighbors:
                remaining.append((candidate, candidate_labels))
                continue
            local_areas = sorted(lot.area for lot in local_lots)
            local_median = local_areas[len(local_areas) // 2]
            area_ratio = candidate.area / max(local_median, 1.0)
            if not 0.50 <= area_ratio <= 1.80:
                remaining.append((candidate, candidate_labels))
                continue
            accepted.append((candidate, candidate_labels))

        if not accepted:
            break
        for candidate, candidate_labels in accepted:
            recovered.append(candidate)
            current_lots.append(candidate)
            represented_labels.update(candidate_labels)
        pending = remaining
    return _dedupe_polygons(recovered, tol=0.20)


def _anchor_guided_lots(page, label_points, area_min, area_max):
    """Fallback de duas passagens para PDFs CAD com camadas nao padronizadas."""
    if len(label_points) < 40:
        return []
    segments = _geometry_only_segments(page)
    lots = _anchor_guided_lots_from_segments(
        segments, label_points, area_min, area_max)
    minimum_coverage = max(40, math.ceil(len(label_points) * 0.94))
    if len(lots) < minimum_coverage:
        return []
    recovered = _recover_unlabelled_neighbor_lots(
        page, lots, label_points, segments, area_min, area_max)
    return lots + recovered


def _repair_lot_gaps(page, lots, area_min, area_max, label_points=None,
                     segments=None):
    """Fecha falhas locais usando os rótulos de lote como pontos de ancoragem.

    O snap global cria polígonos falsos em textos, ruas e áreas verdes. Aqui ele
    só é usado para recuperar um polígono que contém um rótulo de lote que ficou
    sem nenhuma geometria na malha original.
    """
    lot_points = label_points or _lot_label_points(page)
    lot_tree = STRtree(lots) if lots else None
    missing = [pt for pt in lot_points
               if not lot_tree or not any(poly.contains(pt) for poly in _tree_hits(lot_tree, lots, pt))]
    if not missing:
        return lots

    snapped = _snapped_segments(
        segments if segments is not None else _segments(page), 1.0)
    repaired = list(lots)
    repaired_tree = STRtree(repaired) if repaired else None
    for candidate in polygonize(unary_union(MultiLineString(snapped))):
        if not area_min <= candidate.area <= area_max:
            continue
        candidate_hits = [pt for pt in missing if candidate.contains(pt)]
        if not candidate_hits:
            continue
        if any(candidate.intersection(existing).area / max(1.0, min(candidate.area, existing.area)) > 0.90
               for existing in _tree_hits(repaired_tree, repaired, candidate) if repaired_tree):
            continue
        repaired.append(_clean_lot_polygon(candidate))
        repaired_tree = STRtree(repaired)
    return repaired


def _nearest_component(component_map, x, y, max_radius=36):
    """Retorna o preenchimento mais proximo de um texto, ignorando o proprio texto."""
    height, width = component_map.shape
    for radius in range(0, max_radius + 1, 2):
        top, bottom = max(0, y-radius), min(height, y+radius+1)
        left, right = max(0, x-radius), min(width, x+radius+1)
        values = component_map[top:bottom, left:right]
        values = values[values > 0]
        if values.size:
            ids, counts = np.unique(values, return_counts=True)
            return int(ids[np.argmax(counts)])
    return 0


def _filled_lot_polygons(page):
    """Extrai lotes pelo preenchimento original do PDF, quando ele existir.

    Alguns PDFs CAD trazem linhas auxiliares que se cruzam fora das divisas. A
    polygonizacao dessas linhas produz recortes diagonais. Em mapas com os lotes
    preenchidos, a regiao de cor e uma fonte geometrica mais fiel: cada lote e
    identificado pelo seu texto e somente componentes com um unico rotulo entram.
    """
    if cv2 is None or np is None:
        return []
    scale = 2.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]

    # Cores de lote encontradas nos mapas de disponibilidade: amarelo, vermelho
    # e verde. Areas de rua/parque ficam de fora por nao conterem um rotulo Lxx.
    yellow = (red >= 245) & (green >= 205) & (green <= 240) & (blue >= 90) & (blue <= 175)
    coral = (red >= 245) & (green >= 95) & (green <= 180) & (blue >= 85) & (blue <= 185)
    lime = (red >= 145) & (red <= 215) & (green >= 205) & (green <= 255) & (blue >= 80) & (blue <= 185)
    mask = (yellow | coral | lime).astype(np.uint8)
    _, component_map, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    anchors = _lot_label_points(page)
    component_anchors = {}
    for anchor in anchors:
        component_id = _nearest_component(component_map, round(anchor.x * scale), round(anchor.y * scale))
        if component_id:
            component_anchors.setdefault(component_id, []).append(anchor)

    lots = []
    for component_id, matches in component_anchors.items():
        if len(matches) != 1 or stats[component_id, cv2.CC_STAT_AREA] < 20:
            continue
        x, y, width, height, _ = stats[component_id]
        local = (component_map[y:y+height, x:x+width] == component_id).astype(np.uint8)
        contours, _ = cv2.findContours(local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        perimeter = cv2.arcLength(contour, True)
        contour = cv2.approxPolyDP(contour, max(1.2, perimeter * 0.002), True)
        points = [((x + point[0][0]) / scale, (y + point[0][1]) / scale) for point in contour]
        if len(points) < 3:
            continue
        poly = _clean_lot_polygon(Polygon(points)).simplify(0.30, preserve_topology=True)
        if poly.is_empty or poly.geom_type != "Polygon" or poly.area <= 20:
            continue
        # O contorno externo inclui o local do texto, mesmo que o texto seja um
        # furo preto no raster. Esta checagem protege contra componentes proximos.
        if not poly.covers(matches[0]):
            continue
        lots.append(poly)
    return _dedupe_polygons(lots, tol=0.35)


def _clean_point_set(pts):
    poly = Polygon(pts)
    if poly.is_valid and poly.area > 0:
        return pts
    fixed = poly.buffer(0)
    if fixed.is_empty:
        return pts
    if fixed.geom_type == "MultiPolygon":
        fixed = max(fixed.geoms, key=lambda g: g.area)
    if fixed.geom_type != "Polygon" or fixed.area <= 0:
        return pts
    return [(round(x, 2), round(y, 2)) for x, y in fixed.exterior.coords]


def _extract_lots_global(page, area_min, area_max, label_points=None, segments=None):
    segs = segments if segments is not None else _segments(page)
    if not segs: return []
    # O snap agressivo fecha algumas frestas, mas neste tipo de CAD cria falsos
    # positivos em textos/fragmentos. O caminho mais confiavel para o Setor E e
    # usar a malha vetorial original e deixar ajustes finos para a edicao.
    lots = [_clean_lot_polygon(p) for p in polygonize(unary_union(MultiLineString(segs)))
            if area_min <= p.area <= area_max]
    label_points = label_points or _lot_label_points(page)
    if label_points and len(lots) < max(40, int(len(label_points) * 0.75)):
        adaptive_min = min(area_min, 200)
        adaptive_max = max(area_max, 6000)
        adaptive_lot_max = min(adaptive_max, 2500)
        broad = [p for p in polygonize(unary_union(MultiLineString(segs)))
                 if adaptive_min <= p.area <= adaptive_lot_max]
        label_tree = STRtree(label_points)
        selected = []
        for candidate in broad:
            hits = [pt for pt in _tree_hits(label_tree, label_points, candidate)
                    if candidate.contains(pt)]
            # Sem rótulo individual, só aceitamos uma pequena célula. Contornos
            # maiores normalmente são quadras/áreas agrupadas e não lotes.
            centered = bool(hits) and candidate.centroid.distance(hits[0]) / max(1.0, candidate.area ** 0.5) <= 0.40
            if (len(hits) == 1 and _looks_like_lot(candidate) and centered) or (
                    not hits and candidate.area <= 1000 and _looks_like_lot(candidate)):
                selected.append(_clean_lot_polygon(candidate))
        lots = selected
        return _repair_lot_gaps(
            page, lots, adaptive_min, adaptive_lot_max, label_points,
            segments=segs)
    return _repair_lot_gaps(
        page, lots, area_min, area_max, label_points, segments=segs)


def _recover_layered_gaps(page, layered_lots, label_points, area_min, area_max,
                           global_lots=None):
    """Recupera somente celulas isoladas que nao invadem a malha por camadas."""
    layered_tree = STRtree(layered_lots)
    missing = [point for point in label_points
               if not any(poly.contains(point)
                          for poly in _tree_hits(layered_tree, layered_lots, point))]
    if not missing:
        return layered_lots

    recovered = list(layered_lots)
    recovered_tree = STRtree(recovered)
    if global_lots is None:
        global_lots = _extract_lots_global(page, area_min, area_max, label_points)

    # Recorta candidatos globais pela malha confiavel e valida o resultado pela
    # escala entre a area vetorial e a area impressa no proprio lote.
    trusted_metas = extract_lot_metadata(page, layered_lots)
    area_ratios = []
    for poly, meta in zip(layered_lots, trusted_metas):
        match = re.search(r"\d+(?:[,.]\d+)?", str(meta.get("area", "")))
        if match:
            printed = float(match.group(0).replace(",", "."))
            if printed > 0:
                area_ratios.append(poly.area / printed)
    median_ratio = None
    area_points, area_values = [], []
    area_tree = None
    if len(area_ratios) >= max(30, int(len(layered_lots) * 0.60)):
        area_ratios.sort()
        median_ratio = area_ratios[len(area_ratios) // 2]
        for item in _text_items(page):
            area_text = _extract_area(item["text"])
            match = re.search(r"\d+(?:[,.]\d+)?", area_text)
            if match:
                area_points.append(Point(item["cx"], item["cy"]))
                area_values.append(float(match.group(0).replace(",", ".")))
        area_tree = STRtree(area_points) if area_points else None
        trusted_union = unary_union(layered_lots)
        clipped_candidates = []
        for candidate in global_lots:
            hits = [point for point in missing if candidate.contains(point)]
            if len(hits) != 1:
                continue
            difference = candidate.difference(trusted_union)
            parts = list(difference.geoms) if hasattr(difference, "geoms") else [difference]
            parts = [part for part in parts
                     if part.geom_type == "Polygon" and part.covers(hits[0]) and part.area > 100]
            if not parts:
                continue
            part = max(parts, key=lambda geometry: geometry.area)
            printed_areas = []
            if area_tree:
                for hit in area_tree.query(part):
                    index = int(hit) if not hasattr(hit, "contains") else area_points.index(hit)
                    if part.contains(area_points[index]):
                        printed_areas.append(area_values[index])
            if not printed_areas:
                continue
            printed = min(printed_areas,
                          key=lambda value: abs(part.area / max(value, 0.01) - median_ratio))
            relative_ratio = (part.area / printed) / median_ratio
            if 0.60 <= relative_ratio <= 1.45:
                clipped_candidates.append((part.area, part, hits[0]))

        for _, candidate, anchor in sorted(clipped_candidates):
            if anchor not in missing:
                continue
            if any(candidate.intersection(existing).area > 0.75
                   for existing in _tree_hits(recovered_tree, recovered, candidate)):
                continue
            recovered.append(_clean_lot_polygon(candidate))
            missing.remove(anchor)
            recovered_tree = STRtree(recovered)

    # A tolerancia que fecha mais lotes no mapa inteiro pode, pontualmente, unir
    # duas celulas curvas em uma unica face. Repete a polygonizacao com snap fino
    # somente para rotulos ainda descobertos e valida cada face pela vizinhanca.
    if missing:
        layered_segments, _ = _layered_lot_segments(page)
        if layered_segments:
            label_tree = STRtree(label_points)
            recovered_union = unary_union(recovered)
            local_min = min(float(area_min), 80.0)
            local_max = max(float(area_max), 15000.0)
            for local_snap in CAD_LOCAL_RECOVERY_SNAPS:
                if not missing:
                    break
                fine_segments = _snapped_segments(
                    layered_segments, local_snap, min_length_sq=0.0001)
                local_candidates = []
                for candidate in polygonize(unary_union(MultiLineString(fine_segments))):
                    if not local_min <= candidate.area <= local_max:
                        continue
                    hits = [point for point in _tree_hits(label_tree, label_points, candidate)
                            if candidate.covers(point)]
                    if len(hits) != 1 or hits[0] not in missing:
                        continue
                    try:
                        rect_area = candidate.minimum_rotated_rectangle.area
                        fill_ratio = candidate.area / max(rect_area, 1.0)
                        vertex_count = len(candidate.exterior.coords)
                    except Exception:
                        continue
                    # Lotes em curvas possuem mais vertices que um quadrilatero,
                    # mas continuam compactos. Isso exclui contornos de rua/quadra.
                    if fill_ratio < 0.58 or vertex_count > 28:
                        continue

                    anchor = hits[0]
                    nearby_areas = sorted(
                        ((poly.distance(anchor), poly.area) for poly in recovered),
                        key=lambda item: item[0])[:8]
                    if len(nearby_areas) < 4:
                        continue
                    areas = sorted(area for _, area in nearby_areas)
                    middle = len(areas) // 2
                    local_median = ((areas[middle - 1] + areas[middle]) / 2
                                    if len(areas) % 2 == 0 else areas[middle])
                    area_ratio = candidate.area / max(local_median, 1.0)
                    neighborhood_ok = 0.72 <= area_ratio <= 1.32

                    printed = None
                    if median_ratio and area_tree:
                        printed_areas = []
                        for hit in area_tree.query(candidate):
                            index = int(hit) if not hasattr(hit, "contains") else area_points.index(hit)
                            if candidate.covers(area_points[index]):
                                printed_areas.append(area_values[index])
                        if printed_areas:
                            printed = min(
                                printed_areas,
                                key=lambda value: abs(candidate.area / max(value, 0.01) - median_ratio))
                    printed_ok = bool(printed) and 0.72 <= (
                        candidate.area / printed) / median_ratio <= 1.32
                    if not neighborhood_ok and not printed_ok:
                        continue
                    overlap_ratio = candidate.intersection(recovered_union).area / candidate.area
                    if overlap_ratio > 0.08:
                        continue
                    score_ratio = ((candidate.area / printed) / median_ratio
                                   if printed_ok else area_ratio)
                    local_candidates.append((
                        overlap_ratio, abs(1.0 - score_ratio), candidate, anchor,
                        local_median, printed if printed_ok else None))

                for _, _, candidate, anchor, local_median, printed in sorted(
                        local_candidates, key=lambda item: (item[0], item[1])):
                    if anchor not in missing:
                        continue
                    difference = candidate.difference(recovered_union)
                    parts = list(difference.geoms) if hasattr(difference, "geoms") else [difference]
                    parts = [part for part in parts
                             if part.geom_type == "Polygon" and part.covers(anchor)]
                    if not parts:
                        continue
                    part = max(parts, key=lambda geometry: geometry.area)
                    neighborhood_ok = 0.68 <= part.area / max(local_median, 1.0) <= 1.32
                    printed_ok = bool(printed) and 0.68 <= (
                        part.area / printed) / median_ratio <= 1.32
                    if not neighborhood_ok and not printed_ok:
                        continue
                    part = _clean_lot_polygon(part)
                    recovered.append(part)
                    missing.remove(anchor)
                    recovered_tree = STRtree(recovered)
                    recovered_union = recovered_union.union(part)

    # O raster recupera lotes coloridos que nao foram exportados nas OCGs. A
    # malha global vem por ultimo, apenas para celulas vetoriais isoladas.
    filled_lots = _filled_lot_polygons(page)
    sources = [(0, candidate) for candidate in filled_lots]
    sources.extend((1, candidate) for candidate in global_lots)
    for source, candidate in sorted(sources, key=lambda item: (item[0], item[1].area)):
        hits = [point for point in missing if candidate.contains(point)]
        if len(hits) != 1 or (source == 1 and not _looks_like_lot(candidate)):
            continue
        centered_limit = 0.55 if source == 0 else 0.40
        centered = candidate.centroid.distance(hits[0]) / max(1.0, candidate.area ** 0.5)
        if centered > centered_limit:
            continue
        if any(candidate.intersection(existing).area > 0.75
               for existing in _tree_hits(recovered_tree, recovered, candidate)):
            continue
        recovered.append(_clean_lot_polygon(candidate))
        missing.remove(hits[0])
        recovered_tree = STRtree(recovered)
    return recovered


def _printed_area_points(page):
    """Areas impressas dentro dos lotes: (ponto, metragem)."""
    found = []
    for item in _text_items(page):
        match = AREA_RE.search(item["text"])
        if not match:
            continue
        digits = re.search(r"\d+(?:[,.]\d+)?", match.group(0))
        if not digits:
            continue
        try:
            value = float(digits.group(0).replace(",", "."))
        except ValueError:
            continue
        if value > 0:
            found.append((Point(item["cx"], item["cy"]), value))
    return found


def _area_agreement(lots, printed_areas, tolerance=0.05):
    """Fracao de lotes cuja area vetorial bate com a metragem impressa.

    E a unica medida de qualidade que a propria planta oferece: numa malha
    correta a razao area_vetorial/area_impressa e praticamente constante, porque
    as duas descrevem o mesmo lote em escalas diferentes. Uma face diagonal ou um
    lote fundido com o vizinho quebra essa razao na hora.

    Retorna ``None`` quando nao ha amostra suficiente para julgar.
    """
    if not lots or len(printed_areas) < 20:
        return None
    points = [entry[0] for entry in printed_areas]
    tree = STRtree(points)
    ratios = []
    for poly in lots:
        inside = [printed_areas[index][1]
                  for index in tree.query(poly)
                  if poly.covers(points[int(index)])] if points else []
        if len(inside) == 1 and inside[0] > 0:
            ratios.append(poly.area / inside[0])
    if len(ratios) < 20:
        return None
    median = sorted(ratios)[len(ratios) // 2]
    if median <= 0:
        return None
    good = sum(1 for ratio in ratios if abs(ratio / median - 1.0) <= tolerance)
    return good / len(ratios)


def _label_coverage(lots, label_points):
    """Fracao de rotulos que caiu dentro de exatamente um lote."""
    if not label_points:
        return 0.0
    if not lots:
        return 0.0
    tree = STRtree(lots)
    exact = 0
    for point in label_points:
        hits = [poly for poly in _tree_hits(tree, lots, point) if poly.covers(point)]
        if len(hits) == 1:
            exact += 1
    return exact / len(label_points)


def _rank_lot_candidate(lots, label_points, printed_areas):
    """Nota de um conjunto de lotes: qualidade primeiro, cobertura depois.

    Escolher o motor pela quantidade de poligonos e o que fazia uma malha cheia
    de faces falsas vencer uma malha correta e menor. A metragem impressa e o
    criterio honesto.
    """
    if not lots:
        return (-1.0, 0.0, 0)
    coverage = _label_coverage(lots, label_points)
    agreement = _area_agreement(lots, printed_areas)
    if agreement is None:
        # Sem metragem impressa nao da para julgar a forma; sobra a cobertura.
        return (0.0, coverage, len(lots))
    return (agreement * 0.75 + coverage * 0.25, coverage, len(lots))


def _median_area_ratio(lots, printed_areas):
    """Escala tipica entre area vetorial e metragem impressa nesta planta."""
    if not lots or not printed_areas:
        return None
    points = [entry[0] for entry in printed_areas]
    tree = STRtree(points)
    ratios = []
    for poly in lots:
        inside = [printed_areas[int(index)][1] for index in tree.query(poly)
                  if poly.covers(points[int(index)])]
        if len(inside) == 1 and inside[0] > 0:
            ratios.append(poly.area / inside[0])
    if len(ratios) < 20:
        return None
    return sorted(ratios)[len(ratios) // 2]


def _complete_with_validated_lots(winner, pool, label_points, printed_areas,
                                  tolerance=0.08):
    """Preenche rotulos sem lote usando faces de outros motores, com conferencia.

    O motor vencedor privilegia forma correta, entao alguns lotes ficam de fora.
    Em vez de aceitar qualquer face que cubra o rotulo orfao — que foi como as
    versoes anteriores inflaram o mapa com poligonos errados — cada candidata so
    entra se a metragem impressa dentro dela confirmar o tamanho.
    """
    if not winner or not label_points or not pool:
        return winner

    tree = STRtree(winner)
    missing = [point for point in label_points
               if not any(poly.covers(point)
                          for poly in _tree_hits(tree, winner, point))]
    if not missing:
        return winner

    reference = _median_area_ratio(winner, printed_areas)
    area_points = [entry[0] for entry in printed_areas] if printed_areas else []
    area_tree = STRtree(area_points) if area_points else None

    completed = list(winner)
    completed_tree = STRtree(completed)
    pending = list(missing)

    for candidate in sorted(pool, key=lambda poly: poly.area):
        if not pending:
            break
        hits = [point for point in pending if candidate.covers(point)]
        if len(hits) != 1:
            continue
        # Nao pode invadir um lote ja aceito.
        overlap = max((candidate.intersection(existing).area /
                       max(1.0, min(candidate.area, existing.area))
                       for existing in _tree_hits(completed_tree, completed, candidate)
                       if candidate.intersects(existing)), default=0.0)
        if overlap > 0.10:
            continue
        # Conferencia contra a metragem impressa, quando a planta oferece.
        if reference and area_tree is not None:
            inside = [printed_areas[int(index)][1] for index in area_tree.query(candidate)
                      if candidate.covers(area_points[int(index)])]
            if len(inside) != 1 or inside[0] <= 0:
                continue
            if abs((candidate.area / inside[0]) / reference - 1.0) > tolerance:
                continue
        completed.append(_clean_lot_polygon(candidate))
        completed_tree = STRtree(completed)
        pending.remove(hits[0])
    return completed


def extract_lots(page, area_min, area_max):
    label_points = _lot_label_points(page)
    printed_areas = _printed_area_points(page)

    candidates = []

    def offer(lots):
        if lots:
            candidates.append((_rank_lot_candidate(lots, label_points, printed_areas), lots))

    layered = _layered_lots(page, label_points, area_min, area_max)
    global_lots = _extract_lots_global(page, area_min, area_max, label_points)
    offer(global_lots)
    if layered:
        offer(layered)
        offer(_recover_layered_gaps(page, layered, label_points, area_min, area_max,
                                    global_lots=global_lots))
        legacy_global = _extract_lots_global(
            page, area_min, area_max, label_points, segments=_legacy_segments(page))
        offer(legacy_global)
        offer(_recover_layered_gaps(
            page, layered, label_points, area_min, area_max,
            global_lots=legacy_global))
        legacy_layered = _layered_lots(
            page, label_points, area_min, area_max, curve_steps=8)
        offer(legacy_layered)
        offer(_recover_layered_gaps(
            page, legacy_layered, label_points, area_min, area_max,
            global_lots=legacy_global))
    else:
        offer(_anchor_guided_lots(page, label_points, area_min, area_max))

    if not candidates:
        return global_lots
    candidates.sort(key=lambda entry: entry[0], reverse=True)
    best_score = candidates[0][0][0]
    # Diferencas abaixo de um ponto percentual nao justificam abandonar lotes
    # rotulados. Nesse empate tecnico, a cobertura real da planta prevalece.
    competitive = [entry for entry in candidates
                   if entry[0][0] >= best_score - 0.01]
    competitive.sort(key=lambda entry: (entry[0][1], entry[0][0], entry[0][2]),
                     reverse=True)
    winner = competitive[0][1]

    pool = [poly for _, lots in candidates if lots is not winner for poly in lots]
    return _complete_with_validated_lots(winner, pool, label_points, printed_areas)


LOT_RE = re.compile(r"\bL\s*\d{1,3}[A-Z]?", re.I)
AREA_RE = re.compile(r"\d+(?:[,.]\d+)?\s*m(?:²|2|Â²)", re.I)
# A nomenclatura de quadra muda de loteadora para loteadora: E12, Q195, QD-14,
# Q210C. Fixar um unico formato faz o mapa sair sem quadra nenhuma e com dezenas
# de lotes chamados "L003", indistinguiveis entre si.
QUADRA_RE = re.compile(r"^(?:Q(?:D|U(?:ADRA)?)?[\s.\-]*)?\d{1,4}[A-Z]?$|^E\d{1,3}[A-Z]?$", re.I)
_QUADRA_PREFIX_RE = re.compile(r"^(Q(?:D|U(?:ADRA)?)?|E)[\s.\-]*(\d{1,4}[A-Z]?)$", re.I)
# "Q195 - 34 LOTES" / "QUADRA 12 - 8 LOTES": o gabarito impresso na propria planta.
DECLARED_LOTS_RE = re.compile(
    r"([A-Z]{1,6}[\s.\-]*\d{1,4}[A-Z]?)\s*[-–—]\s*(\d{1,4})\s*LOTES", re.I)


def _normalize_quadra(text):
    """Devolve o identificador de quadra num formato estavel, ou vazio."""
    value = re.sub(r"\s+", "", _clean_text(text)).upper()
    match = _QUADRA_PREFIX_RE.match(value)
    if match:
        return "%s%s" % (match.group(1).upper()[:1] if match.group(1)[:1].upper() != "E" else "E",
                         match.group(2).upper())
    if re.fullmatch(r"\d{1,4}[A-Z]?", value):
        return "Q%s" % value
    return ""


def _quadra_label_items(page, texts=None):
    """Rotulos de quadra da planta, ja normalizados.

    O padrao e detectado por prancha em vez de fixado no codigo. Rotulos com
    prefixo (``Q195``, ``QD-14``, ``E12``) sao inequivocos e tem prioridade.
    Numero solto so vira quadra quando a planta nao usa prefixo em lugar nenhum —
    caso contrario toda cota de medida viraria um rotulo de quadra.
    """
    items = texts if texts is not None else _text_items(page)
    prefixed, bare = [], []
    for item in items:
        raw = re.sub(r"\s+", "", _clean_text(item["text"])).upper()
        if not raw or _is_non_lot_area_text(raw) or _extract_lot_name(raw):
            continue
        if _QUADRA_PREFIX_RE.match(raw):
            prefixed.append(dict(item, quadra=_normalize_quadra(raw)))
        elif re.fullmatch(r"\d{1,4}[A-Z]?", raw):
            bare.append(dict(item, quadra="Q%s" % raw))
    if len(prefixed) >= 3:
        return prefixed
    if not bare:
        return prefixed
    # Rotulo de quadra e desenhado grande. Sem esse corte, cotas de 2 digitos
    # espalhadas pela prancha seriam confundidas com identificador de quadra.
    heights = sorted((item["bbox"][3] - item["bbox"][1]) for item in items)
    cut = heights[int(len(heights) * 0.90)] if heights else 0.0
    return [item for item in bare
            if (item["bbox"][3] - item["bbox"][1]) >= cut]


def declared_lot_counts(page, texts=None):
    """Le "QNNN - NN LOTES": quantos lotes cada quadra deveria ter.

    A planta traz o proprio gabarito. Serve para conferir a extracao em vez de
    confiar que o numero de poligonos encontrados esta certo.
    """
    counts = {}
    for item in (texts if texts is not None else _text_items(page)):
        for name, total in DECLARED_LOTS_RE.findall(item["text"]):
            quadra = _normalize_quadra(name)
            if quadra:
                counts[quadra] = int(total)
    return counts


def _clean_text(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def _text_items(page):
    items = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if _clean_text(s.get("text"))]
            if not spans:
                continue
            text = _clean_text("".join(s.get("text", "") for s in spans))
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            items.append({"text": text, "cx": (x0+x1)/2, "cy": (y0+y1)/2, "bbox": (x0, y0, x1, y1)})
    return items


def _extract_lot_name(text):
    m = LOT_RE.search(text or "")
    if not m:
        return ""
    return re.sub(r"\s+", "", m.group(0)).upper()


def _extract_area(text):
    value = text or ""
    lot_match = LOT_RE.search(value)
    if lot_match:
        value = value[lot_match.end():]
    m = AREA_RE.search(value)
    if not m:
        return ""
    return m.group(0).replace(" ", "").replace("Â²", "²")


def _nearest_quadra(poly, quadras, max_distance=None):
    """Quadra do lote pelo rotulo mais proximo, com raio maximo.

    Sem limite de distancia, um lote na ponta do mapa herda a quadra de outro
    setor so porque nenhum rotulo melhor existe. O raio e derivado do tamanho do
    proprio lote, entao acompanha a escala da prancha.
    """
    if not quadras:
        return ""
    center = poly.centroid
    label = min(quadras,
                key=lambda q: (q["cx"]-center.x)**2 + (q["cy"]-center.y)**2)
    if max_distance is not None:
        distance = math.hypot(label["cx"]-center.x, label["cy"]-center.y)
        if distance > max_distance:
            return ""
    return label.get("quadra") or label["text"].upper()


def _lot_number(name):
    match = re.search(r"\d+", str(name or ""))
    return int(match.group(0)) if match else 0


def _refine_quadra_with_declared(metas, lots, quadras, declared):
    """Corrige a quadra do lote usando a contagem declarada na planta.

    O rotulo mais proximo erra em quadra curva e alongada: o lote da ponta fica
    mais perto do rotulo da quadra vizinha. Mas a planta declara quantos lotes
    cada quadra tem, e a numeracao reinicia em cada uma — entao um lote L022 nao
    pode pertencer a uma quadra de 9 lotes. Essa contradicao e suficiente para
    reatribuir o lote a quadra compativel mais proxima.
    """
    if not declared or not quadras:
        return metas

    counts = {}
    for meta in metas:
        name = meta.get("quadra")
        if name:
            counts[name] = counts.get(name, 0) + 1

    def rename(meta, name):
        meta["quadra"] = name
        if meta.get("lote") and str(meta["lote"]).upper().startswith("L"):
            meta["nome"] = "%s-%s" % (name, meta["lote"])

    # Os lotes mais impossiveis saem primeiro: quanto maior o excesso sobre o
    # limite declarado, mais certo e que a atribuicao original esta errada.
    pending = []
    for meta, poly in zip(metas, lots):
        current = meta.get("quadra")
        limit = declared.get(current)
        number = _lot_number(meta.get("lote"))
        if current and limit and number and number > limit:
            pending.append((number - limit, meta, poly))
    pending.sort(key=lambda entry: -entry[0])

    for _, meta, poly in pending:
        current = meta["quadra"]
        number = _lot_number(meta.get("lote"))
        center = poly.centroid
        ordered = sorted(
            quadras,
            key=lambda q: (q["cx"] - center.x) ** 2 + (q["cy"] - center.y) ** 2)
        fallback = None
        for candidate in ordered:
            name = candidate.get("quadra")
            if not name or name == current:
                continue
            allowed = declared.get(name)
            if allowed is not None and number > allowed:
                continue  # a quadra nao chega a ter esse numero de lote
            if fallback is None:
                fallback = name
            if allowed is not None and counts.get(name, 0) >= allowed:
                continue  # quadra ja lotada segundo a propria planta
            counts[current] = counts.get(current, 1) - 1
            counts[name] = counts.get(name, 0) + 1
            rename(meta, name)
            break
        else:
            if fallback:
                counts[current] = counts.get(current, 1) - 1
                counts[fallback] = counts.get(fallback, 0) + 1
                rename(meta, fallback)
    return metas


def extract_lot_metadata(page, lots):
    """Extrai nome, area e quadra a partir dos textos posicionais do PDF."""
    if not lots:
        return []
    texts = _text_items(page)
    quadras = _quadra_label_items(page, texts)
    # Raio de busca proporcional ao lote: o rotulo da quadra fica junto dela.
    typical = sorted(poly.area for poly in lots)[len(lots) // 2] ** 0.5
    quadra_radius = max(typical * 12.0, 60.0)
    tree = STRtree(lots)
    inside = {i: [] for i in range(len(lots))}
    for item in texts:
        pt = Point(item["cx"], item["cy"])
        for hit in tree.query(pt):
            idx = int(hit) if not hasattr(hit, "contains") else lots.index(hit)
            if lots[idx].contains(pt):
                inside[idx].append(item["text"])

    metas = []
    for i, poly in enumerate(lots):
        lot_name = ""
        area = ""
        for text in inside.get(i, []):
            lot_name = lot_name or _extract_lot_name(text)
            area = area or _extract_area(text)
            if lot_name and area:
                break
        quadra = _nearest_quadra(poly, quadras, max_distance=quadra_radius)
        base_name = lot_name or ("Lote %d" % (i+1))
        metas.append({
            "index": i,
            # O rotulo Lxxx se repete em toda quadra. Sem o prefixo, dezenas de
            # lotes ficam com o mesmo nome e o mapa nao serve para vender.
            "nome": ("%s-%s" % (quadra, base_name)) if quadra and lot_name else base_name,
            "lote": base_name,
            "quadra": quadra,
            "area": area,
            "pdf_area": round(poly.area, 2),
            "extraido": bool(lot_name or area),
        })
    return _refine_quadra_with_declared(metas, lots, quadras,
                                        declared_lot_counts(page, texts))


def _filter_lots_by_area_text(page, lots):
    """Descarta faces CAD que nao batem com a area impressa no lote.

    Quando o PDF traz a medida de cada lote, a relacao entre a area vetorial e a
    area impressa e praticamente constante. Uma face diagonal criada pelo CAD
    nao respeita essa relacao, mesmo que contenha um texto Lxx por acaso.
    """
    if len(lots) < 20:
        return lots
    metas = extract_lot_metadata(page, lots)
    ratios = []
    for poly, meta in zip(lots, metas):
        match = re.search(r"\d+(?:[,.]\d+)?", str(meta.get("area", "")))
        if match:
            printed_area = float(match.group(0).replace(",", "."))
            if printed_area > 0:
                ratios.append(poly.area / printed_area)
    if len(ratios) < max(30, int(len(lots) * 0.60)):
        return lots
    median = sorted(ratios)[len(ratios) // 2]
    if median <= 0:
        return lots
    low, high = median * 0.75, median * 1.25
    kept = []
    for poly, meta in zip(lots, metas):
        match = re.search(r"\d+(?:[,.]\d+)?", str(meta.get("area", "")))
        if not match:
            kept.append(poly)
            continue
        printed_area = float(match.group(0).replace(",", "."))
        ratio = poly.area / printed_area if printed_area else 0
        if low <= ratio <= high:
            kept.append(poly)
    return kept if len(kept) >= int(len(lots) * 0.75) else lots


def render_background(page, scale):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _fit_points_to_canvas(point_sets, W, H):
    """Corrige deslocamentos grandes causados por PDFs com cropbox/form offset."""
    xs = [x for pts in point_sets for x, _ in pts]
    ys = [y for pts in point_sets for _, y in pts]
    if not xs or not ys:
        return 0, 0
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    bw, bh = maxx - minx, maxy - miny
    dx = dy = 0

    if bw > W:
        dx = (W - bw) / 2 - minx
    elif minx < 0:
        dx = -minx
    elif maxx > W:
        dx = W - maxx

    if bh > H:
        dy = (H - bh) / 2 - miny
    elif miny < 0:
        dy = -miny
    elif maxy > H:
        dy = H - maxy

    return dx, dy


def _translate_points(point_sets, dx, dy):
    return [[(round(x+dx, 2), round(y+dy, 2)) for x, y in pts] for pts in point_sets]


def _rotate_points(point_sets, angle, cx, cy):
    if not angle:
        return point_sets
    t = math.radians(angle)
    co, si = math.cos(t), math.sin(t)
    out = []
    for pts in point_sets:
        rpts = []
        for x, y in pts:
            dx, dy = x-cx, y-cy
            rpts.append((round(cx+dx*co-dy*si, 2), round(cy+dx*si+dy*co, 2)))
        out.append(rpts)
    return out


def _bounds(point_sets):
    xs = [x for pts in point_sets for x, _ in pts]
    ys = [y for pts in point_sets for _, y in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _auto_align_points(background, point_sets, max_px=300):
    """Procura um ajuste inicial de angulo/posicao comparando bordas em baixa resolucao."""
    W, H = background.size
    scale = max_px / max(W, H)
    if scale >= 1:
        scale = 1
    w, h = max(1, round(W*scale)), max(1, round(H*scale))
    bg = background.resize((w, h), Image.Resampling.BILINEAR).convert("L")
    edges = bg.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 24 else 0).filter(ImageFilter.MaxFilter(3))
    sx_sets = [[(x*scale, y*scale) for x, y in pts] for pts in point_sets]
    minx, miny, maxx, maxy = _bounds(sx_sets)
    cx, cy = (minx+maxx)/2, (miny+maxy)/2

    def mask_for(angle):
        pts = _rotate_points(sx_sets, angle, cx, cy)
        mask = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(mask)
        for poly in pts:
            if len(poly) > 1:
                dr.line(poly + [poly[0]], fill=255, width=1)
        return mask

    def score(mask, dx, dy):
        shifted = Image.new("L", mask.size, 0)
        shifted.paste(mask, (dx, dy))
        return ImageChops.multiply(shifted, edges).histogram()[255]

    def best_offset(mask, center=(0, 0), radius=60, step=8):
        best = (-1, center[0], center[1])
        cx0, cy0 = center
        for dy in range(cy0-radius, cy0+radius+1, step):
            for dx in range(cx0-radius, cx0+radius+1, step):
                sc = score(mask, dx, dy)
                if sc > best[0]:
                    best = (sc, dx, dy)
        bx, by = best[1], best[2]
        for st in (4, 2, 1):
            improved = True
            while improved:
                improved = False
                for dy in range(by-st*2, by+st*2+1, st):
                    for dx in range(bx-st*2, bx+st*2+1, st):
                        sc = score(mask, dx, dy)
                        if sc > best[0]:
                            best = (sc, dx, dy)
                            bx, by = dx, dy
                            improved = True
        return best

    base_mask = mask_for(0)
    base_score = score(base_mask, 0, 0)
    best = (base_score, 0, 0, 0)
    candidate_angles = []
    for base in (-180, -90, 0, 90, 180):
        for off in (-8, -4, 0, 4, 8):
            candidate_angles.append(base + off)
    candidate_angles = sorted(set(candidate_angles))
    for angle in candidate_angles:
        mask = mask_for(angle)
        sc, dx, dy = best_offset(mask)
        if sc > best[0]:
            best = (sc, angle, dx, dy)
    for angle in [best[1] + i*0.5 for i in range(-4, 5)]:
        mask = mask_for(angle)
        sc, dx, dy = best_offset(mask, (best[2], best[3]), radius=16, step=4)
        if sc > best[0]:
            best = (sc, angle, dx, dy)

    nearest_quadrant = min((-180, -90, 0, 90, 180), key=lambda a: abs(a-best[1]))
    if abs(nearest_quadrant - best[1]) <= 4:
        mask = mask_for(nearest_quadrant)
        snapped = best_offset(mask, (best[2], best[3]), radius=16, step=4)
        if snapped[0] >= best[0] * 0.95:
            best = (snapped[0], nearest_quadrant, snapped[1], snapped[2])

    angle_is_quadrant = abs(abs(best[1]) - 90) <= 8 or abs(abs(best[1]) - 180) <= 8
    min_gain = 1.05 if angle_is_quadrant else 1.35
    if best[0] < max(20, base_score * min_gain):
        return point_sets, {"auto_angle": 0, "auto_dx": 0, "auto_dy": 0, "auto_applied": False}

    _, angle, dx, dy = best
    minx, miny, maxx, maxy = _bounds(point_sets)
    real_cx, real_cy = (minx+maxx)/2, (miny+maxy)/2
    aligned = _rotate_points(point_sets, angle, real_cx, real_cy)
    aligned = _translate_points(aligned, dx/scale, dy/scale)
    return aligned, {"auto_angle": round(angle, 2), "auto_dx": round(dx/scale, 1), "auto_dy": round(dy/scale, 1), "auto_applied": True}


def load_status(path, count):
    if not path:
        return [2 if (i*73) % 100 < 10 else 1 if (i*73) % 100 < 33 else 0 for i in range(count)]
    m = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try: idx = int(row["index"])
            except (KeyError, ValueError): continue
            st = (row.get("status") or "").strip().lower()
            m[idx] = STATUS_NAMES.index(st) if st in STATUS_NAMES else 0
    return [m.get(i, 0) for i in range(count)]


def _normalize_lot(item, index=0):
    if isinstance(item, dict):
        s = int(item.get("s", item.get("status_index", 0)) or 0)
        pts = item.get("pts", item.get("points", ""))
        color = item.get("color") or STATUS_HEX[s if 0 <= s < len(STATUS_HEX) else 0]
        return {
            "s": max(0, min(s, len(STATUS_NAMES)-1)),
            "pts": pts,
            "color": color,
            "nome": item.get("nome") or item.get("name") or ("Lote %d" % (index+1)),
            "quadra": item.get("quadra") or "",
            "area": item.get("area") or "",
            "group": item.get("group") or "",
            "extraido": bool(item.get("extraido", True)),
            "index": int(item.get("index", index) or index),
        }
    s, pts = item[:2]
    s = int(s)
    return {
        "s": max(0, min(s, len(STATUS_NAMES)-1)),
        "pts": pts,
        "color": STATUS_HEX[s if 0 <= s < len(STATUS_HEX) else 0],
        "nome": "Lote %d" % (index+1),
        "quadra": "",
        "area": "",
        "group": "",
        "extraido": False,
        "index": index,
    }


# Ids do editor que somem no modo visualizador. Ficam aqui, e nao espalhados em
# api.py, porque cada id novo do template precisa entrar no bloco de bloqueio:
# as tres copias que existiam em api.py ja divergiam (uma esquecia #canvasStatus,
# outra esquecia #lrot) e o cliente via controles que nao deveria ver.
VIEWER_GUARD_HIDDEN_IDS = ("side", "sideToggle", "sideScrim", "edit", "editor",
                           "draft", "vertices", "canvasStatus", "lrot", "draftBar")


def viewer_guard_html(count_label=None, hidden_ids=None):
    """Bloco unico de CSS+JS que desliga a interface de edicao no modo visualizador.

    Devolve `<style id="shared-viewer">...</style><script>...</script>`, pronto para
    ser injetado antes de `</head>` ou de `</body>` no HTML ja gerado do mapa. O
    script tambem marca `#app` com a classe `shared-viewer` no DOMContentLoaded,
    que e o sinal usado pelo proprio template para nao gravar rascunho local.

    count_label: texto que substitui o contador `#cnt` (ex.: "demonstracao" na
                 pagina publica de demo). `None` mantem o contador do editor.
    hidden_ids:  sobrescreve a lista de ids escondidos; o padrao e
                 VIEWER_GUARD_HIDDEN_IDS e cobre todas as variantes antigas.
    """
    ids = tuple(hidden_ids) if hidden_ids is not None else VIEWER_GUARD_HIDDEN_IDS
    selector = ",".join("#" + str(item).lstrip("#") for item in ids)
    guard = ('<style id="shared-viewer">%s{display:none!important}'
             '#lots{pointer-events:none!important}.lot{cursor:default!important}</style>'
             '<script>window.addEventListener(\'DOMContentLoaded\',function(){'
             'var app=document.getElementById(\'app\');if(app)app.classList.add(\'shared-viewer\');' % selector)
    if count_label is not None:
        guard += ("var count=document.getElementById('cnt');if(count)count.textContent=%s;"
                  % json.dumps(str(count_label)))
    return guard + "});</script>"


def build_html(b64, W, H, data, title="Mapa NexoLote", img_mime="image/jpeg",
               opacity=DEFAULT_OPACITY, stroke_width=DEFAULT_STROKE_WIDTH,
               label_mode=DEFAULT_LABEL_MODE):
    data = [_normalize_lot(item, i) for i, item in enumerate(data)]
    img_mime = img_mime or "image/jpeg"
    opacity = _clamp_float(opacity, DEFAULT_OPACITY, 0.20, 1.0)
    stroke_width = _clamp_float(stroke_width, DEFAULT_STROKE_WIDTH, 0.20, 2.5)
    label_mode = _clean_label_mode(label_mode)
    n = [0, 0, 0]
    for item in data:
        n[item["s"]] += 1
    return (HTML_TEMPLATE.replace("__W__", str(W)).replace("__H__", str(H)).replace("__IMG__", b64)
            .replace("__IMG_MIME__", img_mime).replace("__IMG_MIME_JSON__", json.dumps(img_mime))
            .replace("__OPACITY__", ("%.2f" % opacity)).replace("__OPACITY_PERCENT__", str(round(opacity * 100)))
            .replace("__STROKE__", ("%.2f" % stroke_width)).replace("__LABEL_MODE__", json.dumps(label_mode))
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))).replace("__TITLE__", title)
            .replace("__NLOTS__", str(len(data))).replace("__N0__", str(n[0]))
            .replace("__N1__", str(n[1])).replace("__N2__", str(n[2]))
            # Marca de quando este HTML foi gerado (epoch ms). O editor so oferece
            # restaurar o rascunho local se ele for mais novo que este numero.
            .replace("__GENERATED_AT__", str(int(time.time() * 1000))))


def convert(pdf_path, out_html, page_index=0, max_px=None, rotate="auto",
            area_min=800, area_max=9000, status_csv=None, geojson_out=None,
            snapshot_out=None, title="Mapa NexoLote", quality="balanced",
            opacity=DEFAULT_OPACITY, stroke_width=DEFAULT_STROKE_WIDTH,
            label_mode=DEFAULT_LABEL_MODE):
    """Fundo do PDF estatico; os lotes entram como camada vetorial editavel."""
    doc = pymupdf.open(pdf_path); page = doc[page_index]
    quality_info = _quality_settings(quality)
    effective_max_px = int(max_px or quality_info["max_px"])
    opacity = _clamp_float(opacity, DEFAULT_OPACITY, 0.20, 1.0)
    stroke_width = _clamp_float(stroke_width, DEFAULT_STROKE_WIDTH, 0.20, 2.5)
    label_mode = _clean_label_mode(label_mode)
    scale = effective_max_px / max(page.rect.width, page.rect.height)
    lots = extract_lots(page, area_min, area_max)
    if not lots:
        has_vector_content = bool(_segments(page) or _text_items(page))
        if not has_vector_content:
            raise MapConversionError(
                "Este PDF e uma imagem rasterizada, sem linhas ou textos vetoriais extraiveis. "
                "O mapeamento automatico precisa do PDF original exportado do CAD, com as divisas dos lotes em vetor."
            )
        raise MapConversionError("Nenhum lote encontrado. Ajuste os limites de area ou envie o PDF original do CAD.")
    metas = extract_lot_metadata(page, lots)
    bg = render_background(page, scale); W0, H0 = bg.size
    mask = bg.convert("L").point(lambda v: 255 if v < 245 else 0)
    bbox = mask.getbbox() or (0, 0, W0, H0)
    pad = 20
    L = max(0, bbox[0]-pad); T = max(0, bbox[1]-pad)
    R = min(W0, bbox[2]+pad); B = min(H0, bbox[3]+pad)
    crop = bg.crop((L, T, R, B)); W, H = crop.size
    statuses = load_status(status_csv, len(lots))
    data, geo, point_sets = [], [], []
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)) if snapshot_out else None
    dr = ImageDraw.Draw(ov) if ov is not None else None
    ox, oy = page.rect.x0, page.rect.y0
    for poly in lots:
        xs, ys = poly.exterior.coords.xy
        point_sets.append([(round((x-ox)*scale - L, 2), round((y-oy)*scale - T, 2))
                           for x, y in zip(xs, ys)])
    dx, dy = _fit_points_to_canvas(point_sets, W, H)
    point_sets = _translate_points(point_sets, dx, dy)
    align_info = {"fit_dx": round(dx, 1), "fit_dy": round(dy, 1)}
    if str(rotate).strip().lower() == "auto":
        point_sets, auto_info = _auto_align_points(crop, point_sets)
        align_info.update(auto_info)
    else:
        try:
            angle = float(rotate)
        except (TypeError, ValueError):
            angle = 0
        if angle:
            minx, miny, maxx, maxy = _bounds(point_sets)
            point_sets = _rotate_points(point_sets, angle, (minx+maxx)/2, (miny+maxy)/2)
            fdx, fdy = _fit_points_to_canvas(point_sets, W, H)
            point_sets = _translate_points(point_sets, fdx, fdy)
            align_info.update({"manual_angle": angle, "manual_dx": round(fdx, 1), "manual_dy": round(fdy, 1)})
    point_sets = [_clean_point_set(pts) for pts in point_sets]
    for i, poly in enumerate(lots):
        s = statuses[i]
        pts = point_sets[i]
        meta = dict(metas[i]) if i < len(metas) else {"index": i, "nome": "Lote %d" % (i+1), "quadra": "", "area": "", "extraido": False}
        meta.update({"s": s, "status": STATUS_NAMES[s], "color": STATUS_HEX[s],
                     "pts": " ".join("%g,%g" % (p[0], p[1]) for p in pts)})
        data.append(meta)
        col = STATUS_FILL[s]
        if dr is not None:
            dr.polygon(pts, fill=col+(int(opacity * 255),), outline=(20, 25, 22, 220))
        if geojson_out:
            props = {k: meta.get(k) for k in ("index", "nome", "quadra", "area", "extraido", "status", "color")}
            geo.append({"type": "Feature", "properties": props,
                        "geometry": {"type": "Polygon", "coordinates": [[[p[0], p[1]] for p in pts]]}})
    b64, img_mime = _encode_background(crop, quality_info)
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(build_html(b64, W, H, data, title, img_mime, opacity, stroke_width, label_mode))
    if snapshot_out and ov is not None:
        Image.alpha_composite(crop.convert("RGBA"), ov).convert("RGB").save(snapshot_out)
    if geojson_out:
        with open(geojson_out, "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": geo}, fh)
    n = [0, 0, 0]
    for item in data: n[item["s"]] += 1
    # "data" carrega os lotes em si. Sem essa chave o worker da fila grava zero
    # lotes no banco em toda conversao (app_v1/worker.py:extract_lots_from_info)
    # e a validacao assina laudo verde sobre lista vazia.
    return {"lotes": len(data), "data": data,
            "modo": "fundo estatico + lotes editaveis", "tamanho_px": [W, H],
            "alinhamento": align_info,
            "imagem": {"quality": quality_info["name"], "mime": img_mime, "max_px": effective_max_px},
            "estilo": {"opacity": opacity, "stroke_width": stroke_width, "label_mode": label_mode},
            "status": {STATUS_NAMES[i]: n[i] for i in range(3)},
            "metadados": {"com_texto": sum(1 for item in data if item.get("extraido"))},
            "saida": out_html}


# ---------------------------------------------------------------------------
# O editor vive em templates/editor/ (html, css e js separados) em vez de uma
# unica string de 77 KB dentro deste arquivo. Assim ele pode ser lido, revisado
# e passado por lint como codigo de verdade. A saida continua sendo um HTML
# unico e autossuficiente: os pedacos sao costurados aqui na geracao.
# ---------------------------------------------------------------------------
EDITOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "editor")


def _read_editor_part(nome):
    with open(os.path.join(EDITOR_DIR, nome), encoding="utf-8") as arquivo:
        return arquivo.read().rstrip("\n")


def _editor_scripts():
    """editor.js e os modulos editor-*.js, na ordem em que devem ser lidos.

    Cada bloco novo do editor (geometria, transformacao, selecao) vive no seu
    proprio arquivo. Todos entram no mesmo <script>, em ordem alfabetica depois
    do nucleo: o HTML gerado precisa continuar sendo um arquivo unico e sem CDN.
    """
    extras = sorted(nome for nome in os.listdir(EDITOR_DIR)
                    if nome.startswith("editor-") and nome.endswith(".js"))
    return "\n".join(_read_editor_part(nome) for nome in ["editor.js"] + extras)


def _build_html_template():
    return (
        '<!doctype html><html lang="pt-br"><head>\n<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=4,user-scalable=yes">\n<title>__TITLE__</title><link rel="icon" href="data:,">\n'
        "<style>\n" + _read_editor_part("editor.css") + "\n</style></head><body>\n"
        + _read_editor_part("editor.html")
        + "\n<script>\n" + _editor_scripts()
        + "\n</script></body></html>"
    )


HTML_TEMPLATE = _build_html_template()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PDF de loteamento (CAD) -> mapa interativo (HTML).")
    ap.add_argument("pdf"); ap.add_argument("-o", "--out", default="mapa.html")
    ap.add_argument("--page", type=int, default=0); ap.add_argument("--max-px", type=int, default=None)
    ap.add_argument("--rotate", default="auto"); ap.add_argument("--area-min", type=float, default=800)
    ap.add_argument("--area-max", type=float, default=9000); ap.add_argument("--status-csv", default=None)
    ap.add_argument("--geojson", default=None); ap.add_argument("--snapshot", default=None)
    ap.add_argument("--quality", choices=sorted(QUALITY_PRESETS), default="balanced")
    ap.add_argument("--opacity", type=float, default=DEFAULT_OPACITY)
    ap.add_argument("--stroke-width", type=float, default=DEFAULT_STROKE_WIDTH)
    ap.add_argument("--label-mode", choices=["auto", "always", "hidden"], default=DEFAULT_LABEL_MODE)
    ap.add_argument("--title", default="Mapa NexoLote")
    a = ap.parse_args()
    info = convert(a.pdf, a.out, page_index=a.page, max_px=a.max_px,
                   rotate=a.rotate, area_min=a.area_min, area_max=a.area_max,
                   status_csv=a.status_csv, geojson_out=a.geojson,
                   snapshot_out=a.snapshot, title=a.title, quality=a.quality,
                   opacity=a.opacity, stroke_width=a.stroke_width,
                   label_mode=a.label_mode)
    # A lista de lotes vai no retorno para quem chama como biblioteca; no
    # terminal ela seriam centenas de milhares de caracteres de poligono.
    resumo = {chave: valor for chave, valor in info.items() if chave != "data"}
    print("OK ->", json.dumps(resumo, ensure_ascii=False))

