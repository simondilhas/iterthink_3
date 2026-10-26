"""Table components: a chart, a form that proposes one row, and the registry."""

from __future__ import annotations

import json
from pathlib import Path

from iterthink.services.bridge_real import RealBridge

JS = Path("iterthink/web/static/js")
CSV = "room,area\nHall,10\nStair,30\n"
ORIGINAL = "door,rating\nA,EI30\n"


def test_components_registered_in_components_json() -> None:
    loaded = json.loads((JS / "components.json").read_text(encoding="utf-8"))
    table = loaded["data-table"]["example"]
    chart = loaded["simple-chart"]["example"]
    form = loaded["form-fields"]["example"]
    assert "<data-table" in table
    assert "src=" in table
    assert "changed=" in table
    assert "<simple-chart" in chart
    assert 'type="bar"' in chart
    assert "<form-fields" in form
    assert "target=" in form
    assert "schema=" in form


def test_form_fields_submit_creates_proposal_not_write(tmp_path: Path, project_dir: Path) -> None:
    from iterthink.web.table_components import next_document

    doors = project_dir / "doors.csv"
    doors.write_text(ORIGINAL, encoding="utf-8")
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    proposed = next_document(ORIGINAL, ["door", "rating"], ["B", "EI90"], "csv")
    assert proposed == "door,rating\nA,EI30\nB,EI90\n"
    made = bridge.propose(project, {"doors.csv": proposed}, "user:ada", "add a door")
    assert made.status == "open"
    assert "doors.csv" in made.paths
    assert doors.read_text(encoding="utf-8") == ORIGINAL
    fresh = next_document("", ["door", "rating"], ["B", "EI90"], "csv")
    assert fresh == "door,rating\nB,EI90\n"
    glued = next_document("door,rating\nA,EI30", ["door", "rating"], ["B", "EI90"], "csv")
    assert glued.endswith("B,EI90\n")
    added = next_document('[{"door": "A"}]', ["door", "rating"], ["B", "EI90"], "json")
    assert json.loads(added)[-1] == {"door": "B", "rating": "EI90"}
    assert json.loads(next_document("", ["door"], ["B"], "json")) == [{"door": "B"}]
    wrapped = next_document('{"door": "A"}', ["rating"], ["EI90"], "json")
    assert json.loads(wrapped)[0] == {"door": "A"}
    assert json.loads(next_document("not-json", ["door"], ["B"], "json")) == [{"door": "B"}]
    assert json.loads(next_document("3", ["door"], ["B"], "json")) == [{"door": "B"}]
    script = (JS / "form-fields.js").read_text(encoding="utf-8")
    assert "propose" in script
    assert "writeFile" not in script


def test_simple_chart_renders_svg_from_csv() -> None:
    from iterthink.web.table_components import chart_svg

    bars = chart_svg(CSV, "bar", "room", "area")
    assert bars.startswith("<svg")
    assert bars.count("<rect") == 2
    assert "Hall" in bars
    assert "Stair" in bars
    line = chart_svg(CSV, "line", "room", "area")
    assert "<polyline" in line
    assert "Hall" in line
    assert "<rect" not in chart_svg("", "bar", "room", "area")
    zero = chart_svg("room,area\nHall,0\n", "line", "room", "area")
    assert "<polyline" in zero
    assert "Hall" in zero
    assert "<rect" in chart_svg("room,area\nHall,nope\n", "bar", "room", "area")


def test_js_files_are_ts_checked() -> None:
    for name in ("data-table.js", "simple-chart.js", "form-fields.js"):
        first = (JS / name).read_text(encoding="utf-8").splitlines()[0]
        assert first == "// @ts-check"
