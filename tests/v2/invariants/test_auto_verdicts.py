"""An automatic verdict only covers a class the program can see for itself."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from iterthink.compare.change_classes import classify
from iterthink.services.agent_rules import Rules, decide
from iterthink.services.bridge import FileDiff

_TEXT = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=512), max_size=24)
_DETERMINISTIC = frozenset({"whitespace", "spelling", "typography"})
_RULES = Rules(
    default="propose",
    direct=("**/*.md:typos",),
    deny=(),
    propose_always=(),
    deletions="propose",
)


@given(before=_TEXT, after=_TEXT)
def test_auto_never_applies_non_deterministic_classes(before: str, after: str) -> None:
    raw_before = before.encode("utf-8")
    raw_after = after.encode("utf-8")
    classes = classify("note.md", raw_before, raw_after)
    change = FileDiff("note.md", "text", "changed", details={"classes": sorted(classes)})
    choice = decide(_RULES, "agent:checker", "note.md", change, False)
    if choice.action == "direct":
        assert classes
        assert classes <= _DETERMINISTIC
        assert choice.rule_id == "**/*.md:typos"
