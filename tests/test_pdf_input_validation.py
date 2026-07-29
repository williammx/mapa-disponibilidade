import io

import fitz
import pytest
from PIL import Image

from pdf_to_map import MapConversionError, convert


def test_raster_only_pdf_returns_a_clear_conversion_error(tmp_path):
    image = Image.new("RGB", (320, 220), (235, 235, 235))
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")

    pdf_path = tmp_path / "raster.pdf"
    output_path = tmp_path / "map.html"
    document = fitz.open()
    page = document.new_page(width=320, height=220)
    page.insert_image(page.rect, stream=image_bytes.getvalue())
    document.save(pdf_path)
    document.close()

    with pytest.raises(MapConversionError, match="imagem rasterizada"):
        convert(str(pdf_path), str(output_path))
