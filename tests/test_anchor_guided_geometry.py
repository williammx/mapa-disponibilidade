import pymupdf
from shapely.geometry import Point

from pdf_to_map import (
    _anchor_guided_lots_from_segments,
    _geometry_only_segments,
    _is_auxiliary_geometry_layer,
)


def _rectangle_segments(x0, y0, x1, y1):
    return [
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ]


def test_anchor_guided_extraction_discards_unlabelled_faces():
    segments = []
    segments.extend(_rectangle_segments(0, 0, 10, 10))
    segments.extend(_rectangle_segments(10, 0, 20, 10))
    segments.extend(_rectangle_segments(20, 0, 30, 10))

    lots = _anchor_guided_lots_from_segments(
        segments, [Point(5, 5), Point(15, 5)], 20, 200,
        snap_candidates=(None,),
    )

    assert len(lots) == 2
    assert all(lot.area == 100 for lot in lots)


def test_anchor_guided_extraction_closes_small_cad_gap():
    segments = [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 10)),
        ((10, 10), (0, 10)),
        ((0, 10), (0, 0.2)),
    ]

    lots = _anchor_guided_lots_from_segments(
        segments, [Point(5, 5)], 20, 200,
        snap_candidates=(None, 0.5),
    )

    assert len(lots) == 1
    assert lots[0].covers(Point(5, 5))


def test_geometry_pass_ignores_annotation_layers():
    class FakePage:
        def get_drawings(self, extended=False):
            return [
                {
                    "layer": "BASE 2024",
                    "items": [("l", pymupdf.Point(0, 0), pymupdf.Point(10, 0))],
                },
                {
                    "layer": "SETORES$0$6_block_id_label",
                    "items": [("l", pymupdf.Point(0, 5), pymupdf.Point(10, 5))],
                },
                {
                    "layer": "CL_SIMBOLOS",
                    "items": [("l", pymupdf.Point(5, 0), pymupdf.Point(5, 10))],
                },
            ]

    assert _is_auxiliary_geometry_layer("TXT_LOTES_NUMERACAO")
    assert _is_auxiliary_geometry_layer("6_block_id_label")
    assert _is_auxiliary_geometry_layer("CL_SIMBOLOS")
    assert not _is_auxiliary_geometry_layer("BASE 2024")
    assert _geometry_only_segments(FakePage()) == [((0.0, 0.0), (10.0, 0.0))]
