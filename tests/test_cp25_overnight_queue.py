"""Queue order and no silent source/scale substitution."""

from scripts.cp25_load import overnight_queue as queue


def test_before_profile_after_order_and_ram_floor():
    assert queue.plan("before") == [("before", n, False) for n in (10, 25, 50, 100, 500, 1000)] + [
        ("before", 25, True)
    ]
    assert queue.plan("after") == [("after", n, False) for n in (10, 25, 50, 100, 500, 1000)]
    assert not queue.admit(3071) and queue.admit(3072)


def test_queue_prerequisites_fail_closed():
    assert hasattr(queue, "prerequisites")
    state = {"phase": "ready", "readings": [{"streak": 2}]}
    assert queue.prerequisites(state, True, False, "before")
    assert queue.prerequisites(state, True, True, "after")
    assert not queue.prerequisites(state, False, True, "before")
    assert not queue.prerequisites(state, True, False, "after")
    assert not queue.prerequisites({**state, "phase": "expired"}, True, True, "before")
    assert not queue.prerequisites({**state, "readings": [{"streak": 1}]}, True, True, "before")


def test_uncertified_wrong_source_or_incomplete_delivery_is_rejected():
    data = {
        "shops": 2,
        "healthy_replies": 8,
        "expected_reminder_sends": 2,
        "expected_order_sends": 2,
        "telegram_uploads": 0,
        "worker": {"reminder_ticks": [{"sent": 2}], "order_ticks": [{"sent": 2}]},
        "runtime_provenance": {
            "executed_tree_sha256": "digest",
            "git_status_porcelain": "",
            "production_commit": queue.BEFORE,
            "database_revision": "a24d9e7b2c10",
        },
    }
    queue.verify(data, "before", 2)
    for changed in (
        {**data, "healthy_replies": 7},
        {**data, "runtime_provenance": {}},
        {
            **data,
            "runtime_provenance": {**data["runtime_provenance"], "production_commit": "wrong"},
        },
        {
            **data,
            "runtime_provenance": {
                **data["runtime_provenance"],
                "git_status_porcelain": " M src/change.py",
            },
        },
        {
            **data,
            "runtime_provenance": {**data["runtime_provenance"], "database_revision": "wrong"},
        },
        {**data, "telegram_uploads": 1},
        {**data, "worker": {"reminder_ticks": [{"sent": 1}], "order_ticks": [{"sent": 2}]}},
        {**data, "worker": {"reminder_ticks": [{"sent": 2}], "order_ticks": [{"sent": 1}]}},
    ):
        rejected = False
        try:
            queue.verify(changed, "before", 2)
        except AssertionError:
            rejected = True
        assert rejected, "Incomplete or uncertified measurements cannot enter a baseline"
