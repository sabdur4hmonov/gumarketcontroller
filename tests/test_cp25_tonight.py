"""No heavy process may start under the precheck; runtime cleanup is owned."""

from __future__ import annotations

from unittest.mock import Mock

from scripts.cp25_load import tonight


def test_tonight_precheck_records_refusal_without_launch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tonight, "available_mib", lambda: 2048)
    notes = []
    monkeypatch.setattr(tonight, "note", notes.append)
    launch = Mock(side_effect=AssertionError("Heavy process was launched"))
    monkeypatch.setattr(tonight.subprocess, "Popen", launch)
    refused = False
    try:
        tonight.job("baseline", ["python"], cwd=tmp_path, output=tmp_path, environment={})
    except RuntimeError:
        refused = True
    assert refused and len(notes) == 1, "Reject once and record; never retry"
    launch.assert_not_called()


def test_finished_child_is_never_killed(monkeypatch) -> None:
    child = Mock()
    child.poll.return_value = 0
    kill = Mock()
    monkeypatch.setattr(tonight.subprocess, "run", kill)
    tonight.stop_owned(child)
    kill.assert_not_called()


def test_runtime_floor_stops_only_the_returned_child(monkeypatch, tmp_path) -> None:
    values = iter([4096, 500])
    monkeypatch.setattr(tonight, "available_mib", lambda: next(values))
    child = Mock()
    child.pid = 9001234
    child.poll.side_effect = [None, 0]
    child.returncode = 0
    monkeypatch.setattr(tonight.subprocess, "Popen", Mock(return_value=child))
    stop = Mock()
    monkeypatch.setattr(tonight, "stop_owned", stop)
    monkeypatch.setattr(tonight.time, "sleep", lambda _: None)
    notes = []
    monkeypatch.setattr(tonight, "note", notes.append)
    refused = False
    try:
        tonight.job("runtime", ["fake"], cwd=tmp_path, output=tmp_path, environment={})
    except RuntimeError:
        refused = True
    assert refused and len(notes) == 1, "A RAM-aborted job must not return success"
    assert stop.call_args_list and all(call.args == (child,) for call in stop.call_args_list)
