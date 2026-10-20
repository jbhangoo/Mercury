from database import bulk_load_cdr_records


def test_main_runs_each_day_from_repository_root_and_continues_after_failure(
    monkeypatch, capsys
):
    calls = []

    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    failed_day = bulk_load_cdr_records.DAYS[1].isoformat()

    def fake_run(command, *, cwd, check):
        calls.append((command, cwd, check))
        return Result(1 if command[3] == failed_day else 0)

    monkeypatch.setattr(bulk_load_cdr_records.subprocess, "run", fake_run)

    assert bulk_load_cdr_records.main() == 1

    assert [call[0][3] for call in calls] == [
        day.isoformat() for day in bulk_load_cdr_records.DAYS
    ]
    assert all(call[1] == bulk_load_cdr_records.REPOSITORY_ROOT for call in calls)
    assert all(call[2] is False for call in calls)
    assert all(call[0][-1] == str(bulk_load_cdr_records.OUTPUT_DIR) for call in calls)

    captured = capsys.readouterr()
    assert f"Uploading CDR records for {bulk_load_cdr_records.DAYS[0]}" in captured.out
    assert f"Uploading CDR records for {bulk_load_cdr_records.DAYS[-1]}" in captured.out
    assert f"{failed_day}: failed with exit code 1" in captured.err
    assert f"Bulk load failed for: {failed_day}" in captured.err
