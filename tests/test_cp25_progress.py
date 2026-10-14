"""Stop failed idle tails; never turn incomplete delivery into a passing row."""

import importlib.util
from contextlib import suppress


def test_stall_requires_finished_worker_missing_unique_replies_and_no_recent_progress():
    assert importlib.util.find_spec("scripts.cp25_load.progress") is not None
    from scripts.cp25_load.progress import stalled_replies

    now = 200_000_000_000
    old = {"bot_id": 1, "chat_id": 10, "role": "customer", "received_ns": 1_000_000_000}
    other = {"bot_id": 1, "chat_id": 20, "role": "other", "received_ns": 199_000_000_000}
    stats = {"replies": [old, old, other]}
    assert stalled_replies(stats, 2, now, 0, worker_finished=True) == 1
    assert stalled_replies(stats, 2, now, 0, worker_finished=False) is None
    assert stalled_replies(stats, 1, now, 0, worker_finished=True) is None
    assert stalled_replies(stats, 2, 100_000_000_000, 0, worker_finished=True) is None
    recent = {**old, "received_ns": 190_000_000_000}
    assert stalled_replies({"replies": [recent]}, 2, now, 0, worker_finished=True) is None
    assert stalled_replies({"replies": []}, 2, now, 150_000_000_000, worker_finished=True) is None


def test_stage_records_failed_row_before_leaving_the_controller(monkeypatch, tmp_path):
    import json

    from scripts.cp25_load import evening

    monkeypatch.setattr(evening.queue, "plan", lambda stage: [("after", 10, False)])
    monkeypatch.setattr(evening.queue, "publish_tables", lambda: None)
    monkeypatch.setattr(evening, "note", lambda message: None)
    monkeypatch.setattr(evening, "ROOT", tmp_path)

    def failed(*args):
        args[-1].update(precheck_free_mib=3210)
        raise RuntimeError("incomplete workload")

    monkeypatch.setattr(evening, "run_one", failed)
    with suppress(RuntimeError):
        evening.run_stage("after", tmp_path, {})
    ledger = json.loads((tmp_path / "after-ledger.json").read_text(encoding="utf-8"))
    row = ledger["rows"][0] if ledger["rows"] else {}
    assert row.get("status") == "failed", "A failed attempted scale must remain in the ledger"
    assert row.get("shops") == 10 and ledger["phase"] == "failed"
    assert row.get("precheck_free_mib") == 3210


def test_supervisor_stops_stalled_child_as_failure(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from scripts.cp25_load import evening

    child = SimpleNamespace(pid=123, returncode=None)
    child.poll = lambda: child.returncode
    stopped = []

    def stop(process):
        if process.returncode is None:
            stopped.append(process.pid)
            process.returncode = 1

    def sleep(seconds):
        raise RuntimeError("stall guard skipped")

    clock = iter([0, 0, 20, 20, 20])
    monkeypatch.setattr(evening, "available_mib", lambda: 4096)
    monkeypatch.setattr(evening, "note", lambda message: None)
    monkeypatch.setattr(evening.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(evening, "stop_owned", stop)
    monkeypatch.setattr(evening.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(evening.time, "sleep", sleep)
    monkeypatch.setattr(
        evening,
        "inspect_stall",
        lambda *args: {"successful_replies": 99, "expected_replies": 100, "runtime_provenance": {}},
    )
    error = None
    try:
        evening.run_one("after", 25, False, tmp_path, {})
    except RuntimeError as failed:
        error = str(failed)
    assert error and "FAILED" in error, "Stalled delivery must be a failure, never a passing row"
    assert stopped == [123]
    assert (tmp_path / "after-25-stalled.json").is_file()


def test_progress_observer_is_local_and_has_a_bounded_request(monkeypatch, tmp_path):
    import io
    import json

    from scripts.cp25_load import progress

    (tmp_path / "worker-metrics.json").write_text(
        json.dumps({"runtime_provenance": {"kind": "test fixture"}}), encoding="utf-8"
    )
    api = tmp_path / "api-ready.json"
    calls = []

    def read(url, **kwargs):
        calls.append((url, kwargs))
        return io.StringIO(json.dumps({"replies": []}))

    monkeypatch.setattr(progress, "urlopen", read)
    monkeypatch.setattr(progress.time, "perf_counter_ns", lambda: 200_000_000_000)
    api.write_text(json.dumps({"url": "https://example.invalid"}), encoding="utf-8")
    rejected = False
    try:
        progress.inspect_stall(tmp_path, 1, 0)
    except ValueError:
        rejected = True
    assert rejected and calls == [], "Never inspect a foreign API"
    api.write_text(json.dumps({"url": "http://127.0.0.1:1234"}), encoding="utf-8")
    assert progress.inspect_stall(tmp_path, 1, 0)["successful_replies"] == 0
    assert calls == [("http://127.0.0.1:1234/control/stats", {"timeout": 1})]


def test_failed_progress_preserves_role_records_and_actual_idle_age(monkeypatch, tmp_path):
    import io
    import json

    from scripts.cp25_load import progress

    stats = {
        "replies": [{"bot_id": 1, "chat_id": 3, "role": "customer", "received_ns": 1_000_000_000}],
        "calls": {"sendMessage": 1},
        "polled_shops": 1,
    }
    (tmp_path / "worker-metrics.json").write_text(
        json.dumps({"runtime_provenance": {"commit": "fixture"}})
    )
    (tmp_path / "api-ready.json").write_text(json.dumps({"url": "http://127.0.0.1:1234"}))
    monkeypatch.setattr(progress, "urlopen", lambda *a, **kw: io.StringIO(json.dumps(stats)))
    monkeypatch.setattr(progress.time, "perf_counter_ns", lambda: 201_000_000_000)
    record = progress.inspect_stall(tmp_path, 1, 0)
    assert record.get("api_stats") == stats, (
        "Keep the real role/delivery evidence before stopping API"
    )
    assert record.get("actual_no_progress_seconds") == 200
    assert record.get("runtime_provenance") == {"commit": "fixture"}
