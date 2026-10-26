"""Delivery files. Markdown becomes Word or PDF. CSV becomes Excel."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from openpyxl import Workbook

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge import ExportInfo, Invalid, NotFound, ProposalInfo, kind_of
from iterthink.services.markdown_docx_export import (
    ExportMeta,
    bundled_templates_dir,
    markdown_to_docx,
)
from iterthink.services.projects import inside, relative

_Format = Literal["docx", "xlsx", "pdf", "csv"]
_FORMATS = ("docx", "xlsx", "pdf", "csv")
_TEXT = {"markdown", "text"}


class _Host(Protocol):
    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo: ...


class DeliverBridge:
    """`export` and `import_returned` for the real bridge."""

    def export(
        self, project: str, path: str, format: str, template: str | None = None
    ) -> ExportInfo:
        return write_export(cast(_Host, self), project, path, format, template)

    def import_returned(
        self, project: str, returned: Path, source: str, actor: str
    ) -> ProposalInfo:
        from iterthink.services.returned import take_back

        return take_back(cast(_Host, self), project, returned, source, actor)


def write_export(
    host: _Host, project: str, path: str, format: str, template: str | None
) -> ExportInfo:
    """Write one delivery file and record which source version it came from."""
    root = host._root(project)
    rel = relative(path)
    source = _read(inside(root, rel), rel)
    chosen = _format(format)
    _matches(rel, chosen)
    version = Snapshots(root).head().id
    dest_rel = _dest(rel, version, chosen)
    dest = root / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    _render(chosen, source, rel, inside(root, rel), dest, template)
    host._event(root, project, "user:local", "export", _payload(dest_rel, rel, version, chosen))
    return ExportInfo(path=dest_rel, source_version=version, format=chosen)


def _format(format: str) -> _Format:
    chosen = format.strip().lower()
    if chosen not in _FORMATS:
        raise Invalid("format is docx, xlsx, pdf or csv")
    return cast(_Format, chosen)


def _matches(rel: str, chosen: str) -> None:
    kind = kind_of(rel)
    suffix = Path(rel).suffix.lower()
    text = chosen in {"docx", "pdf"} and kind in _TEXT
    table = chosen in {"xlsx", "csv"} and suffix == ".csv"
    if not text and not table:
        raise Invalid(f"{rel} cannot be delivered as {chosen}")


def _read(full: Path, rel: str) -> str:
    if not full.is_file():
        raise NotFound(f"no file {rel}")
    return full.read_text(encoding="utf-8")


def _dest(rel: str, version: str, chosen: str) -> str:
    return f".iterthink/exports/{Path(rel).stem}-{version[:12]}.{chosen}"


def _payload(dest: str, source: str, version: str, chosen: str) -> dict[str, object]:
    return {
        "format": chosen,
        "path": dest,
        "relation": "derived_from",
        "source": source,
        "source_version": version,
    }


def _render(
    chosen: str, source: str, rel: str, full: Path, dest: Path, template: str | None
) -> None:
    if chosen == "docx":
        _docx(source, rel, full, dest, template)
    elif chosen == "xlsx":
        _xlsx(source, dest)
    elif chosen == "pdf":
        dest.write_bytes(_pdf(source))
    else:
        dest.write_text(source, encoding="utf-8")


def _docx(source: str, rel: str, full: Path, dest: Path, template: str | None) -> None:
    chosen = _template(template)
    meta = ExportMeta(
        title_stem=Path(rel).stem,
        author="user:local",
        date_iso=datetime.now(UTC).date().isoformat(),
    )
    markdown_to_docx(
        markdown_src=source,
        md_path=full,
        template_path=chosen,
        output_path=dest,
        meta=meta,
    )


def _template(template: str | None) -> Path:
    chosen = Path(template) if template else bundled_templates_dir() / "Iterthink Standard.docx"
    if not chosen.is_file():
        raise NotFound(f"no template at {chosen}")
    return chosen


def _xlsx(source: str, dest: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "Export"
    for row in csv.reader(io.StringIO(source)):
        sheet.append(row)
    book.save(dest)


def _pdf(text: str) -> bytes:
    lines = text.replace("\r\n", "\n").split("\n")
    stream = _stream(lines[:48])
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n",
        _page(),
        _content(stream),
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>endobj\n",
    ]
    return _assemble(objects)


def _content(stream: bytes) -> bytes:
    length = str(len(stream)).encode("ascii")
    return b"4 0 obj<</Length " + length + b">>stream\n" + stream + b"\nendstream\nendobj\n"


def _page() -> bytes:
    return (
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    )


def _stream(lines: list[str]) -> bytes:
    chunks = ["BT /F1 11 Tf 72 740 Td 14 TL"]
    for index, line in enumerate(lines):
        if index:
            chunks.append("T*")
        chunks.append(f"({_escape(line)}) Tj")
    chunks.append("ET")
    return "\n".join(chunks).encode("latin-1", errors="replace")


def _escape(line: str) -> str:
    encoded = line.encode("latin-1", errors="replace").decode("latin-1")
    return encoded.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble(objects: list[bytes]) -> bytes:
    header = b"%PDF-1.4\n"
    cursor = len(header)
    offsets: list[int] = []
    for item in objects:
        offsets.append(cursor)
        cursor += len(item)
    xref = _xref(offsets, cursor)
    return header + b"".join(objects) + xref


def _xref(offsets: list[int], start: int) -> bytes:
    rows = ["xref", f"0 {len(offsets) + 1}", "0000000000 65535 f "]
    rows.extend(f"{offset:010d} 00000 n " for offset in offsets)
    rows.append(f"trailer<</Size {len(offsets) + 1}/Root 1 0 R>>")
    rows.append(f"startxref\n{start}")
    rows.append("%%EOF")
    return "\n".join(rows).encode("ascii") + b"\n"
