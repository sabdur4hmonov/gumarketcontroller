"""Pure admission/startup guards only; no large run or infrastructure boot."""

from contextlib import suppress

from scripts.cp25_load import reference_measure as reference


def test_after_requires_review_of_this_profile_and_current_source(monkeypatch, tmp_path):
    import hashlib
    import importlib.util
    import json

    assert importlib.util.find_spec("scripts.cp25_load.evening") is not None
    from scripts.cp25_load import evening

    profile = tmp_path / "profile.json"
    profile.write_text("actual-profile", encoding="utf-8")
    review = tmp_path / "review.json"
    monkeypatch.setattr(
        evening, "provenance", lambda source, phase: {"executed_tree_sha256": "current"}
    )
    data = {
        "status": "reviewed",
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "after_tree_sha256": "current",
        "attribution": "explicit reviewed evidence",
    }
    review.write_text(json.dumps(data), encoding="utf-8")
    assert evening.profile_approved(review, profile)
    for changed in (
        {**data, "profile_sha256": "wrong"},
        {**data, "after_tree_sha256": "old"},
        {**data, "status": "pending"},
        {**data, "attribution": ""},
    ):
        review.write_text(json.dumps(changed), encoding="utf-8")
        assert not evening.profile_approved(review, profile)


def test_small_peak_margin_never_lowers_large_scale_floor():
    assert hasattr(reference, "scale_gate")
    assert reference.scale_gate(10, None) == 3072
    assert reference.scale_gate(25, 1500.1) == 2525
    assert reference.scale_gate(50, 2200) == 3224
    for shops in (100, 500, 1000):
        assert reference.scale_gate(shops, 1) == 3072
    for peak in (-1, float("nan"), float("inf")):
        rejected = False
        try:
            reference.scale_gate(10, peak)
        except ValueError:
            rejected = True
        assert rejected, "Unknown/invalid peaks cannot reduce an admission guard"


def test_startup_seed_never_runs_a_capacity_scale():
    assert hasattr(reference, "seed_startup")
    calls = []
    reference.seed_startup(2, calls.append)
    assert calls == [2]
    for scale in (10, 100, 1000):
        rejected = False
        try:
            reference.seed_startup(scale, calls.append)
        except ValueError:
            rejected = True
        assert rejected and calls == [2]


def test_startup_refusal_never_launches_a_process(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from scripts.cp25_load import startup_audit

    calls, records = [], []
    monkeypatch.setattr(startup_audit, "snapshot", lambda label: {"label": label, "free_mib": 1279})
    monkeypatch.setattr(startup_audit, "note", lambda message: None)

    def launched(*a, **kw):
        calls.append(a)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(startup_audit.subprocess, "run", launched)
    assert not startup_audit.step("fake", ["never"], records, tmp_path)
    assert calls == [] and records[-1]["status"] == "waiting for RAM"


def test_evening_large_scale_admission_cannot_use_small_peak(monkeypatch, tmp_path):
    from scripts.cp25_load import evening

    calls = []
    monkeypatch.setattr(evening, "available_mib", lambda: 3071)
    monkeypatch.setattr(evening, "note", lambda message: None)

    def forbidden(*a, **kw):
        calls.append(a)
        raise ValueError("Launch would violate the admission rule")

    monkeypatch.setattr(evening.subprocess, "Popen", forbidden)
    row = None
    with suppress(ValueError):
        row = evening.run_one("before", 100, False, tmp_path, {100: 1})
    assert calls == [] and row and row["status"] == "not run: RAM"
    assert row["required_mib"] == 3072


def test_evening_prepares_infrastructure_before_fresh_admission(monkeypatch, tmp_path):
    from scripts.cp25_load import evening

    events = []
    monkeypatch.setattr(evening, "ROOT", tmp_path)
    monkeypatch.setattr(evening.queue, "STAGE", evening.queue.STAGE)
    monkeypatch.setattr(evening, "provenance", lambda *a: {})
    monkeypatch.setattr(evening, "pending_guards", lambda: [])
    monkeypatch.setattr(evening, "note", lambda message: None)
    monkeypatch.setattr(
        evening, "prepare", lambda *a, **kw: events.append("infrastructure") or True
    )
    monkeypatch.setattr(evening, "available_mib", lambda: events.append("ram") or 3071)
    monkeypatch.setattr(evening, "run_stage", lambda *a: events.append("BAD stage"))
    with suppress(SystemExit, TypeError):
        evening.main()
    assert events == ["infrastructure", "ram"], "No stage before fresh post-infrastructure RAM"


def test_evening_main_never_starts_after_without_actual_profile_review(monkeypatch, tmp_path):
    from scripts.cp25_load import evening

    stages = []
    monkeypatch.setattr(evening, "ROOT", tmp_path)
    monkeypatch.setattr(evening.queue, "STAGE", evening.queue.STAGE)
    monkeypatch.setattr(evening, "provenance", lambda *a: {})
    monkeypatch.setattr(evening, "pending_guards", lambda: [])
    monkeypatch.setattr(evening, "note", lambda message: None)
    monkeypatch.setattr(evening, "prepare", lambda *a, **kw: True)
    monkeypatch.setattr(evening, "available_mib", lambda: 4000)
    monkeypatch.setattr("builtins.input", lambda message: "")

    def stage(name, *a):
        stages.append(name)
        return {"rows": [{"status": "measured"}]}

    monkeypatch.setattr(evening, "run_stage", stage)
    with suppress(SystemExit):
        evening.main()
    assert stages == ["before"], "A profile file and its certified source review are mandatory"
