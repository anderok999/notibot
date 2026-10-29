"""Punto de entrada de NotiBot.

Uso:
    python main.py                 # bot + scheduler + health server
    python main.py --check         # valida configuración sin secretos
    python main.py --dry-run       # scraping real, sin enviar a Telegram
    python main.py --once general  # un envío inmediato y sale
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import signal
import sys
from collections.abc import Sequence
from dataclasses import replace

from notibot.ai import AIClient
from notibot.bot import NotiBot
from notibot.config import ConfigError, Settings
from notibot.formatting import build_messages
from notibot.health import HealthServer
from notibot.pipeline import NewsPipeline
from notibot.scheduler import BotScheduler
from notibot.sources import RedunoSource, UnitelSource
from notibot.sources.base import BaseSource
from notibot.storage import Storage
from notibot.utils import format_datetime

log = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("telebot").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


def build_sources(settings: Settings) -> dict[str, BaseSource]:
    return {
        "unitel": UnitelSource(
            timeout=settings.request_timeout,
            max_workers=4,
        ),
        "reduno": RedunoSource(
            timeout=settings.request_timeout,
            max_workers=4,
        ),
    }


def build_storage(settings: Settings) -> Storage:
    settings.ensure_dirs()
    return Storage(settings.data_dir / "notibot.db")


def build_ai(settings: Settings) -> AIClient | None:
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY no configurada; se usará resumen automático")
        return None
    try:
        return AIClient(settings.gemini_api_key, settings.gemini_models)
    except Exception:  # noqa: BLE001 - el bot puede seguir con fallback
        log.exception("No se pudo inicializar Gemini; se usará fallback")
        return None


def close_sources(sources: dict[str, BaseSource]) -> None:
    for source in sources.values():
        with contextlib.suppress(Exception):
            source.close()


def run_check(settings: Settings) -> int:
    print(json.dumps(settings.summary(), ensure_ascii=False, indent=2))
    return 0


def run_dry(args: argparse.Namespace, settings: Settings) -> int:
    if args.limit is not None:
        settings = replace(settings, max_articles_per_source=args.limit)

    settings.ensure_dirs()
    sources = build_sources(settings)
    storage = build_storage(settings)
    ai: AIClient | None = None
    if args.with_ai:
        if not settings.gemini_api_key:
            log.error("--with-ai requiere GEMINI_API_KEY")
            close_sources(sources)
            return 2
        ai = build_ai(settings)

    pipeline = NewsPipeline(settings, sources, storage, ai)
    try:
        items, summaries, model = pipeline.build(args.kind, automatic=False)
    finally:
        close_sources(sources)

    if not items:
        print("No se encontraron noticias.")
        return 1

    counts: dict[str, int] = {}
    for item in items:
        counts[item.source] = counts.get(item.source, 0) + 1

    print("Modo dry-run: no se envió nada a Telegram.")
    print(
        f"Tipo: {args.kind} | Noticias: {len(items)} | "
        f"Fuentes: {counts} | Modelo: {model}"
    )

    for index, (item, summary) in enumerate(zip(items, summaries, strict=False), start=1):
        estimated = " (fecha estimada)" if item.date_estimated else ""
        print(
            f"\n{index}. [{item.source}] "
            f"{format_datetime(item.published_at, settings.timezone)}{estimated}"
        )
        print(f"   {item.title}")
        print(f"   {item.url}")
        print(f"   {summary}")

    messages = build_messages(
        items,
        summaries,
        args.kind,
        settings.timezone,
        model,
    )
    print("\n--- Mensajes que se enviarían ---")
    for index, message in enumerate(messages, start=1):
        print(
            f"\n[Mensaje {index} · {len(message)} caracteres]\n{message}"
        )
    return 0


def run_once(kind: str, settings: Settings) -> int:
    settings.ensure_dirs()
    sources = build_sources(settings)
    storage = build_storage(settings)
    ai = build_ai(settings)
    pipeline = NewsPipeline(settings, sources, storage, ai)
    bot = NotiBot(settings, pipeline, storage)
    try:
        bot.connect()
        ok = bot.run_automatic(kind)
        print("Envío completado." if ok else "No se pudo completar el envío.")
        return 0 if ok else 1
    finally:
        close_sources(sources)


def run_service(settings: Settings) -> int:
    settings.ensure_dirs()
    sources = build_sources(settings)
    storage = build_storage(settings)
    storage.prune_seen()
    ai = build_ai(settings)
    pipeline = NewsPipeline(settings, sources, storage, ai)
    bot = NotiBot(settings, pipeline, storage)
    scheduler = BotScheduler(settings, bot.run_automatic)
    bot.scheduler_status = lambda: scheduler.running
    bot.next_runs_provider = scheduler.next_runs
    health = HealthServer(settings.port, bot.state)

    stopping = False

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        log.info("Señal %s recibida; cerrando NotiBot...", signum)
        bot.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            signal.signal(sig, handle_signal)

    try:
        bot.connect()
        scheduler.start()
        health.start()
        log.info("NotiBot listo; esperando mensajes de Telegram...")
        bot.poll()
    finally:
        bot.stop()
        scheduler.shutdown()
        health.stop()
        close_sources(sources)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NotiBot: boletín de noticias bolivianas por Telegram"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="valida la configuración y muestra un resumen sin secretos",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="hace scraping real y muestra el boletín sin enviarlo",
    )
    parser.add_argument(
        "--with-ai",
        action="store_true",
        help="en --dry-run, usa Gemini si GEMINI_API_KEY está disponible",
    )
    parser.add_argument(
        "--kind",
        choices=["general", "seguridad"],
        default="general",
        help="tipo de boletín para --dry-run",
    )
    parser.add_argument(
        "--once",
        choices=["general", "seguridad"],
        help="envía un boletín inmediato a CHAT_ID/CHAT_IDS y termina",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="máximo de artículos a inspeccionar por fuente en --dry-run",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.dry_run and args.once:
        parser.error("--dry-run y --once son mutuamente excluyentes")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit debe ser mayor que 0")

    try:
        settings = Settings.from_env(
            require_credentials=not (args.dry_run or args.check)
        )
    except ConfigError as exc:
        print(f"ERROR DE CONFIGURACIÓN: {exc}", file=sys.stderr)
        return 2

    setup_logging(settings.log_level)

    try:
        if args.check:
            return run_check(settings)
        if args.dry_run:
            return run_dry(args, settings)
        if args.once:
            return run_once(args.once, settings)
        return run_service(settings)
    except KeyboardInterrupt:
        log.info("Interrumpido por el usuario")
        return 0
    except Exception:  # noqa: BLE001 - error fatal de arranque
        log.exception("Error fatal de NotiBot")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
