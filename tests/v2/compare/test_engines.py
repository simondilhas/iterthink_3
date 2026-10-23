"""Registry and the cases every engine shares (slice A4)."""

from __future__ import annotations

import io
import re

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from iterthink.compare.engines import diff

_VCS = re.compile(
    r"\b(commit|commits|branch|branches|rebase|bookmark|repository|checkout|jj|git)\b",
    re.I,
)


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


def test_registry_dispatches_by_kind() -> None:
    assert diff("note.md", b"old", b"new").kind == "text"
    assert diff("t.csv", b"id,n\n1,a\n", b"id,n\n1,b\n").kind == "table"
    assert diff("plan.pdf", _pdf("EI30"), _pdf("EI90")).kind == "plan"


def test_unknown_kind_is_binary() -> None:
    result = diff("scan.bin", b"a", b"b")
    assert result.kind == "binary"
    assert result.summary == "file changed"


def test_identical_is_none() -> None:
    result = diff("note.md", b"same", b"same")
    assert result.kind == "none"
    assert result.summary == "no changes"


def test_new_file_is_all_added() -> None:
    result = diff("note.md", None, b"One.\n\nTwo.")
    assert result.kind == "text"
    assert [block.kind for block in result.blocks] == ["added", "added"]
    assert [block.after for block in result.blocks] == ["One.", "Two."]


def test_deleted_file_is_all_removed() -> None:
    result = diff("note.md", b"One.\n\nTwo.", None)
    assert [block.kind for block in result.blocks] == ["removed", "removed"]
    assert [block.before for block in result.blocks] == ["One.", "Two."]


def test_summaries_have_no_vcs_words() -> None:
    samples = [
        diff("note.md", b"old word", b"new word"),
        diff("note.md", None, b"Added.\n\nMore."),
        diff("note.md", b"Gone.\n\nStay.", None),
        diff("t.csv", b"id,name\n1,Ada\n", b"id,name\n1,Ada Lovelace\n2,Bea\n"),
        diff("plan.pdf", _pdf("EI30"), _pdf("EI90")),
        diff("scan.bin", b"a", b"b"),
        diff("note.md", b"same", b"same"),
    ]
    for result in samples:
        assert _VCS.search(result.summary) is None
