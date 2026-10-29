from __future__ import annotations

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from notibot.scheduler import BotScheduler


def test_scheduler_builds_jobs_in_bolivia_timezone() -> None:
    settings = SimpleNamespace(
        timezone=ZoneInfo("America/La_Paz"),
        timezone_name="America/La_Paz",
        schedule_times=("07:00", "12:00", "19:00"),
    )
    scheduler = BotScheduler(settings, lambda kind: None)
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 3
    assert {job.id for job in jobs} == {
        "general-07:00",
        "general-12:00",
        "general-19:00",
    }
    assert scheduler.running is False
