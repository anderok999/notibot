"""Configuración validada desde variables de entorno."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv es una comodidad local
    load_dotenv = None  # type: ignore[assignment]

from . import __version__

if load_dotenv is not None:
    load_dotenv()


class ConfigError(RuntimeError):
    """Error de configuración con un mensaje apto para el operador."""


def _split_values(value: str | None) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\s]+", value or "") if part.strip()]


def _int_env(
    name: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} debe ser un número entero, no {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} debe ser >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} debe ser <= {maximum}")
    return value


def _valid_time(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match:
        raise ConfigError(f"Horario inválido {value!r}; usa HH:MM, por ejemplo 07:00")
    hour, minute = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"Horario inválido {value!r}; usa HH:MM entre 00:00 y 23:59")
    return f"{hour:02d}:{minute:02d}"


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    gemini_api_key: str
    chat_ids: tuple[str, ...]
    allowed_user_ids: frozenset[int]
    gemini_models: tuple[str, ...]
    timezone: ZoneInfo
    timezone_name: str
    schedule_times: tuple[str, ...]
    port: int
    data_dir: Path
    log_level: str
    max_articles_per_source: int
    news_unitel: int
    news_reduno: int
    total_news: int
    request_timeout: int
    rate_limit_seconds: int
    version: str = __version__

    @classmethod
    def from_env(cls, require_credentials: bool = True) -> Settings:
        telegram_token = (
            os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
        ).strip()
        gemini_api_key = (
            os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        ).strip()

        chat_raw = os.getenv("CHAT_IDS") or os.getenv("CHAT_ID") or ""
        chat_ids = tuple(_split_values(chat_raw))

        allowed_raw = os.getenv("ALLOWED_USER_IDS", "")
        allowed_user_ids: set[int] = set()
        for value in _split_values(allowed_raw):
            try:
                allowed_user_ids.add(int(value))
            except ValueError:
                logging.getLogger(__name__).warning(
                    "ALLOWED_USER_IDS contiene un valor no numérico: %r", value
                )

        models_raw = (
            os.getenv("GEMINI_MODELS")
            or os.getenv("GEMINI_MODEL")
            or "gemini-2.5-flash,gemini-2.0-flash"
        )
        gemini_models = tuple(dict.fromkeys(_split_values(models_raw)))
        if not gemini_models:
            raise ConfigError("GEMINI_MODELS no puede estar vacío")

        timezone_name = os.getenv("TIMEZONE", "America/La_Paz").strip() or "America/La_Paz"
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                f"TIMEZONE {timezone_name!r} no existe. En Windows instala tzdata."
            ) from exc

        schedule_raw = os.getenv("SCHEDULE_TIMES", "07:00,12:00,19:00")
        schedule_times = tuple(_valid_time(value) for value in _split_values(schedule_raw))
        if not schedule_times:
            raise ConfigError("SCHEDULE_TIMES no puede estar vacío")

        port = _int_env("PORT", 8080, 1, 65535)
        data_dir = Path(os.getenv("DATA_DIR", "data")).expanduser()
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError(f"LOG_LEVEL inválido: {log_level!r}")

        max_articles = _int_env("MAX_ARTICLES_PER_SOURCE", 20, 1, 100)
        news_unitel = _int_env("NEWS_UNITEL", 3, 0, 20)
        news_reduno = _int_env("NEWS_REDUNO", 2, 0, 20)
        total_news = _int_env("TOTAL_NEWS", 5, 1, 20)
        if news_unitel + news_reduno == 0:
            raise ConfigError("NEWS_UNITEL y NEWS_REDUNO no pueden ser ambos 0")

        request_timeout = _int_env("REQUEST_TIMEOUT", 20, 5, 120)
        rate_limit_seconds = _int_env("RATE_LIMIT_SECONDS", 60, 0, 3600)

        if require_credentials:
            missing = []
            if not telegram_token:
                missing.append("TELEGRAM_TOKEN")
            if not gemini_api_key:
                missing.append("GEMINI_API_KEY")
            if not chat_ids:
                missing.append("CHAT_ID o CHAT_IDS")
            if missing:
                raise ConfigError(
                    "Faltan variables de entorno obligatorias: "
                    + ", ".join(missing)
                    + ". Configúralas en Render (Environment) o en tu .env local."
                )

        return cls(
            telegram_token=telegram_token,
            gemini_api_key=gemini_api_key,
            chat_ids=chat_ids,
            allowed_user_ids=frozenset(allowed_user_ids),
            gemini_models=gemini_models,
            timezone=timezone,
            timezone_name=timezone_name,
            schedule_times=schedule_times,
            port=port,
            data_dir=data_dir,
            log_level=log_level,
            max_articles_per_source=max_articles,
            news_unitel=news_unitel,
            news_reduno=news_reduno,
            total_news=total_news,
            request_timeout=request_timeout,
            rate_limit_seconds=rate_limit_seconds,
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def summary(self) -> dict[str, object]:
        return {
            "version": self.version,
            "timezone": self.timezone_name,
            "schedule_times": list(self.schedule_times),
            "gemini_models": list(self.gemini_models),
            "telegram_token": "configurado" if self.telegram_token else "FALTA",
            "gemini_api_key": "configurada" if self.gemini_api_key else "FALTA",
            "chat_ids": len(self.chat_ids),
            "allowed_user_ids": len(self.allowed_user_ids),
            "max_articles_per_source": self.max_articles_per_source,
            "news_unitel": self.news_unitel,
            "news_reduno": self.news_reduno,
            "total_news": self.total_news,
            "port": self.port,
            "data_dir": str(self.data_dir),
        }
