"""Stage S8 (decision D-28): direction items, the qualified-pool guard and label rows."""

import pytest

from viveka.coders import coding
from viveka.coders.base import Label, Missing
from viveka.coders.coding import CodingRefused, direction_items, label_rows, qualified_pool


def test_direction_items_show_claim_and_abstract_and_count_missing_abstracts():
    items, work_of, missing = direction_items("c1", "X works.", {"W2": "It  did\nnot.", "W1": None, "W3": ""})
    assert missing == 2
    assert [i.text for i in items] == ["Claim: X works.\n\nAbstract: It did not."]
    assert work_of == {items[0].item_id: "W2"}
    assert "W2" not in items[0].item_id and "c1" not in items[0].item_id
    again, _, _ = direction_items("c2", "X works.", {"W2": "It did not."})
    assert again[0].item_id != items[0].item_id  # the same work under another claim is another item


def test_label_rows_keep_each_coder_and_the_task_span():
    rows = label_rows("T7", "f-c", [Label("i1", "a", 0, "r", {"label": "for", "basis_span": "found"}),
                                    Missing("i2", "b", 0, "r", "absent")], {"i1": "W1", "i2": "W2"})
    assert rows[0] | {} == {"task": "T7", "subject": "f-c", "item_id": "i1", "work_id": "W1", "coder_id": "a",
                            "rep": 0, "label": "for", "span": "found", "missing": None}
    assert rows[1]["label"] is None and rows[1]["missing"] == "absent"
    stance = label_rows("T1", "f-c", [Label("i3", "a", 0, "r", {"label": "x", "reason_span": "small"})], {})
    assert stance[0]["span"] == "small" and stance[0]["work_id"] is None


def _audit(run_id, *, instrument="i1", thresholds="t1", version="v1", qualifies=True):
    return {"run_id": run_id, "stage": "S7-audits", "fold": "dev", "status": "ok",
            "registry": {"components": {"instrument": instrument, "thresholds": thresholds, "prompts": "p-old"}},
            "params": {"task_version": version, "result": {"pool_qualifies": qualifies, "qualified": ["a", "b"]}}}


def test_qualified_pool_takes_the_newest_audit_under_the_current_instrument(monkeypatch, tmp_path):
    runs = [_audit("new-other", instrument="i2"), _audit("ok"), _audit("old", qualifies=False)]
    monkeypatch.setattr("viveka.provenance.recent_runs", lambda root, limit: runs)
    current = {"instrument": "i1", "thresholds": "t1", "prompts": "p-new"}
    assert qualified_pool(tmp_path, "dev", current, "v1")["run_id"] == "ok"
    with pytest.raises(CodingRefused):
        qualified_pool(tmp_path, "dev", current, "v2")
    runs.insert(1, _audit("failed", qualifies=False))
    with pytest.raises(CodingRefused, match="does not qualify"):
        qualified_pool(tmp_path, "dev", current, "v1")


def test_tasks_are_registered_prompts():
    assert coding.TASKS == {"T7": "T7-direction", "T1": "T1-stance"}
