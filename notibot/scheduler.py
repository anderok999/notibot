"""Programación de envíos automáticos con APScheduler."""

from __future__ import annotations

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from .config import Settings

log = logging.getLogger(__name__)


class BotScheduler:
    """Envía el boletín general a las horas configuradas (hora de Bolivia)."""

    def __init__(self, settings: Settings, job: Callable[[str], object]) -> None:
        self.settings = settings
        self.job = job
        self.scheduler = BackgroundScheduler(
            timezone=settings.timezone,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )

        for schedule in settings.schedule_times:
            hour, minute = (int(part) for part in schedule.split(":"))
            self.scheduler.add_job(
                self._run,
                trigger="cron",
                hour=hour,
                minute=minute,
                args=["general"],
                id=f"general-{schedule}",
                name=f"Boletín general {schedule}",
                replace_existing=True,
            )

    def _run(self, kind: str) -> None:
        log.info("Ejecutando envío automático: %s", kind)
        try:
            self.job(kind)
        except Exception:  # noqa: BLE001 - el scheduler debe seguir vivo
            log.exception("Falló el envío automático %s", kind)

    def start(self) -> None:
        self.scheduler.start()
        log.info(
            "Scheduler iniciado en %s con horarios %s",
            self.settings.timezone_name,
            ", ".join(self.settings.schedule_times),
        )
        for job in self.scheduler.get_jobs():
            log.info("Próxima ejecución de %s: %s", job.id, job.next_run_time)

    @property
    def running(self) -> bool:
        return bool(self.scheduler.running)

    def next_runs(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for job in self.scheduler.get_jobs():
            if job.next_run_time is not None:
                result[job.id] = job.next_run_time.isoformat()
        return result

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            log.info("Scheduler detenido")
