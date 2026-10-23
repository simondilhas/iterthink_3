"""Paragraph-level compare: alignment, layout, diff spans, semantics, slot labels.

Submodules (import explicitly to avoid circular loads in ``__init__``):

- ``margin`` — paragraph splitting and editor–margin geometry
- ``judge`` — semantic tie-break (STABLE / NEW, rewritten / major)
- ``paragraph_align`` — TF-IDF alignment vs saved text
- ``paragraph_semantics`` — embeddings and stability signals
- ``paragraph_compare`` — slot kinds and async LLM refinement
- ``layout`` — paired rows for History / Review compare UI
"""
