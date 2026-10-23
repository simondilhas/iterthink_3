"""Plan engine acceptance test (slice A4)."""

from __future__ import annotations

import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from iterthink.compare.engines import diff


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


def test_plan_text_change_has_page_and_bbox() -> None:
    result = diff("plan.pdf", _pdf("EI30"), _pdf("EI90"))
    assert result.kind == "plan"
    changes = result.details["changes"]
    assert isinstance(changes, list)
    assert len(changes) == 1
    change = changes[0]
    assert isinstance(change, dict)
    assert change["page"] == 1
    assert change["before"] == "EI30"
    assert change["after"] == "EI90"
    bbox = change["bbox"]
    assert isinstance(bbox, list)
    assert len(bbox) == 4
    assert all(isinstance(value, float) and 0.0 <= value <= 1.0 for value in bbox)
    pages = result.details["pages"]
    assert pages == [1]
