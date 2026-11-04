from database import pds_bulk_load_month


def test_main_accepts_zero_padded_month_and_includes_leap_day(monkeypatch):
    calls = []

    class Result:
        returncode = 0

    def fake_run(command, *, cwd, check):
        calls.append((command, cwd, check))
        return Result()

    monkeypatch.setattr(pds_bulk_load_month.subprocess, "run", fake_run)

    assert pds_bulk_load_month.main(["2016", "02", "cdr"]) == 0

    days = [call[0][3] for call in calls]
    assert len(days) == 29
    assert days[0] == "2016-02-01"
    assert days[-1] == "2016-02-29"
    assert all(call[1] == pds_bulk_load_month.REPOSITORY_ROOT for call in calls)
    assert all(call[2] is False for call in calls)
