from elevator_control.simulator.audit import AuditLog


def test_spill_retains_full_history_and_bounded_tail_updates():
    log = AuditLog(max_bytes=128, tail_size=2)
    for i in range(20):
        log.append({"sequence": i, "payload": "真实记录" * 10})
    assert log.spilled and len(log) == 20
    assert log[-2:] == [{"sequence": i, "payload": "真实记录" * 10} for i in [18, 19]]
    log.update_last({"inference_ms": 1.2})
    records = list(log)
    assert [r["sequence"] for r in records] == list(range(20))
    assert records[-1]["inference_ms"] == 1.2
    log.append({"sequence": 20})
    assert [r["sequence"] for r in log] == list(range(21))
    log.close()
