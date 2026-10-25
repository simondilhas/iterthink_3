"""Page images for a plan, cached once per version."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from iterthink.services.plan_render import page_image


def _pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_page_image_cached_per_version(tmp_path: Path) -> None:
    data = _pdf("EI30")
    cache = tmp_path / "cache"
    first = page_image(data, 1, "v1", cache)
    stamp = first.stat().st_mtime_ns
    body = first.read_bytes()
    again = page_image(data, 1, "v1", cache)
    assert again == first
    assert again.stat().st_mtime_ns == stamp
    assert again.read_bytes() == body
    assert body.startswith(b"\x89PNG\r\n\x1a\n")
    other = page_image(data, 1, "v2", cache)
    assert other != first
    assert other.is_file()
    assert other.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
