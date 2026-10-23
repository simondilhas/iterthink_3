"""Table engine acceptance tests (slice A4)."""

from __future__ import annotations

import io

from openpyxl import Workbook

from iterthink.compare.engines import diff


def _xlsx(rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


def test_cell_change_by_key() -> None:
    before = b"id,name\n1,Ada\n2,Bea\n"
    after = b"id,name\n1,Ada Lovelace\n2,Bea\n"
    result = diff("people.csv", before, after)
    change = next(item for item in result.cell_changes if item.column == "name")
    assert change.row == "1"
    assert change.before == "Ada"
    assert change.after == "Ada Lovelace"


def test_row_added_removed() -> None:
    before = b"id,name\n1,Ada\n2,Bea\n"
    after = b"id,name\n1,Ada\n3,Cleo\n"
    result = diff("people.csv", before, after)
    assert any("Cleo" in row for row in result.added_rows)
    assert any("Bea" in row for row in result.removed_rows)


def test_column_added() -> None:
    before = b"id,name\n1,Ada\n"
    after = b"id,name,city\n1,Ada,Bern\n"
    result = diff("people.csv", before, after)
    assert "city" in result.columns
    assert any(item.column == "city" and item.after == "Bern" for item in result.cell_changes)


def test_tsv_and_xlsx() -> None:
    before = "id\tname\n1\tAda\n"
    after = "id\tname\n1\tBea\n"
    tsv = diff("people.tsv", before.encode(), after.encode())
    assert any(item.after == "Bea" for item in tsv.cell_changes)
    sheet_before = _xlsx([["id", "name"], ["1", "Ada"]])
    sheet_after = _xlsx([["id", "name"], ["1", "Bea"]])
    xlsx = diff("people.xlsx", sheet_before, sheet_after)
    assert any(item.after == "Bea" for item in xlsx.cell_changes)
