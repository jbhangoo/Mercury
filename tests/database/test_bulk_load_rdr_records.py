import pytest

from database import bulk_load_rdr_records


def test_main_runs_each_day_with_rerun_and_continues_after_failure(monkeypatch, capsys):
    calls = []

    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    failed_day = bulk_load_rdr_records.DAYS[1].isoformat()

    def fake_run(command, *, cwd, check):
        calls.append((command, cwd, check))
        return Result(1 if command[3] == failed_day else 0)

    monkeypatch.setattr(bulk_load_rdr_records.subprocess, "run", fake_run)

    assert bulk_load_rdr_records.main(["--rerun"]) == 1

    assert [call[0][3] for call in calls] == [day.isoformat() for day in bulk_load_rdr_records.DAYS]
    assert all(call[0][-1] == "--rerun" for call in calls)
    assert all(call[1] == bulk_load_rdr_records.REPOSITORY_ROOT for call in calls)
    assert all(call[2] is False for call in calls)

    captured = capsys.readouterr()
    assert f"Uploading RDR records for {bulk_load_rdr_records.DAYS[0]}" in captured.out
    assert f"Uploading RDR records for {bulk_load_rdr_records.DAYS[-1]}" in captured.out
    assert f"{failed_day}: failed with exit code 1" in captured.err
    assert f"Bulk load failed for: {failed_day}" in captured.err


def test_main_rejects_unknown_options():
    with pytest.raises(SystemExit) as exc_info:
        bulk_load_rdr_records.main(["--unknown"])

    assert exc_info.value.code == 2
