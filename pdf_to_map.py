#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_to_map.py — PDF de loteamento (CAD) -> mapa interativo (HTML).
Inclui um modo EDITAR: desenhar os lotes que faltam por cima do mapa.
100% deterministico. Nao usa IA.  Deps: python -m pip install -r requirements.txt
"""
import argparse, base64, csv, io, json, math, re, sys, unicodedata
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
            .replace("__N1__", str(n[1])).replace("__N2__", str(n[2])))


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


HTML_TEMPLATE = r'''<!doctype html><html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=4,user-scalable=yes">
<title>__TITLE__</title><link rel="icon" href="data:,">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%;background:#15171a;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#eee;overflow:hidden}
  #app{position:fixed;inset:0;--lot-opacity:__OPACITY__;--lot-stroke:__STROKE__px}
  #map{width:100%;height:100%;display:block;touch-action:none;background:#fff;cursor:grab}
  #map.draw{cursor:crosshair}#map.move-lots{cursor:move}#map.vertex-edit{cursor:default}
  .lot{stroke:rgba(10,14,18,.68);stroke-width:var(--lot-stroke);vector-effect:non-scaling-stroke;fill-opacity:var(--lot-opacity);cursor:pointer;transition:fill-opacity .1s,stroke-width .1s}
  .lot:hover{fill-opacity:.86}.lot.sel{stroke:#05070a;stroke-width:calc(var(--lot-stroke) + 1.1px)}
  .lotlabel{font-size:7px;font-weight:650;text-anchor:middle;dominant-baseline:middle;fill:rgba(13,17,20,.78);vector-effect:non-scaling-stroke;pointer-events:none}
  .draftpt{fill:#36d889;stroke:#fff;stroke-width:1;vector-effect:non-scaling-stroke}.draftline{fill:none;stroke:#36d889;stroke-width:1.5;stroke-dasharray:4 3;vector-effect:non-scaling-stroke}.vertexpt{fill:#f7faf8;stroke:#087d4b;stroke-width:2;vector-effect:non-scaling-stroke;cursor:move}.selectbox{fill:#36d889;fill-opacity:.12;stroke:#16965d;stroke-width:1;stroke-dasharray:5 3;pointer-events:none}
  .panel{position:absolute;background:rgba(28,30,34,.94);border:1px solid #383b40;border-radius:12px;padding:8px 11px;backdrop-filter:blur(6px)}
  #title{top:12px;left:12px;font-weight:700;font-size:14px}#title small{display:block;font-weight:400;color:#a9aab0;font-size:11.5px;margin-top:2px}
  #legend{bottom:12px;left:12px;font-size:12.5px;line-height:1.9}#legend .row{display:flex;align-items:center;gap:8px}#legend i{width:13px;height:13px;border-radius:3px;display:inline-block}
  #zoom{top:12px;right:12px;display:flex;flex-direction:column;gap:6px;background:none;border:none;padding:0}
  #zoom button{width:38px;height:38px;border-radius:10px;border:1px solid #383b40;background:rgba(28,30,34,.92);color:#eee;font-size:19px;cursor:pointer}
  #edit{top:10px;left:calc(50% + 180px);transform:translateX(-50%);display:flex;align-items:center;gap:6px;justify-content:center;max-width:calc(100vw - 400px);padding:6px;border-radius:8px}
  #edit button{background:#1f242c;color:#eee;border:1px solid #2c313a;border-radius:6px;padding:7px 9px;font-size:12px;cursor:pointer;white-space:nowrap}
  #edit button.on{background:#26d07c;color:#06281a;border-color:#26d07c;font-weight:700}#edit .st{width:30px;padding-inline:6px;font-size:15px}#edit .st.on{background:#26313a!important;color:inherit!important;border-color:#eef8f2!important;box-shadow:inset 0 0 0 1px #eef8f2}
  #edit button:disabled,.editBtns button:disabled{opacity:.38;cursor:not-allowed}.toolset{display:flex;align-items:center;gap:4px}.toolset+.toolset{border-left:1px solid #39434c;padding-left:6px}.selectionSummary{color:#b9c3ca;font-size:11px;min-width:72px;text-align:center;white-space:nowrap}.selectionSummary.active{color:#e9fff4}.kbdIcon{font-size:15px;line-height:0;vertical-align:-1px;margin-right:4px}
  #info{bottom:12px;right:12px;min-width:140px;display:none}#info .h{font-weight:700;font-size:14px}
  #lrot{bottom:12px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:6px;font-size:12.5px;flex-wrap:wrap;justify-content:center;max-width:96vw}#lrot input[type=range]{width:160px;max-width:34vw;accent-color:#1b6cf0}#lrot button{background:#1f242c;color:#eee;border:1px solid #2c313a;border-radius:8px;padding:5px 9px;font-size:12px;cursor:pointer;min-width:30px}#lrot button.on{background:#1b6cf0;color:#fff;border-color:#1b6cf0}#lrot b{min-width:44px;text-align:right;font-variant-numeric:tabular-nums}#lrot .sep{width:1px;height:22px;background:#333;margin:0 1px}#lrot .xy{min-width:86px;color:#a9aab0;text-align:center;font-variant-numeric:tabular-nums}
  #side{position:absolute;left:0;top:0;bottom:0;width:340px;background:#171a20;border-right:1px solid #363a41;z-index:5;display:flex;flex-direction:column;box-shadow:18px 0 35px rgba(0,0,0,.22);transition:transform .18s ease}
  #side.closed{transform:translateX(-340px)}#sideToggle{position:absolute;left:352px;top:72px;z-index:6;width:38px;height:38px;border-radius:10px;border:1px solid #383b40;background:rgba(28,30,34,.94);color:#eee;cursor:pointer}#side.closed+#sideToggle{left:12px}
  .shead{padding:14px;border-bottom:1px solid #33373e}.shead h2{font-size:15px;line-height:1.25;margin-bottom:3px}.shead p{font-size:12px;color:#a9aab0}.sactions{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}.sactions button,.filter button{background:#232832;color:#e8e8ea;border:1px solid #363c46;border-radius:6px;padding:7px 8px;font-size:11.5px;cursor:pointer}
  #lotSearch{width:100%;margin-top:12px;background:#101216;border:1px solid #343944;border-radius:9px;color:#f2f2f2;padding:9px 10px;font-size:13px}.filter{display:flex;gap:6px;margin-top:9px;flex-wrap:wrap}.filter button.on{border-color:#26d07c;color:#dffbea;background:#143020}
  .palette{display:grid;gap:8px;padding:12px 14px;border-bottom:1px solid #33373e}.palrow{display:grid;grid-template-columns:18px 1fr 72px;align-items:center;gap:8px;font-size:12px;color:#d9dadd}.palrow input{width:100%;height:28px;background:#101216;border:1px solid #343944;border-radius:7px;padding:2px}
  .mapstyle{display:grid;gap:9px;padding:12px 14px;border-bottom:1px solid #33373e}.styleRow{display:grid;grid-template-columns:108px 1fr;align-items:center;gap:10px;font-size:12px;color:#d9dadd}.styleRow span{display:flex;align-items:center;justify-content:space-between;gap:8px}.styleRow b{font-variant-numeric:tabular-nums;color:#eef0f3;font-size:11px}.styleRow input[type=range]{width:100%;accent-color:#1b6cf0}.styleRow select{background:#101216;border:1px solid #343944;border-radius:8px;color:#f0f0f2;padding:7px 8px;font-size:12px}
  #lotList{flex:1;overflow:auto;padding:8px}.lotrow{width:calc(100% - 16px);display:grid;grid-template-columns:16px minmax(0,1fr) auto;gap:9px;align-items:center;text-align:left;background:transparent;border:1px solid transparent;border-radius:8px;color:#ececef;padding:7px 8px;cursor:pointer;position:absolute;left:8px;right:8px}.lotrow:hover{background:#22262e}.lotrow.on{background:#27313c;border-color:#52606f}.sw{width:12px;height:12px;border-radius:3px;border:1px solid rgba(255,255,255,.35)}.lt{display:block;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.lm{display:block;font-size:11px;color:#a9aab0;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tag{font-size:10.5px;color:#b8bbc2;background:#2b3038;border-radius:6px;padding:2px 5px}
  #editor{border-top:1px solid #33373e;padding:12px 14px;background:#181b20;max-height:44vh;overflow:auto}.empty{font-size:12px;color:#8f929a;line-height:1.45}.selectionHead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.selectionHead strong{font-size:13px}.groupBadge{font-size:10.5px;color:#b9c5cd;background:#29323a;border:1px solid #3d4b56;border-radius:5px;padding:3px 6px}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.field{display:flex;flex-direction:column;gap:4px;font-size:11px;color:#a9aab0}.field input,.field select{background:#101216;border:1px solid #343944;border-radius:6px;color:#f0f0f2;padding:7px 8px;font-size:12.5px;min-width:0}.field input[type=color]{height:34px;padding:2px}.field.full{grid-column:1/-1}.editBtns{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:9px}.editBtns button{background:#232832;color:#e8e8ea;border:1px solid #363c46;border-radius:6px;padding:7px 8px;font-size:11.5px;cursor:pointer}.editBtns button.primary{background:#26d07c;color:#06281a;border-color:#26d07c;font-weight:700}.editBtns button.danger{color:#ffb4a4}.nudgeRow{display:grid;grid-template-columns:1fr auto;align-items:center;gap:8px;margin-top:8px}.nudgeRow span{font-size:11px;color:#9faab2}.nudgeGrid{display:grid;grid-template-columns:repeat(4,30px);gap:4px}.nudgeGrid button{height:28px;border-radius:5px;border:1px solid #3b4752;background:#232832;color:#e8e8ea;cursor:pointer}
  #toast{position:absolute;right:16px;bottom:72px;z-index:10;max-width:320px;background:#111820;color:#eef7f2;border:1px solid #3c4a54;border-left:3px solid #36d889;border-radius:6px;padding:10px 12px;font-size:12px;box-shadow:0 14px 34px rgba(0,0,0,.28);opacity:0;transform:translateY(8px);pointer-events:none;transition:opacity .18s ease,transform .18s ease}#toast.show{opacity:1;transform:none}#toast.error{border-left-color:#e0613b}
  @media(max-width:760px){#side{width:86vw}#side.closed{transform:translateX(-86vw)}#sideToggle{left:calc(86vw + 12px);top:68px}#edit{left:auto;right:12px;transform:none;max-width:calc(100vw - 74px)}}
  [hidden]{display:none!important}
  :root{color-scheme:dark}body{font-family:"Segoe UI Variable","Aptos","Trebuchet MS",system-ui,sans-serif;font-variant-numeric:tabular-nums}
  button,input,select{transition:border-color .18s ease,background-color .18s ease,box-shadow .18s ease,transform .12s ease}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #36d889;outline-offset:2px}
  .panel{box-shadow:0 12px 32px rgba(5,9,13,.24);border-color:#3a4651}.panel button:hover{background:#2a333d;border-color:#4c5a66}.panel button:active{transform:translateY(1px)}
  #side{width:360px;background:#141a20;border-right-color:#303b45;box-shadow:18px 0 38px rgba(0,0,0,.28)}#side.closed{transform:translateX(-360px)}#sideToggle{left:372px;background:#1b232b;border-color:#43505c;box-shadow:0 10px 24px rgba(0,0,0,.24)}#side.closed+#sideToggle{left:12px}
  .shead{padding:16px;border-bottom-color:#303b45}.shead h2{font-size:16px;letter-spacing:-.01em}.shead p{color:#aab5bd}.sactions button,.filter button,.editBtns button{border-color:#3b4752}.sactions button:hover,.filter button:hover,.editBtns button:hover{background:#2a333d;border-color:#52616d}.filter button.on{background:#143524;border-color:#36d889;color:#dcf9e9}
  #lotSearch{background:#0f1419;border-color:#3b4752;padding:10px 11px}#lotSearch:focus{box-shadow:0 0 0 3px rgba(54,216,137,.12)}
  .palette,.mapstyle{padding:14px 16px;border-bottom-color:#303b45}.styleRow{grid-template-columns:112px 1fr}.styleRow input[type=range]{accent-color:#36d889}.styleRow select,.field input,.field select{border-color:#3b4752}.styleRow select:hover,.field input:hover,.field select:hover{border-color:#52616d}
  #lotList{padding:8px 8px 12px}.lotrow{border-radius:7px}.lotrow:hover{background:#222c35}.lotrow.on{background:#1c3a2c;border-color:#36d889}
  #title{max-width:min(320px,calc(100vw - 120px));line-height:1.25}#title small{color:#aab5bd}
  #zoom button{background:#1b232b;border-color:#43505c}#zoom button:hover{background:#29343d;border-color:#60707d}
  #edit{background:rgba(22,28,34,.97);border-radius:8px;box-shadow:0 14px 38px rgba(4,10,14,.3)}#edit button.on{background:#36d889;border-color:#36d889;color:#06251a}#edit #edt.on{background:#183528;color:#dff8ea;border-color:#36d889;box-shadow:inset 3px 0 0 #36d889}#lrot{left:calc(50% + 180px);background:rgba(22,28,34,.96);border-radius:8px}#lrot input[type=range]{accent-color:#36d889}#app.side-closed #edit,#app.side-closed #lrot{left:50%}
  .sectionLabel{display:flex;align-items:center;justify-content:space-between;color:#7f8e97;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em}.palette,.mapstyle{position:relative}.palette .sectionLabel,.mapstyle .sectionLabel{margin-bottom:2px}.sideScrim{display:none;position:absolute;inset:0;z-index:4;background:rgba(5,9,12,.46);opacity:0;pointer-events:none;transition:opacity .18s ease}#sideToggle{font-size:0}#sideToggle:before{content:"\2630";font-size:17px}#sideToggle[aria-expanded="true"]:before{content:"\00d7";font-size:22px}.shortcut{display:inline-grid;place-items:center;min-width:18px;height:18px;margin-left:5px;border:1px solid #485560;border-radius:4px;color:#98a6ae;font:10px/1 ui-monospace,SFMono-Regular,Consolas,monospace}.empty{display:flex;align-items:center;min-height:46px}.empty:before{content:"\25a1";margin-right:8px;color:#60707b;font-size:17px}.editBtns button,.nudgeGrid button{min-height:30px}.resultCount{font-weight:700;color:#e8f2ed}
  /* Workspace cartografico: navegacao, visual e alinhamento ficam separados. */
  #side{width:320px;box-shadow:14px 0 32px rgba(0,0,0,.24)}#side.closed{transform:translateX(-320px)}#sideToggle{left:332px}.sideHeader{padding:15px 16px 12px;border-bottom:1px solid #303b45}.sideHeader strong{display:block;max-width:255px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.sideHeader span{display:block;margin-top:3px;color:#8f9da5;font-size:10.5px}.sideTabs{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;padding:8px;border-bottom:1px solid #303b45;background:#11171c}.sideTab{height:34px;border:1px solid transparent;border-radius:6px;background:transparent;color:#94a2aa;font-size:11px;cursor:pointer}.sideTab:hover{background:#202a31;color:#e7efec}.sideTab.on{border-color:#40505b;background:#202a31;color:#f0f6f3;box-shadow:inset 0 -2px 0 #36d889}.sidePanel{display:flex;min-height:0;flex:1;flex-direction:column}.sidePanel[hidden]{display:none!important}.sidePanel .shead{padding:12px 12px 10px}.sidePanel #lotSearch{margin-top:0}.sidePanel .filter{margin-top:8px}.sidePanel .sactions{margin-top:8px}.sidePanel .palette,.sidePanel .mapstyle{border-bottom:1px solid #303b45}.visualBody,.alignBody{flex:1;overflow:auto}.statusSummary{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:12px 14px}.statusMetric{padding:9px 7px;border:1px solid #303b45;border-radius:6px;background:#11171c}.statusMetric i{display:block;width:8px;height:8px;margin-bottom:7px;border-radius:2px}.statusMetric b{display:block;font-size:14px}.statusMetric span{display:block;margin-top:2px;color:#89969e;font-size:9.5px}.alignBody{padding:14px}.alignGroup{padding:14px 0;border-bottom:1px solid #303b45}.alignGroup:first-child{padding-top:0}.alignGroup:last-child{border-bottom:0}.alignGroup .sectionLabel{margin-bottom:10px}.alignAngle{display:grid;grid-template-columns:32px 1fr 32px;gap:7px;align-items:center}.alignAngle input{width:100%;accent-color:#36d889}.alignAngle button,.alignNudge button,.alignActions button{height:32px;border:1px solid #3b4752;border-radius:6px;background:#202830;color:#e7eeee;cursor:pointer}.alignValue{display:flex;align-items:center;justify-content:space-between;margin-top:8px;color:#9ba8af;font-size:11px}.alignValue b{color:#edf4f1}.alignNudge{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.alignPosition{margin-top:8px;color:#96a3ab;font-size:11px;text-align:center}.alignActions{display:grid;grid-template-columns:1fr 1fr;gap:7px}.alignActions button.on{border-color:#36d889;background:#173526;color:#ddf8e9}
  #title,#legend,#info{display:none!important}#lrot{position:static;display:block;max-width:none;padding:0;border:0;border-radius:0;background:none;box-shadow:none;transform:none}#lrot .sep{display:none}
  #editor{position:absolute;z-index:7;top:66px;right:12px;width:304px;max-height:calc(100vh - 84px);overflow:auto;padding:0;border:1px solid #3a4651;border-radius:8px;background:#171e24;box-shadow:0 20px 50px rgba(4,9,13,.3);opacity:0;pointer-events:none;transform:translateX(12px);transition:opacity .16s ease,transform .16s ease}#editor.show{opacity:1;pointer-events:auto;transform:none}#editor .empty{display:none}.selectionHead{position:sticky;top:0;z-index:1;margin:0;padding:13px 14px 10px;border-bottom:1px solid #303b45;background:#171e24}.selectionHead strong{font-size:14px}.selectionHeadActions{display:flex;align-items:center;gap:6px}.inspectorClose{width:28px;height:28px;border:1px solid #3b4752;border-radius:5px;background:#202830;color:#dfe8e4;cursor:pointer}.groupBadge{white-space:nowrap}.formgrid{padding:13px 14px 4px}.editBtns{padding:7px 14px 0;margin:0}.nudgeRow{padding:10px 14px 14px;margin:0}.inspectorSection{padding:0 14px;color:#809099;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:.07em}
  #edit{left:calc(50% + 160px);max-width:calc(100vw - 368px)}#lrot{left:auto}#app.side-closed #edit{left:50%}.selectionSummary{min-width:58px}.contextGroup{display:none}
  @media(max-width:1180px){#edit{max-width:calc(100vw - 96px)}#edit .toolLabel{display:none}.kbdIcon{margin-right:0}.selectionSummary{display:none}}
  @media(max-width:760px){#side{width:min(92vw,340px)}#side.closed{transform:translateX(-100%)}.sideScrim{display:block}#app:not(.side-closed) .sideScrim{opacity:1;pointer-events:auto}#sideToggle{left:calc(min(92vw,340px) - 50px);top:12px;z-index:8}#side.closed+#sideToggle{left:12px}#zoom{top:60px;right:12px}#edit,#app.side-closed #edit{top:10px;right:12px;left:auto;transform:none;max-width:calc(100vw - 78px);overflow-x:auto;justify-content:flex-start;scrollbar-width:none}#edit::-webkit-scrollbar{display:none}#app:not(.side-closed) #zoom,#app:not(.side-closed) #edit{visibility:hidden;pointer-events:none}#editor{top:auto;left:8px;right:8px;bottom:8px;width:auto;max-height:48vh;transform:translateY(12px)}#editor.show{transform:none}.sactions{grid-template-columns:repeat(3,1fr)}}
  /* Minimal editor polish: Figma-style canvas, compact tools and contextual inspector. */
  html,body{background:#0b1014;color:#e7edf0}
  #app{background:#eef1ef}
  #map{background:#f7f8f6}
  #side{width:312px;background:#0f151a;border-right:1px solid #26313a;box-shadow:10px 0 28px rgba(4,9,13,.22)}
  #side.closed{transform:translateX(-312px)}#sideToggle{left:324px;top:18px;width:34px;height:34px;border-radius:8px;background:#111922;border-color:#2b3842;box-shadow:0 12px 30px rgba(3,8,12,.22)}#side.closed+#sideToggle{left:16px}
  .sideHeader{padding:14px 14px 10px;background:#0f151a}.sideHeader strong{font-size:13px;font-weight:650}.sideHeader span{font-size:10px;color:#91a0a8}
  .sideTabs{padding:7px;background:#0b1116}.sideTab{height:32px;border-radius:7px;font-weight:600}.sideTab.on{background:#172129;border-color:#33434f;color:#f4faf7;box-shadow:inset 0 -2px 0 #36d889}
  .shead{padding:12px}.filter{gap:5px}.filter button,.sactions button,.editBtns button,.alignAngle button,.alignNudge button,.alignActions button{border-radius:7px;background:#161f27;border-color:#2c3943;color:#dbe5e7}.filter button.on{background:#113321;border-color:#36d889;color:#dff8ea}
  #lotSearch{height:38px;margin-top:0;border-radius:8px;background:#0b1116;border-color:#2c3943;color:#eef5f1}
  #lotList{padding:7px}.lotrow{width:calc(100% - 14px);left:7px;right:7px;border-radius:7px;padding:6px 7px}.lotrow:hover{background:#172129}.lotrow.on{background:#153524;border-color:#36d889}.lt{font-size:12px;font-weight:650}.lm{font-size:10.5px}.tag{border-radius:5px;background:#212b34;color:#aebbc2}
  .palette,.mapstyle{padding:13px;border-bottom-color:#26313a}.styleRow{grid-template-columns:104px 1fr}.styleRow select,.field input,.field select{height:34px;border-radius:7px;background:#0b1116;border-color:#2c3943}
  #edit{top:14px;left:calc(50% + 156px);max-width:calc(100vw - 380px);padding:5px;border:1px solid rgba(35,47,57,.72);border-radius:9px;background:rgba(12,18,24,.92);box-shadow:0 18px 50px rgba(3,8,12,.28);backdrop-filter:blur(14px)}
  #app.side-closed #edit{left:50%;max-width:calc(100vw - 120px)}
  #edit button{height:32px;border-radius:7px;border-color:transparent;background:transparent;color:#dce6e8;padding:0 9px;font-weight:650}
  #edit button:hover{background:#1a252e;border-color:#2c3943}#edit button.on{background:#36d889;color:#052419;border-color:#36d889}#edit #edt{border-color:#2c3943;background:#131c23}#edit #edt.on{background:#113321;color:#dff8ea;border-color:#36d889;box-shadow:none}
  .toolset+.toolset{border-left:1px solid #26313a;padding-left:5px}.kbdIcon{opacity:.86}.selectionSummary{min-width:72px;color:#9facb4}.selectionSummary.active{color:#dff8ea}
  #eddl{background:#36d889!important;border-color:#36d889!important;color:#052419!important}
  #zoom{top:16px;right:16px;gap:5px}#zoom button{width:34px;height:34px;border-radius:8px;background:#111922;border-color:#2b3842;box-shadow:0 10px 24px rgba(3,8,12,.18)}
  #editor{top:64px;right:16px;width:316px;max-height:calc(100vh - 86px);border-radius:9px;background:#101820;border-color:#2b3842;box-shadow:0 22px 60px rgba(3,8,12,.3)}
  .selectionHead{padding:12px 13px 10px;background:#101820;border-bottom-color:#26313a}.selectionHead strong{font-weight:650}.inspectorClose{border-radius:7px;background:#151f27;border-color:#2c3943}.inspectorSection{padding:0 13px;color:#80909a}.formgrid{padding:12px 13px 4px}.editBtns{grid-template-columns:repeat(2,1fr);padding:7px 13px 0}.nudgeRow{padding:10px 13px 13px}
  #canvasStatus{position:absolute;left:328px;bottom:14px;z-index:4;max-width:calc(100vw - 660px);padding:7px 10px;border:1px solid rgba(38,49,58,.72);border-radius:8px;background:rgba(12,18,24,.8);color:#b4c0c6;font:11px/1.25 ui-monospace,SFMono-Regular,Consolas,monospace;backdrop-filter:blur(10px);pointer-events:none;box-shadow:0 12px 30px rgba(3,8,12,.18)}
  #app.side-closed #canvasStatus{left:16px;max-width:calc(100vw - 360px)}
  @media(max-width:1180px){#edit .toolLabel{display:none}#edit{max-width:calc(100vw - 96px)}#canvasStatus{display:none}}
  @media(max-width:760px){#side{width:min(92vw,340px)}#side.closed{transform:translateX(-100%)}#sideToggle{left:calc(min(92vw,340px) - 50px);top:12px}#side.closed+#sideToggle{left:12px}#edit,#app.side-closed #edit{top:10px;right:12px;left:auto;max-width:calc(100vw - 78px)}#editor{top:auto;left:8px;right:8px;bottom:8px;width:auto;max-height:48vh}}
</style></head><body>
<div id="app">
  <aside id="side">
    <div class="sideHeader"><strong>__TITLE__</strong><span><b id="listCount">0</b> visiveis de __NLOTS__ lotes</span></div>
    <nav class="sideTabs" aria-label="Areas de trabalho">
      <button class="sideTab on" data-panel="lots" aria-pressed="true">Lotes</button>
      <button class="sideTab" data-panel="visual" aria-pressed="false">Visual</button>
      <button class="sideTab" data-panel="align" aria-pressed="false">Alinhar</button>
    </nav>
    <section class="sidePanel" id="panelLots">
      <div class="shead">
        <input id="lotSearch" placeholder="Buscar lote, quadra ou area">
        <div class="filter"><button class="on" data-f="all">Todos</button><button data-f="0">Disponivel</button><button data-f="1">Vendido</button><button data-f="2">Reservado</button><button data-f="missing">Sem nome</button></div>
        <div class="sactions"><button id="selectVisible">Selecionar</button><button id="csvBtn">Baixar CSV</button><button id="clearSel">Limpar</button></div>
      </div>
      <div id="lotList"></div>
    </section>
    <section class="sidePanel" id="panelVisual" hidden>
      <div class="visualBody">
        <div class="statusSummary">
          <div class="statusMetric"><i style="background:#26d07c"></i><b id="n0">__N0__</b><span>Disponiveis</span></div>
          <div class="statusMetric"><i style="background:#6e6d67"></i><b id="n1">__N1__</b><span>Vendidos</span></div>
          <div class="statusMetric"><i style="background:#e0613b"></i><b id="n2">__N2__</b><span>Reservados</span></div>
        </div>
        <div class="palette"><div class="sectionLabel">Cores dos status</div><div class="palrow"><span class="sw" style="background:#26d07c"></span><span>Disponivel</span><input type="color" data-pal="0" value="#26d07c"></div><div class="palrow"><span class="sw" style="background:#6e6d67"></span><span>Vendido</span><input type="color" data-pal="1" value="#6e6d67"></div><div class="palrow"><span class="sw" style="background:#e0613b"></span><span>Reservado</span><input type="color" data-pal="2" value="#e0613b"></div></div>
        <div class="mapstyle"><div class="sectionLabel">Camada dos lotes</div><label class="styleRow"><span>Opacidade <b id="opacityVal">__OPACITY_PERCENT__%</b></span><input id="opacityCtrl" type="range" min="20" max="100" step="5" value="__OPACITY_PERCENT__"></label><label class="styleRow"><span>Divisao <b id="strokeVal">__STROKE__px</b></span><input id="strokeCtrl" type="range" min="0.2" max="2.0" step="0.1" value="__STROKE__"></label><label class="styleRow"><span>Numeros</span><select id="labelMode"><option value="auto">Auto</option><option value="always">Sempre</option><option value="hidden">Oculto</option></select></label></div>
      </div>
    </section>
    <section class="sidePanel" id="panelAlign" hidden>
      <div class="alignBody"><div id="lrot">
        <div class="alignGroup"><div class="sectionLabel">Angulo da camada</div><div class="alignAngle"><button id="lrm">&minus;</button><input type="range" id="lr" min="-180" max="180" step="0.1" value="0"><button id="lrp">+</button></div><div class="alignValue"><span>Rotacao</span><b id="lrval">0.0&deg;</b></div></div>
        <div class="alignGroup"><div class="sectionLabel">Posicao da camada</div><div class="alignNudge"><button id="lmleft">&#8592;</button><button id="lmup">&#8593;</button><button id="lmdown">&#8595;</button><button id="lmright">&#8594;</button></div><div class="alignPosition" id="xyval">0,0 px</div></div>
        <div class="alignGroup"><div class="alignActions"><button id="lr0">Repor</button><button id="lmove">Mover no mapa</button></div></div>
      </div></div>
    </section>
  </aside>
  <button id="sideToggle" title="Mostrar/ocultar lista" aria-expanded="true"></button>
  <div class="sideScrim" id="sideScrim"></div>
  <svg id="map" viewBox="0 0 __W__ __H__" preserveAspectRatio="xMidYMid meet">
    <image href="data:__IMG_MIME__;base64,__IMG__" x="0" y="0" width="__W__" height="__H__"></image>
    <g id="lotsrot"><g id="lots"></g><g id="labels"></g><g id="draft"></g><g id="vertices"></g></g><g id="ui"></g>
  </svg>
  <div class="panel" id="title">__TITLE__ <small>__NLOTS__ lotes &middot; <span id="cnt"></span></small></div>
  <div class="panel" id="zoom"><button id="zin">+</button><button id="zout">&minus;</button><button id="zr">&#8635;</button></div>
  <div class="panel" id="edit">
    <button id="edt"><span class="kbdIcon">&#9998;</span><span class="toolLabel">Editar</span></button>
    <span id="edtools" hidden class="toolset">
      <span class="toolset">
        <button id="edsel" class="on" title="Selecionar lotes (V)"><span class="kbdIcon">&#9633;</span><span class="toolLabel">Selecionar</span></button>
        <button id="edmove" title="Mover lotes selecionados (M)"><span class="kbdIcon">&#8596;</span><span class="toolLabel">Mover</span></button>
        <button id="edvertex" title="Editar os pontos de um lote (P)"><span class="kbdIcon">&#9671;</span><span class="toolLabel">Pontos</span></button>
        <button id="eddraw" title="Desenhar um novo lote (D)"><span class="kbdIcon">&#9998;</span><span class="toolLabel">Desenhar</span></button>
        <button id="eddel" title="Apagar lotes"><span class="kbdIcon">&#128465;</span><span class="toolLabel">Apagar</span></button>
      </span>
      <span class="toolset contextGroup">
        <button id="edgroup" title="Agrupar lotes selecionados"><span class="kbdIcon">&#9939;</span><span class="toolLabel">Agrupar</span></button>
        <button id="edungroup" title="Desagrupar lotes"><span class="kbdIcon">&#10005;</span><span class="toolLabel">Desagrupar</span></button>
      </span>
      <span class="toolset">
        <button id="edundo" title="Desfazer">&#8634;</button>
        <button id="edredo" title="Refazer">&#8635;</button>
      </span>
      <span class="toolset">
        <button class="st" data-s="0" title="Marcar como disponivel" style="color:#26d07c">&#9679;</button>
        <button class="st on" data-s="1" title="Marcar como vendido" style="color:#9a9a93">&#9679;</button>
        <button class="st" data-s="2" title="Marcar como reservado" style="color:#e0613b">&#9679;</button>
      </span>
      <span id="selectionSummary" class="selectionSummary">Nenhum lote</span>
      <span class="toolset"><button id="eddl" style="background:#26d07c;color:#06281a;border-color:#26d07c;font-weight:700" title="Baixar HTML editado">&#11015; <span class="toolLabel">Baixar</span></button></span>
    </span>
  </div>
  <aside id="editor"><div class="empty">Selecione um lote.</div></aside>
  <div class="panel" id="legend"></div>
  <div class="panel" id="info"><div class="h" id="ih"></div><div id="is"></div></div>
  <div id="canvasStatus">Pan: arraste o mapa · Zoom: scroll · Edicao: clique em Editar</div>
  <div id="toast" role="status" aria-live="polite"></div>
</div>
<script>
var W=__W__,H=__H__,INIT=__DATA__,NS="http://www.w3.org/2000/svg",NAMES=["Disponivel","Vendido","Reservado"],STATUS_KEYS=["disponivel","vendido","reservado"],statusColors=["#26d07c","#6e6d67","#e0613b"];
var app=document.getElementById('app'),mapSettings={opacity:__OPACITY__,strokeWidth:__STROKE__,labelMode:__LABEL_MODE__,imgMime:__IMG_MIME_JSON__};
  [['sideToggle','Mostrar ou ocultar a lista'],['zin','Aumentar zoom'],['zout','Diminuir zoom'],['zr','Repor zoom'],['clearSel','Limpar selecao'],['selectVisible','Selecionar lotes visiveis'],['csvBtn','Baixar dados CSV'],['edt','Ativar edicao'],['edundo','Desfazer ultima alteracao'],['edredo','Refazer ultima alteracao']].forEach(function(pair){var b=document.getElementById(pair[0]);if(b)b.setAttribute('aria-label',pair[1]);});
  var svg=document.getElementById('map'),g=document.getElementById('lots'),gl=document.getElementById('labels'),gd=document.getElementById('draft'),gv=document.getElementById('vertices'),gui=document.getElementById('ui'),listEl=document.getElementById('lotList'),editor=document.getElementById('editor');
  function norm(d,i){if(Array.isArray(d)){return{s:+d[0]||0,pts:d[1]||'',color:statusColors[+d[0]||0],nome:'Lote '+(i+1),quadra:'',area:'',group:'',extraido:false,index:i};}return{s:+(d.s||0),pts:d.pts||'',color:d.color||statusColors[+(d.s||0)],nome:d.nome||('Lote '+(i+1)),quadra:d.quadra||'',area:d.area||'',group:d.group||'',extraido:!!d.extraido,index:d.index==null?i:d.index};}
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];});}
  var L=INIT.map(norm),filterMode='all',query='';
  var toastTimer=null;function toast(message,error){var box=document.getElementById('toast');box.textContent=message;box.classList.toggle('error',!!error);box.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(function(){box.classList.remove('show');},2200);}
  function groupMembers(group){var out=[];if(!group)return out;for(var i=0;i<L.length;i++)if(L[i].group===group)out.push(i);return out;}
  function selectionHasGroup(){var yes=false;selected.forEach(function(i){if(L[i]&&L[i].group)yes=true;});return yes;}
  var selected=new Set(),editMode=false,tool="select",curStatus=1,draft=[],sel=null,dragSel=false,dragStart=null,dragRect=null,groupCounter=0;
  var moveDrag=false,movePrevious=null,vertexDrag=null;
var lotsrot=document.getElementById("lotsrot"),R=0,tx=0,ty=0,moveMode=false,cxi=W/2,cyi=H/2;
function applyLotRot(){lotsrot.setAttribute("transform","translate("+tx+" "+ty+") rotate("+R+" "+cxi+" "+cyi+")");document.getElementById("lrval").textContent=R.toFixed(1)+"\u00b0";document.getElementById("lr").value=R;document.getElementById("xyval").textContent=Math.round(tx)+","+Math.round(ty)+" px";updateLabelVisibility();}
function toLocal(p){var x=p.x-tx,y=p.y-ty,t=-R*Math.PI/180,c=Math.cos(t),si=Math.sin(t),dx=x-cxi,dy=y-cyi;return{x:cxi+dx*c-dy*si,y:cyi+dx*si+dy*c};}
function fromLocal(p){var t=R*Math.PI/180,c=Math.cos(t),si=Math.sin(t),dx=p.x-cxi,dy=p.y-cyi;return{x:tx+cxi+dx*c-dy*si,y:ty+cyi+dx*si+dy*c};}
function bakePts(str){return str.split(' ').filter(Boolean).map(function(pair){var a=pair.split(','),p=fromLocal({x:parseFloat(a[0]),y:parseFloat(a[1])});return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ');}
  function currentLots(){return L.map(function(o,i){return{s:o.s,pts:bakePts(o.pts),color:o.color,nome:o.nome,quadra:o.quadra,area:o.area,group:o.group||'',extraido:o.extraido,index:o.index==null?i:o.index};});}
function currentPayload(){return{img:svg.querySelector('image').getAttribute('href').split(',')[1],img_mime:mapSettings.imgMime,w:W,h:H,title:(document.getElementById('title').childNodes[0].textContent||'mapa').trim(),lots:currentLots(),opacity:mapSettings.opacity,stroke_width:mapSettings.strokeWidth,label_mode:mapSettings.labelMode};}
window.getMapaPayload=currentPayload;
function el(t){return document.createElementNS(NS,t);}
function labelText(o,i){var n=(o.nome||'').trim();return n&&!/^Lote\s+\d+$/i.test(n)?n:'#'+(i+1);}
function localCenter(i){var pts=ptsArray(L[i].pts);if(pts.length>1){var a=pts[0],b=pts[pts.length-1];if(Math.abs(a.x-b.x)<.01&&Math.abs(a.y-b.y)<.01)pts.pop();}if(!pts.length)return{x:0,y:0};var sx=0,sy=0;pts.forEach(function(p){sx+=p.x;sy+=p.y;});return{x:sx/pts.length,y:sy/pts.length};}
function cachedCenter(i){var o=L[i];if(!o)return{x:0,y:0};if(o._cx==null||o._cy==null){var c=localCenter(i);o._cx=c.x;o._cy=c.y;}return{x:o._cx,y:o._cy};}
function updateLotStyle(i){var o=L[i];if(!o)return;var p=g.querySelector('polygon[data-i="'+i+'"]');if(p){p.dataset.s=o.s;p.setAttribute('class','lot'+(selected.has(i)?' sel':''));p.style.fill=o.color;}var t=gl.querySelector('text[data-i="'+i+'"]');if(t)t.textContent=labelText(o,i);}
  function syncSelection(){Array.prototype.forEach.call(g.children,function(p){var i=parseInt(p.dataset.i);p.classList.toggle('sel',selected.has(i));});Array.prototype.forEach.call(listEl.querySelectorAll('.lotrow'),function(r){r.classList.toggle('on',selected.has(parseInt(r.dataset.i)));});counts();renderEditor();redrawVertices();}
function applyMapStyle(){mapSettings.opacity=Math.max(.2,Math.min(1,parseFloat(mapSettings.opacity)||.7));mapSettings.strokeWidth=Math.max(.2,Math.min(2.5,parseFloat(mapSettings.strokeWidth)||.6));app.style.setProperty('--lot-opacity',mapSettings.opacity.toFixed(2));app.style.setProperty('--lot-stroke',mapSettings.strokeWidth.toFixed(1)+'px');document.getElementById('opacityVal').textContent=Math.round(mapSettings.opacity*100)+'%';document.getElementById('strokeVal').textContent=mapSettings.strokeWidth.toFixed(1)+'px';updateLabelVisibility();}
var labelFrame=0,labelLimit=420,labelIdleTimer=null,fastMapTimer=null;
function clearLabels(){while(gl.firstChild)gl.removeChild(gl.firstChild);}
function suspendLabels(){clearTimeout(labelIdleTimer);gl.style.display='none';clearLabels();labelIdleTimer=setTimeout(function(){updateLabelVisibility(true);},180);}
function suspendMapDetails(){clearTimeout(fastMapTimer);suspendLabels();lotsrot.style.visibility='hidden';fastMapTimer=setTimeout(function(){lotsrot.style.visibility='';updateLabelVisibility(true);},180);}
function renderVisibleLabels(){
  labelFrame=0;
  var show=mapSettings.labelMode==='always'||(mapSettings.labelMode==='auto'&&vb.w<=W*.38);
  if(!show){gl.style.display='none';clearLabels();return;}
  gl.style.display='';
  var pad=Math.max(30,vb.w*.08),x0=vb.x-pad,y0=vb.y-pad,x1=vb.x+vb.w+pad,y1=vb.y+vb.h+pad;
  var max=mapSettings.labelMode==='always'?650:labelLimit,keep={},made=0;
  for(var i=0;i<L.length&&made<max;i++){
    var c=cachedCenter(i),p=fromLocal(c);
    if(p.x<x0||p.x>x1||p.y<y0||p.y>y1)continue;
    keep[i]=true;made++;
    var t=gl.querySelector('text[data-i="'+i+'"]');
    if(!t){t=el('text');t.setAttribute('class','lotlabel');t.dataset.i=i;gl.appendChild(t);}
    t.setAttribute('x',c.x.toFixed(1));t.setAttribute('y',c.y.toFixed(1));t.textContent=labelText(L[i],i);
  }
  Array.prototype.slice.call(gl.children).forEach(function(t){if(!keep[t.dataset.i])gl.removeChild(t);});
}
function updateLabelVisibility(force){if(typeof vb==='undefined')return;if(force)labelFrame=0;if(labelFrame)return;labelFrame=requestAnimationFrame(renderVisibleLabels);}
  function redraw(){while(g.firstChild)g.removeChild(g.firstChild);clearLabels();for(var i=0;i<L.length;i++){var p=el('polygon');p.setAttribute('points',L[i].pts);p.setAttribute('class','lot'+(selected.has(i)?' sel':''));p.dataset.i=i;p.dataset.s=L[i].s;p.style.fill=L[i].color;cachedCenter(i);g.appendChild(p);}counts();renderList();renderEditor();redrawVertices();updateLabelVisibility();}
  function updateCanvasStatus(){var box=document.getElementById('canvasStatus');if(!box)return;var selectedText=selected.size?selected.size+' lote'+(selected.size>1?'s':'')+' selecionado'+(selected.size>1?'s':''):'nenhum lote';var mode='Pan: arraste o mapa · Zoom: scroll';if(editMode){if(tool==='select')mode='Selecionar: clique no lote ou arraste uma caixa';else if(tool==='move')mode='Mover: arraste a selecao no mapa';else if(tool==='vertex')mode='Pontos: arraste vertices do lote selecionado';else if(tool==='draw')mode='Desenhar: clique nos cantos e Enter para concluir';else if(tool==='delete')mode='Apagar: clique em um lote para remover';}box.textContent=mode+' · '+selectedText;}
  function counts(){var n=[0,0,0];for(var i=0;i<L.length;i++)n[L[i].s]++;document.getElementById('n0').textContent=n[0];document.getElementById('n1').textContent=n[1];document.getElementById('n2').textContent=n[2];document.getElementById('cnt').textContent=selected.size?(selected.size+' selecionado'+(selected.size>1?'s':'')):'lista editavel';var summary=document.getElementById('selectionSummary');if(summary){summary.textContent=selected.size?(selected.size+' lote'+(selected.size>1?'s':'')):'Nenhum lote';summary.classList.toggle('active',selected.size>0);}var groupBtn=document.getElementById('edgroup'),ungroupBtn=document.getElementById('edungroup'),vertexBtn=document.getElementById('edvertex'),moveBtn=document.getElementById('edmove');if(groupBtn)groupBtn.disabled=selected.size<2;if(ungroupBtn)ungroupBtn.disabled=!selectionHasGroup();if(vertexBtn)vertexBtn.disabled=selected.size!==1;if(moveBtn)moveBtn.disabled=!selected.size;updateCanvasStatus();}
var listTimer=null;function scheduleListRender(){clearTimeout(listTimer);listTimer=setTimeout(renderList,80);}
function matches(i){var o=L[i],hay=(o.nome+' '+o.quadra+' '+o.area+' '+NAMES[o.s]).toLowerCase();if(query&&hay.indexOf(query)<0)return false;if(filterMode==='missing')return !o.extraido||/^Lote \d+$/.test(o.nome);if(filterMode!=='all'&&String(o.s)!==filterMode)return false;return true;}
function renderList(){var frag=document.createDocumentFragment(),visible=0;for(var i=0;i<L.length;i++){if(!matches(i))continue;visible++;var o=L[i],b=document.createElement('button');b.className='lotrow'+(selected.has(i)?' on':'');b.dataset.i=i;b.innerHTML='<span class="sw" style="background:'+esc(o.color)+'"></span><span><span class="lt">'+esc((o.quadra?o.quadra+' \u00b7 ':'')+o.nome)+'</span><span class="lm">'+esc((o.area||'sem area')+' \u00b7 '+NAMES[o.s]+(o.group?' \u00b7 agrupado':''))+'</span></span><span class="tag">#'+(i+1)+'</span>';b.onclick=function(e){selectIndex(+this.dataset.i,e.shiftKey);};frag.appendChild(b);}listEl.replaceChildren(frag);document.getElementById('listCount').textContent=visible;}
var listWindowFrame=0,listMatches=[],LIST_ROW_H=54;
function renderListWindow(){if(!listEl.firstChild)return;var inner=listEl.firstChild,start=Math.max(0,Math.floor(listEl.scrollTop/LIST_ROW_H)-6),end=Math.min(listMatches.length,start+Math.ceil((listEl.clientHeight||400)/LIST_ROW_H)+12),frag=document.createDocumentFragment();for(var k=start;k<end;k++){var i=listMatches[k],o=L[i],b=document.createElement('button');b.className='lotrow'+(selected.has(i)?' on':'');b.dataset.i=i;b.style.top=(k*LIST_ROW_H+3)+'px';b.style.height=(LIST_ROW_H-6)+'px';b.innerHTML='<span class="sw" style="background:'+esc(o.color)+'"></span><span><span class="lt">'+esc((o.quadra?o.quadra+' \u00b7 ':'')+o.nome)+'</span><span class="lm">'+esc((o.area||'sem area')+' \u00b7 '+NAMES[o.s]+(o.group?' \u00b7 agrupado':''))+'</span></span><span class="tag">#'+(i+1)+'</span>';b.onclick=function(e){selectIndex(+this.dataset.i,e.shiftKey);};frag.appendChild(b);}inner.replaceChildren(frag);}
function scheduleListWindow(){if(listWindowFrame)return;listWindowFrame=requestAnimationFrame(function(){listWindowFrame=0;renderListWindow();});}
function renderList(){listMatches=[];for(var i=0;i<L.length;i++){if(matches(i))listMatches.push(i);}var inner=document.createElement('div');inner.style.position='relative';inner.style.height=(listMatches.length*LIST_ROW_H)+'px';listEl.replaceChildren(inner);document.getElementById('listCount').textContent=listMatches.length;renderListWindow();}
listEl.addEventListener('scroll',scheduleListWindow,{passive:true});
function firstSelected(){var a=Array.from(selected);return a.length?a[0]:null;}
function renderEditor(){
  var idx=firstSelected();
  if(idx==null||!L[idx]){editor.classList.remove('show');editor.innerHTML='<div class="empty">Selecione um lote.</div>';return;}
  var o=L[idx],multi=selected.size>1,grouped=selectionHasGroup(),badge=grouped?'Grupo ativo':(multi?selected.size+' lotes':'Lote #'+(idx+1));
  editor.classList.add('show');
  editor.innerHTML='<div class="selectionHead"><strong>'+(multi?selected.size+' lotes selecionados':esc(o.nome))+'</strong><span class="selectionHeadActions"><span class="groupBadge">'+badge+'</span><button class="inspectorClose" id="clearInspector" title="Fechar inspetor">&times;</button></span></div><div class="inspectorSection">Dados do lote</div><div class="formgrid"><label class="field full">Nome do lote<input id="lotName" '+(multi?'disabled ':'')+'value="'+esc(multi?selected.size+' lotes selecionados':o.nome)+'"></label><label class="field">Quadra<input id="lotQuadra" '+(multi?'disabled ':'')+'value="'+esc(o.quadra)+'"></label><label class="field">Area<input id="lotArea" '+(multi?'disabled ':'')+'value="'+esc(o.area)+'"></label><label class="field">Status<select id="lotStatus"><option value="0">Disponivel</option><option value="1">Vendido</option><option value="2">Reservado</option></select></label><label class="field">Cor<input id="lotColor" type="color" value="'+esc(o.color)+'"></label></div><div class="inspectorSection">Geometria e grupo</div><div class="editBtns"><button id="zoomLot" class="primary">Enquadrar</button><button id="editPoints" '+(multi?'disabled':'')+'>Pontos</button><button id="dupLot" '+(multi?'disabled':'')+'>Duplicar</button><button id="groupLots" '+(selected.size<2?'disabled':'')+'>Agrupar</button><button id="ungroupLots" '+(!grouped?'disabled':'')+'>Desagrupar</button><button id="delLot" class="danger">Apagar</button></div><div class="nudgeRow"><span>Mover selecao</span><div class="nudgeGrid"><button data-nudge="-1,0" title="Mover para esquerda">&#8592;</button><button data-nudge="0,-1" title="Mover para cima">&#8593;</button><button data-nudge="0,1" title="Mover para baixo">&#8595;</button><button data-nudge="1,0" title="Mover para direita">&#8594;</button></div></div>';
  document.getElementById('clearInspector').onclick=function(){selected.clear();syncSelection();};
  document.getElementById('lotStatus').value=o.s;
  if(!multi){
    ['lotName','lotQuadra','lotArea'].forEach(function(id){document.getElementById(id).onfocus=function(){snapshot();};});
    document.getElementById('lotName').oninput=function(){o.nome=this.value;updateLotStyle(idx);scheduleListRender();};
    document.getElementById('lotQuadra').oninput=function(){o.quadra=this.value;scheduleListRender();};
    document.getElementById('lotArea').oninput=function(){o.area=this.value;scheduleListRender();};
    document.getElementById('dupLot').onclick=function(){snapshot();var cp=JSON.parse(JSON.stringify(o));cp.nome=cp.nome+' copia';cp.group='';L.splice(idx+1,0,cp);selected.clear();selected.add(idx+1);redraw();toast('Lote duplicado');};
  }
  document.getElementById('lotStatus').onchange=function(){applyStatusToSelection(+this.value);};
  document.getElementById('lotColor').onpointerdown=function(){snapshot();};
  document.getElementById('lotColor').oninput=function(){var color=this.value;selected.forEach(function(i){if(L[i]){L[i].color=color;updateLotStyle(i);}});scheduleListRender();};
  document.getElementById('zoomLot').onclick=zoomToSelection;
  document.getElementById('editPoints').onclick=function(){setTool('vertex');};
  document.getElementById('groupLots').onclick=groupSelected;
  document.getElementById('ungroupLots').onclick=ungroupSelected;
  document.getElementById('delLot').onclick=function(){deleteSelection();};
  Array.prototype.forEach.call(editor.querySelectorAll('[data-nudge]'),function(button){button.onclick=function(){var d=this.dataset.nudge.split(',');nudgeSelection(+d[0],+d[1]);};});
}
function ptsArray(str){return str.split(' ').filter(Boolean).map(function(pair){var a=pair.split(',');return{x:+a[0],y:+a[1]};});}
function zoomToLot(i){var pts=ptsArray(L[i].pts);if(!pts.length)return;var xs=pts.map(function(p){return p.x;}),ys=pts.map(function(p){return p.y;}),minx=Math.min.apply(null,xs),maxx=Math.max.apply(null,xs),miny=Math.min.apply(null,ys),maxy=Math.max.apply(null,ys),pad=Math.max(40,(maxx-minx+maxy-miny)*.9);vb={x:minx-pad,y:miny-pad,w:Math.max(120,maxx-minx+pad*2),h:Math.max(120,maxy-miny+pad*2)};ap();}
function zoomToSelection(){var all=[];selected.forEach(function(i){if(L[i])all=all.concat(ptsArray(L[i].pts));});if(!all.length)return;var xs=all.map(function(p){return p.x;}),ys=all.map(function(p){return p.y;}),minx=Math.min.apply(null,xs),maxx=Math.max.apply(null,xs),miny=Math.min.apply(null,ys),maxy=Math.max.apply(null,ys),pad=Math.max(30,(maxx-minx+maxy-miny)*.24);vb={x:minx-pad,y:miny-pad,w:Math.max(100,maxx-minx+pad*2),h:Math.max(100,maxy-miny+pad*2)};ap();}
function csv(){var rows=[['index','quadra','lote','area','status','cor','grupo','pontos']].concat(currentLots().map(function(o,i){return[i,o.quadra,o.nome,o.area,STATUS_KEYS[o.s],o.color,o.group||'',o.pts];}));return rows.map(function(r){return r.map(function(v){return '"'+String(v==null?'':v).replace(/"/g,'""')+'"';}).join(',');}).join('\n');}
document.getElementById('lotSearch').oninput=function(){query=this.value.toLowerCase().trim();scheduleListRender();};Array.prototype.forEach.call(document.querySelectorAll('.filter button'),function(b){b.onclick=function(){filterMode=this.dataset.f;Array.prototype.forEach.call(document.querySelectorAll('.filter button'),function(x){x.classList.remove('on');});this.classList.add('on');scheduleListRender();};});
function setSidePanel(name){Array.prototype.forEach.call(document.querySelectorAll('.sideTab'),function(button){var active=button.dataset.panel===name;button.classList.toggle('on',active);button.setAttribute('aria-pressed',String(active));});['lots','visual','align'].forEach(function(panel){document.getElementById('panel'+panel.charAt(0).toUpperCase()+panel.slice(1)).hidden=panel!==name;});}
Array.prototype.forEach.call(document.querySelectorAll('.sideTab'),function(button){button.onclick=function(){setSidePanel(this.dataset.panel);};});
Array.prototype.forEach.call(document.querySelectorAll('[data-pal]'),function(inp){inp.onpointerdown=function(){snapshot();};inp.oninput=function(){var s=+this.dataset.pal;statusColors[s]=this.value;this.parentElement.querySelector('.sw').style.background=this.value;L.forEach(function(o,i){if(o.s===s){o.color=statusColors[s];updateLotStyle(i);}});scheduleListRender();};});
document.getElementById('opacityCtrl').oninput=function(){mapSettings.opacity=parseInt(this.value,10)/100;applyMapStyle();};
document.getElementById('strokeCtrl').oninput=function(){mapSettings.strokeWidth=parseFloat(this.value);applyMapStyle();};
document.getElementById('labelMode').value=mapSettings.labelMode;
document.getElementById('labelMode').onchange=function(){mapSettings.labelMode=this.value;updateLabelVisibility();};
document.getElementById('csvBtn').onclick=function(){var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv()],{type:'text/csv;charset=utf-8'}));a.download='lotes.csv';a.click();};
document.getElementById('selectVisible').onclick=function(){selected=new Set(listMatches);expandSelectedGroups();syncSelection();toast(selected.size+' lotes selecionados');};
document.getElementById('clearSel').onclick=function(){selected.clear();document.getElementById('info').style.display='none';syncSelection();};
function setSideClosed(closed){document.getElementById('side').classList.toggle('closed',closed);app.classList.toggle('side-closed',closed);document.getElementById('sideToggle').setAttribute('aria-expanded',String(!closed));}
document.getElementById('sideToggle').onclick=function(){setSideClosed(!document.getElementById('side').classList.contains('closed'));};
document.getElementById('sideScrim').onclick=function(){setSideClosed(true);};
var vb={x:0,y:0,w:W,h:H},viewFrame=0;function ap(){if(viewFrame)return;viewFrame=requestAnimationFrame(function(){viewFrame=0;svg.setAttribute('viewBox',vb.x+' '+vb.y+' '+vb.w+' '+vb.h);updateLabelVisibility();redrawVertices();});}
function c2s(px,py){var r=svg.getBoundingClientRect(),sc=Math.min(r.width/vb.w,r.height/vb.h);var ox=(r.width-vb.w*sc)/2,oy=(r.height-vb.h*sc)/2;return{x:vb.x+(px-r.left-ox)/sc,y:vb.y+(py-r.top-oy)/sc};}
function zoomAt(px,py,f){suspendLabels();var p=c2s(px,py),nw=vb.w*f;nw=Math.max(W*0.03,Math.min(W*2.5,nw));var rf=nw/vb.w;vb.x=p.x-(p.x-vb.x)*rf;vb.y=p.y-(p.y-vb.y)*rf;vb.w=nw;vb.h=vb.h*rf;ap();}
function lotCenter(i){var pts=L[i].pts.split(' ').filter(Boolean),sx=0,sy=0,n=0;pts.forEach(function(pair){var a=pair.split(',');sx+=parseFloat(a[0]);sy+=parseFloat(a[1]);n++;});return fromLocal({x:sx/n,y:sy/n});}
function setLotPoints(i,points){if(!L[i])return;L[i].pts=points.map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ');L[i]._cx=null;L[i]._cy=null;var poly=g.querySelector('polygon[data-i="'+i+'"]');if(poly)poly.setAttribute('points',L[i].pts);var text=gl.querySelector('text[data-i="'+i+'"]');if(text){var c=cachedCenter(i);text.setAttribute('x',c.x);text.setAttribute('y',c.y);}}
function translateSelection(dx,dy,record){if(!selected.size)return;if(record)snapshot();selected.forEach(function(i){setLotPoints(i,ptsArray(L[i].pts).map(function(p){return{x:p.x+dx,y:p.y+dy};}));});redrawVertices();if(record)updateLabelVisibility(true);}
function nudgeSelection(dx,dy){translateSelection(dx,dy,true);}
function redrawVertices(){while(gv.firstChild)gv.removeChild(gv.firstChild);if(!editMode||tool!=='vertex'||selected.size!==1)return;var i=firstSelected(),points=ptsArray(L[i].pts);if(points.length>1&&Math.hypot(points[0].x-points[points.length-1].x,points[0].y-points[points.length-1].y)<.01)points.pop();var radius=Math.max(.7,vb.w*.004);points.forEach(function(p,index){var c=el('circle');c.setAttribute('class','vertexpt');c.setAttribute('cx',p.x);c.setAttribute('cy',p.y);c.setAttribute('r',radius);c.dataset.i=i;c.dataset.v=index;gv.appendChild(c);});}
function setTool(t){if(t==='vertex'&&selected.size!==1){toast('Selecione um unico lote para editar os pontos.',true);t='select';}if(t==='move'&&!selected.size){toast('Selecione ao menos um lote para mover.',true);t='select';}tool=t;['edsel','edmove','edvertex','eddraw','eddel'].forEach(function(id){var modes={edsel:'select',edmove:'move',edvertex:'vertex',eddraw:'draw',eddel:'delete'},active=modes[id]===t,button=document.getElementById(id);button.classList.toggle('on',active);button.setAttribute('aria-pressed',String(active));});draft=[];redrawDraft();svg.classList.toggle('draw',editMode&&t==='draw');svg.classList.toggle('move-lots',editMode&&t==='move');svg.classList.toggle('vertex-edit',editMode&&t==='vertex');redrawVertices();updateCanvasStatus();}
function clearDragBox(){while(gui.firstChild)gui.removeChild(gui.firstChild);dragRect=null;dragStart=null;dragSel=false;}
function drawDragBox(a,b){while(gui.firstChild)gui.removeChild(gui.firstChild);var r=el('rect'),x=Math.min(a.x,b.x),y=Math.min(a.y,b.y),w=Math.abs(a.x-b.x),h=Math.abs(a.y-b.y);r.setAttribute('x',x);r.setAttribute('y',y);r.setAttribute('width',w);r.setAttribute('height',h);r.setAttribute('class','selectbox');gui.appendChild(r);dragRect={x:x,y:y,w:w,h:h};}
function expandSelectedGroups(){var groups={};selected.forEach(function(i){if(L[i]&&L[i].group)groups[L[i].group]=true;});Object.keys(groups).forEach(function(group){groupMembers(group).forEach(function(i){selected.add(i);});});}
function finishDragBox(add){if(!dragRect)return;var x2=dragRect.x+dragRect.w,y2=dragRect.y+dragRect.h;if(!add)selected.clear();for(var i=0;i<L.length;i++){var c=lotCenter(i);if(c.x>=dragRect.x&&c.x<=x2&&c.y>=dragRect.y&&c.y<=y2)selected.add(i);}expandSelectedGroups();clearDragBox();syncSelection();}
svg.addEventListener('wheel',function(e){e.preventDefault();suspendMapDetails();zoomAt(e.clientX,e.clientY,e.deltaY>0?1.12:.892);},{passive:false});
var ptrs=new Map(),moved=false,dn=null,ld=0,lotPress=false;
svg.addEventListener('pointerdown',function(e){ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});moved=false;lotPress=false;dn={x:e.clientX,y:e.clientY};var cls=e.target.getAttribute?e.target.getAttribute('class')||'':'';if(cls.indexOf('lot')>=0&&(!editMode||tool==='select'||tool==='vertex'||tool==='delete')){lotPress=true;return;}svg.setPointerCapture(e.pointerId);if(editMode&&tool==='vertex'&&cls.indexOf('vertexpt')>=0){snapshot();suspendLabels();vertexDrag={i:+e.target.dataset.i,v:+e.target.dataset.v};return;}if(editMode&&tool==='move'){var lot=cls.indexOf('lot')>=0?e.target:null;if(lot){var index=+lot.dataset.i;if(!selected.has(index))selectIndex(index,e.shiftKey);snapshot();suspendLabels();moveDrag=true;movePrevious=toLocal(c2s(e.clientX,e.clientY));return;}}if(editMode&&tool==='select'){dragSel=true;dragStart=c2s(e.clientX,e.clientY);}});
svg.addEventListener('pointermove',function(e){if(!ptrs.has(e.pointerId))return;var pv=ptrs.get(e.pointerId);ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});if(lotPress)return;if(dn&&Math.abs(e.clientX-dn.x)+Math.abs(e.clientY-dn.y)>4)moved=true;if(vertexDrag){var point=toLocal(c2s(e.clientX,e.clientY)),points=ptsArray(L[vertexDrag.i].pts),closed=points.length>1&&Math.hypot(points[0].x-points[points.length-1].x,points[0].y-points[points.length-1].y)<.01;points[vertexDrag.v]={x:point.x,y:point.y};if(closed&&vertexDrag.v===0)points[points.length-1]={x:point.x,y:point.y};setLotPoints(vertexDrag.i,points);redrawVertices();return;}if(moveDrag){var current=toLocal(c2s(e.clientX,e.clientY));translateSelection(current.x-movePrevious.x,current.y-movePrevious.y,false);movePrevious=current;return;}if(dragSel&&ptrs.size===1){suspendLabels();drawDragBox(dragStart,c2s(e.clientX,e.clientY));return;}if(ptrs.size===1){suspendMapDetails();var r=svg.getBoundingClientRect(),sc=Math.min(r.width/vb.w,r.height/vb.h);if(moveMode){tx+=(e.clientX-pv.x)/sc;ty+=(e.clientY-pv.y)/sc;applyLotRot();}else{vb.x-=(e.clientX-pv.x)/sc;vb.y-=(e.clientY-pv.y)/sc;ap();}}else if(ptrs.size===2){suspendMapDetails();var ar=Array.from(ptrs.values()),d=Math.hypot(ar[0].x-ar[1].x,ar[0].y-ar[1].y);if(ld)zoomAt((ar[0].x+ar[1].x)/2,(ar[0].y+ar[1].y)/2,ld/d);ld=d;}});
function up(e){if(dragSel&&moved)finishDragBox(e.shiftKey);else if(dragSel)clearDragBox();if(moveDrag||vertexDrag){moveDrag=false;movePrevious=null;vertexDrag=null;scheduleListRender();renderEditor();updateLabelVisibility(true);}lotPress=false;ptrs.delete(e.pointerId);if(ptrs.size<2)ld=0;}svg.addEventListener('pointerup',up);svg.addEventListener('pointercancel',up);
// ---- edicao ----
var hist=[],future=[];
function snapshot(){hist.push(JSON.stringify(L));if(hist.length>24)hist.shift();future=[];}
function restore(){if(!hist.length){toast('Nao ha alteracoes para desfazer.',true);return;}future.push(JSON.stringify(L));L=JSON.parse(hist.pop());selected.clear();draft=[];redrawDraft();redraw();toast('Alteracao desfeita');}
function redo(){if(!future.length){toast('Nao ha alteracoes para refazer.',true);return;}hist.push(JSON.stringify(L));L=JSON.parse(future.pop());selected.clear();draft=[];redrawDraft();redraw();toast('Alteracao refeita');}
function selectIndex(i,add){if(!L[i])return;var members=L[i].group?groupMembers(L[i].group):[i],allSelected=members.every(function(index){return selected.has(index);});if(!add)selected.clear();if(add&&allSelected)members.forEach(function(index){selected.delete(index);});else members.forEach(function(index){selected.add(index);});var o=L[i];document.getElementById('ih').textContent=(o.quadra?o.quadra+' \u00b7 ':'')+o.nome;document.getElementById('is').innerHTML='Status: <b>'+NAMES[o.s]+'</b><br>Area: <b>'+(esc(o.area)||'-')+'</b>';document.getElementById('info').style.display='block';syncSelection();}
function groupSelected(){if(selected.size<2){toast('Selecione pelo menos dois lotes.',true);return;}snapshot();var id='grupo-'+Date.now().toString(36)+'-'+(++groupCounter);selected.forEach(function(i){if(L[i])L[i].group=id;});scheduleListRender();syncSelection();toast(selected.size+' lotes agrupados');}
function ungroupSelected(){var groups={};selected.forEach(function(i){if(L[i]&&L[i].group)groups[L[i].group]=true;});var names=Object.keys(groups);if(!names.length){toast('A selecao nao possui grupo.',true);return;}snapshot();L.forEach(function(o){if(groups[o.group])o.group='';});scheduleListRender();syncSelection();toast('Grupo removido');}
function applyStatusToSelection(s){if(!selected.size)return;snapshot();selected.forEach(function(i){if(L[i]){L[i].s=s;L[i].color=statusColors[s];updateLotStyle(i);}});counts();scheduleListRender();renderEditor();}
function deleteSelection(){if(!selected.size)return;snapshot();var total=selected.size;L=L.filter(function(_,i){return !selected.has(i);});selected.clear();if(tool==='vertex'||tool==='move')setTool('select');redraw();toast(total+' lote'+(total>1?'s':'')+' apagado'+(total>1?'s':''));}
function redrawDraft(){while(gd.firstChild)gd.removeChild(gd.firstChild);if(draft.length){var pl=el('polyline');pl.setAttribute('points',draft.map(function(v){return v.x+','+v.y;}).join(' '));pl.setAttribute('class','draftline');gd.appendChild(pl);draft.forEach(function(v){var c=el('circle');c.setAttribute('cx',v.x);c.setAttribute('cy',v.y);c.setAttribute('r',Math.max(2,vb.w*0.004));c.setAttribute('class','draftpt');gd.appendChild(c);});}}
function finishDraft(){if(draft.length<3){toast('Marque pelo menos tres pontos.',true);return;}snapshot();L.push({s:curStatus,pts:draft.map(function(v){return v.x.toFixed(1)+','+v.y.toFixed(1);}).join(' '),color:statusColors[curStatus],nome:'Lote '+(L.length+1),quadra:'',area:'',group:'',extraido:false,index:L.length});selected.clear();selected.add(L.length-1);draft=[];redrawDraft();redraw();toast('Novo lote criado');}
svg.addEventListener('click',function(e){
  if(moved)return;
  var lot=(e.target.getAttribute&&(e.target.getAttribute('class')||'').indexOf('lot')>=0)?e.target:null;
  if(!editMode){ if(lot){selectIndex(parseInt(lot.dataset.i),false);} return; }
  if(tool==='select'){ if(lot)selectIndex(parseInt(lot.dataset.i),e.shiftKey); return; }
  if(tool==='delete'){ if(lot){selectIndex(parseInt(lot.dataset.i),false);deleteSelection();} return; }
  if(tool==='vertex'){if(lot)selectIndex(parseInt(lot.dataset.i),false);return;}
  if(tool==='move'||tool!=='draw')return;
  var p=toLocal(c2s(e.clientX,e.clientY));
  if(draft.length>=3){var f=draft[0];if(Math.hypot(p.x-f.x,p.y-f.y)<vb.w*0.012){finishDraft();return;}}
  draft.push({x:+p.x.toFixed(1),y:+p.y.toFixed(1)});redrawDraft();
});
document.addEventListener('keydown',function(e){if(!editMode)return;var typing=/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();if(e.shiftKey)redo();else restore();return;}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();redo();return;}if(typing)return;var key=e.key.toLowerCase();if((e.ctrlKey||e.metaKey)&&key==='a'){e.preventDefault();selected=new Set(listMatches);expandSelectedGroups();syncSelection();return;}if(key==='v')setTool('select');if(key==='m')setTool('move');if(key==='p')setTool('vertex');if(key==='d')setTool('draw');if(key==='g'&&!e.shiftKey)groupSelected();if(key==='g'&&e.shiftKey)ungroupSelected();if(e.key==='Enter'&&tool==='draw')finishDraft();if(e.key==='Escape'){draft=[];redrawDraft();clearDragBox();if(tool!=='select')setTool('select');}if((e.key==='Delete'||e.key==='Backspace')&&selected.size)deleteSelection();});
function setEdit(on){editMode=on;document.getElementById('edtools').hidden=!on;document.getElementById('edt').classList.toggle('on',on);document.getElementById('edt').setAttribute('aria-pressed',String(on));if(on)setTool('select');else{tool='select';draft=[];redrawDraft();clearDragBox();while(gv.firstChild)gv.removeChild(gv.firstChild);svg.classList.remove('draw','move-lots','vertex-edit');updateCanvasStatus();}}
document.getElementById('edt').onclick=function(){setEdit(!editMode);};
Array.prototype.forEach.call(document.querySelectorAll('#edit .st'),function(b){b.onclick=function(){curStatus=parseInt(b.dataset.s);Array.prototype.forEach.call(document.querySelectorAll('#edit .st'),function(x){x.classList.remove('on');});b.classList.add('on');applyStatusToSelection(curStatus);};});
document.getElementById('edsel').onclick=function(){setTool('select');};
document.getElementById('edmove').onclick=function(){setTool('move');};
document.getElementById('edvertex').onclick=function(){setTool('vertex');};
document.getElementById('eddraw').onclick=function(){setTool('draw');};
document.getElementById('eddel').onclick=function(){if(selected.size)deleteSelection();else setTool('delete');};
document.getElementById('edundo').onclick=function(){if(draft.length){draft.pop();redrawDraft();}else restore();};
document.getElementById('edredo').onclick=redo;
document.getElementById('edgroup').onclick=groupSelected;
document.getElementById('edungroup').onclick=ungroupSelected;
document.getElementById('eddl').onclick=function(){fetch('/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(currentPayload())}).then(function(r){if(!r.ok)throw new Error();return r.text();}).then(function(html){var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([html],{type:'text/html'}));a.download='mapa.html';a.click();toast('HTML atualizado gerado');}).catch(function(){toast('Nao foi possivel gerar o HTML.',true);});};
document.getElementById('zin').onclick=function(){var r=svg.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,.8);};
document.getElementById('zout').onclick=function(){var r=svg.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,1.25);};
document.getElementById('zr').onclick=function(){vb={x:0,y:0,w:W,h:H};ap();document.getElementById('info').style.display='none';if(sel){sel.classList.remove('sel');sel=null;}};
document.getElementById("lr").addEventListener("input",function(){R=parseFloat(this.value);applyLotRot();});
document.getElementById("lrm").onclick=function(){R-=0.5;if(R<-180)R+=360;applyLotRot();};
document.getElementById("lrp").onclick=function(){R+=0.5;if(R>180)R-=360;applyLotRot();};
document.getElementById("lr0").onclick=function(){R=0;tx=0;ty=0;applyLotRot();};
document.getElementById("lmove").onclick=function(){moveMode=!moveMode;this.classList.toggle("on",moveMode);svg.style.cursor=moveMode?"move":"";};
function nudge(dx,dy){tx+=dx;ty+=dy;applyLotRot();}
document.getElementById("lmleft").onclick=function(){nudge(-5,0);};
document.getElementById("lmright").onclick=function(){nudge(5,0);};
document.getElementById("lmup").onclick=function(){nudge(0,-5);};
document.getElementById("lmdown").onclick=function(){nudge(0,5);};
if(window.matchMedia&&window.matchMedia('(max-width:760px)').matches)setSideClosed(true);applyMapStyle();redraw();ap();applyLotRot();
</script></body></html>'''


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
