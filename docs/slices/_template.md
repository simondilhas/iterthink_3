```
id: Sxx
status: draft
depends_on: []
```
# Sxx · <title>

**Goal:** <one sentence a user would recognise>

**Spec sections:** <headings in iterthink-2.mdc to read>

## Scope
- `iterthink/...` — <what>
- `tests/v2/...` — <what>
- `scripts/strict_paths.d/Sxx.txt` — the new modules

## Out of scope
- <tempting neighbour, and which slice owns it>

## Interface
```python
def example(project_dir: Path, ...) -> Result: ...
```

## Decided for you
- <format, naming, error behaviour, edge case>

## Acceptance (tests first)
- [ ] `test_<behaviour>` — <what it proves>
- [ ] property: `test_<invariant>` — <invariant number from 10-testing.mdc>

## Done when
All acceptance tests pass and `scripts/check.py --full` is green.
