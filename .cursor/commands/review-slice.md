# Review a finished slice (run in a fresh session)

You did not write this code. Review the branch against its slice file:

1. Does every acceptance item have a test that would fail without the change?
   Try mentally reverting the implementation; name any test that would still pass.
2. Are any tests skipped, weakened, or asserting implementation details
   instead of behaviour?
3. Is anything outside the slice's scope list changed?
4. Check against `AGENTS.md` → Never, and the Known traps.
5. Any undocumented design choice? It belongs in `docs/decisions.md` → Proposed.

Output: blocking issues, then non-blocking, each with file:line. No praise.
