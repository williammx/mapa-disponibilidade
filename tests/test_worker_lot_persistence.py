"""Regressao do BRK-4: o worker gravava zero lotes em toda conversao.

`extract_lots_from_info` lia chaves que `pdf_to_map.convert()` nunca produziu
(`points`, `status`, `id`), entao devolvia lista vazia em silencio e
`validate_lots([])` assinava laudo verde. O mapa era publicado sem lote nenhum
no banco.
"""
import json

import pytest

from app_v1.validation import validate_lots
from app_v1.worker import _parse_area, _parse_points, extract_lots_from_info


def _convert_output(lot_count=3):
    """Reproduz o formato real de pdf_to_map.convert(), via _normalize_lot."""
    from pdf_to_map import _normalize_lot

    data = []
    for index in range(lot_count):
        data.append(_normalize_lot({
            "s": index % 3,
            "pts": "10,10 30,10 30,25 10,25",
            "nome": "Q195-L%03d" % (index + 1),
            "quadra": "Q195",
            "area": "178.86m²",
            "color": "#26d07c",
            "index": index,
        }, index))
    return {"lotes": len(data), "data": data}


def test_lotes_do_conversor_viram_linhas_na_tabela():
    info = _convert_output(3)
    lots = extract_lots_from_info(info, "proj-1", "ver-1")
    assert len(lots) == 3, "o worker precisa gravar um Lot por lote convertido"


def test_geometria_chega_com_pontos_utilizaveis():
    lots = extract_lots_from_info(_convert_output(1), "proj-1", "ver-1")
    geometry = json.loads(lots[0].geometry_json)
    assert len(geometry["points"]) == 4
    assert geometry["points"][0] == [10.0, 10.0]


def test_validacao_nao_assina_laudo_verde_sobre_lote_sem_geometria():
    lots = extract_lots_from_info(_convert_output(2), "proj-1", "ver-1")
    summary = validate_lots(lots)
    assert summary["lot_count"] == 2
    assert summary["error_count"] == 0


def test_status_vira_vocabulario_do_banco():
    lots = extract_lots_from_info(_convert_output(3), "proj-1", "ver-1")
    assert [lot.status for lot in lots] == ["available", "sold", "reserved"]


def test_nome_quadra_e_area_sao_preservados():
    lot = extract_lots_from_info(_convert_output(1), "proj-1", "ver-1")[0]
    assert lot.name == "Q195-L001"
    assert lot.block == "Q195"
    assert lot.area_m2 == pytest.approx(178.86)


def test_external_id_e_unico_por_versao():
    lots = extract_lots_from_info(_convert_output(5), "proj-1", "ver-1")
    assert len({lot.external_id for lot in lots}) == 5


def test_area_aceita_formato_brasileiro_e_rejeita_lixo():
    assert _parse_area("1234,56 m²") == pytest.approx(1234.56)
    assert _parse_area("") is None
    assert _parse_area("sem numero") is None
    assert _parse_area(0) is None


def test_pontos_aceitam_lista_ou_string():
    assert _parse_points([[1, 2], [3, 4]]) == [[1.0, 2.0], [3.0, 4.0]]
    assert _parse_points("1,2 3,4") == [[1.0, 2.0], [3.0, 4.0]]
    assert _parse_points("") == []


def test_lista_vazia_nao_gera_lote_fantasma():
    assert extract_lots_from_info({"lotes": 0, "data": []}, "p", "v") == []
