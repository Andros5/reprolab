"""First divergence between two traces."""

from reprolab.diff import (
    DIFFERENT_CALL, DIFFERENT_REQUEST, LENGTH, SAME_REQUEST_DIFFERENT_OUTCOME, first_divergence,
)
from reprolab.events import Event


def call(seq, name, request, ok):
    return Event(seq=seq, type="call", name=name, kind="llm", request=request, outcome={"ok": ok})


BASE = [call(1, "ask", {"q": "move it?"}, {"intent": "book", "id": None}), call(2, "act", {"x": 1}, "done")]


def test_identical_traces_have_no_divergence():
    assert first_divergence(BASE, list(BASE)) is None


def test_same_request_different_answer_names_the_values():
    other = [call(1, "ask", {"q": "move it?"}, {"intent": "reschedule", "id": "a1"}), BASE[1]]
    d = first_divergence(BASE, other)
    assert (d.position, d.kind) == (0, SAME_REQUEST_DIFFERENT_OUTCOME)
    assert dict(zip(d.paths, d.values)) == {"/outcome/ok/id": (None, "a1"), "/outcome/ok/intent": ("book", "reschedule")}
    assert '/outcome/ok/intent: A "book"  /  B "reschedule"' in d.describe()


def test_different_request_and_different_call_and_length():
    d = first_divergence(BASE, [BASE[0], call(2, "act", {"x": 2}, "done")])
    assert (d.position, d.kind, d.paths) == (1, DIFFERENT_REQUEST, ("request/x",))
    assert first_divergence(BASE, [BASE[0], call(2, "other", {"x": 1}, "done")]).kind == DIFFERENT_CALL
    d = first_divergence(BASE, BASE[:1])
    assert (d.position, d.kind, d.a, d.b) == (1, LENGTH, BASE[1], None)
    assert "one trace ends" in d.describe()
