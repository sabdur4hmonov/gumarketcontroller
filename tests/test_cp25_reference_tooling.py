"""Only new measurement prerequisites; no previously passed harness suite."""

import asyncio
import json
from types import SimpleNamespace

from scripts.cp25_load import reference_measure as reference


def test_worker_meter_preserves_task_pool_options(monkeypatch, tmp_path):
    from scripts.cp25_load import load_roles

    import gulbot.db.session as session_module
    from gulbot.worker import tasks

    options = []
    sentinel = object()

    def engine(database=None, **kwargs):
        options.append(kwargs)
        return sentinel

    def task():
        assert session_module.build_engine(task=True) is sentinel
        return {"sent": 0}

    monkeypatch.setattr(session_module, "build_engine", engine)
    monkeypatch.setattr(
        load_roles,
        "DbMeter",
        lambda value: SimpleNamespace(times_ms=[], peak_connections=0, peak_checked_out=0),
    )
    monkeypatch.setattr(load_roles, "install_local_api", lambda api: lambda: None)
    monkeypatch.setattr(tasks.send_due_reminders, "run", task)
    monkeypatch.setattr(tasks.send_order_pings, "run", task)
    error = None
    try:
        asyncio.run(load_roles.worker_role("http://127.0.0.1", tmp_path, 1))
    except TypeError as exc:
        error = str(exc)
    assert error is None, error
    assert options == [{"task": True}, {"task": True}]


def test_certificate_contains_status_and_hashes_source_and_harness(monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts/cp25_load").mkdir(parents=True)
    (tmp_path / "src/module.py").write_text("value=1", encoding="utf-8")
    script = tmp_path / "scripts/cp25_load/fixture.py"
    script.write_text("fixture=1", encoding="utf-8")
    monkeypatch.setattr(
        reference,
        "git",
        lambda root, *args: reference.BEFORE if args[0] == "rev-parse" else " M docs/status.md",
    )
    first = reference.provenance(tmp_path, "after")
    assert first.get("git_status_porcelain") == " M docs/status.md"
    assert "scripts/cp25_load/fixture.py" in first.get("executed_file_sha256", {})
    assert "src/module.py" in first.get("executed_file_sha256", {})
    script.write_text("fixture=2", encoding="utf-8")
    second = reference.provenance(tmp_path, "after")
    assert first["executed_tree_sha256"] != second["executed_tree_sha256"]


def test_dirty_before_harness_cannot_be_certified(monkeypatch, tmp_path):
    def git(root, *args):
        if args[0] == "rev-parse":
            return reference.BEFORE
        return " M scripts/cp25_load/fleet_api.py" if args == ("status", "--porcelain") else ""

    monkeypatch.setattr(reference, "git", git)
    rejected = False
    try:
        reference.provenance(tmp_path, "before")
    except ValueError:
        rejected = True
    assert rejected, "A changed reference harness is not the frozen before checkout"


def test_every_result_payload_keeps_the_runtime_certificate(tmp_path):
    assert hasattr(reference, "write_certified"), "Every result needs executed-source provenance"
    certificate = {
        "production_commit": reference.BEFORE,
        "executed_tree_sha256": "digest",
        "git_status_porcelain": "",
    }
    for payload in ({"shops": 2}, [{"shops": 2}]):
        path = tmp_path / "result.json"
        reference.write_certified(path, payload, certificate)
        found = json.loads(path.read_text(encoding="utf-8"))
        row = found[0] if isinstance(found, list) else found
        assert row.get("runtime_provenance") == certificate


def test_before_after_resources_are_disjoint():
    before, after = reference.resources("before"), reference.resources("after")
    assert before["POSTGRES_DB"] != after["POSTGRES_DB"]
    assert before["POSTGRES_TEST_DB"] != after["POSTGRES_TEST_DB"]
    assert {v for k, v in before.items() if k.startswith("REDIS_DB_")}.isdisjoint(
        {v for k, v in after.items() if k.startswith("REDIS_DB_")}
    )


def test_actual_database_revision_must_match_one_source_head():
    assert hasattr(reference, "checked_revision")
    assert reference.checked_revision(["old"], ["old"]) == "old"
    for actual, expected in (
        (["new"], ["old"]),
        (["old"], ["old", "other"]),
        (["old", "other"], ["old", "other"]),
        ([], []),
    ):
        rejected = False
        try:
            reference.checked_revision(actual, expected)
        except RuntimeError:
            rejected = True
        assert rejected, "Imported source and real DB schema must agree on a single head"
