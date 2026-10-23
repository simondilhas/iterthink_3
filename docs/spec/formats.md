# Formats: work open, deliver closed
- Working files and app outputs are open formats only: CSV (tables),
  Markdown (text), JSON (structured data), GLB (geometry previews).
- DOCX, XLSX and PDF are delivery exports, generated from an open file on
  request, stored under `<project>/.iterthink/exports/` unless the user picks a location, never edited, never the source.
  Each export records which version of which source it came from.
- Incoming DOCX, XLSX and PDF from others are inputs: the original is kept
  as received (versioned, compared as-is) and imported into an open working
  copy (MD / CSV) when the user works on it. Plans (PDF) stay PDF.

# Format engines
One engine per format, registered by file extension in `compare/engines.py`.
Every engine returns `ContentChange` rows plus a render payload; the review
screen picks the fragment by `kind`.

```python
class FormatEngine(Protocol):
    extensions: tuple[str, ...]
    kind: Literal["text", "table", "plan", "model", "image"]
    def diff(self, old: Path, new: Path, ctx: CompareContext) -> EngineResult: ...
    def summarize(self, result: EngineResult) -> str: ...  # plain language, no LLM
```

| Kind  | Extensions          | Engine                                         | Subject / path              |
|-------|---------------------|------------------------------------------------|-----------------------------|
| text  | .md .txt .docx      | existing `compare/` pipeline                   | paragraph id / paragraph n  |
| table | .csv .xlsx          | daff (new dependency); xlsx via openpyxl → CSV | row key / column name       |
| plan  | .pdf                | existing `services/plan_text_diff`             | page n / bbox               |
| model | .ifc                | IfcOpenShell, by GlobalId                      | GlobalId / Pset.Property    |
| image | .png .jpg           | before/after, pixel diff                       | file / region               |

Semantic judgment (embedding bands, LLM tie-break, impact checks) runs on top of
any engine's rows, not inside the engines.
