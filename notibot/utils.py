"""Utilidades compartidas: fechas, URLs, texto y caché."""

from __future__ import annotations

import html
import re
import threading
import time
import unicodedata
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

_RELATIVE_RE = re.compile(
    r"hace\s+(?:un\s+)?(\d+)?\s*"
    r"(momento|momentos|instante|instantes|minuto|minutos|hora|horas|"
    r"d[ií]a|d[ií]as|semana|semanas)",
    re.IGNORECASE,
)
_DMY_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})")
_REDUNO_CODE_RE = re.compile(r"-(\d{12,14})$")
_UNITEL_CODE_RE = re.compile(r"-([A-Z]{2}\d{8})$")
_ISO_RE = re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?")


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_iso_datetime(value: str | None, default_tz: tzinfo = UTC) -> datetime | None:
    """Convierte un ISO-8601 a UTC. Si no trae zona, usa ``default_tz``."""
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(UTC)


def parse_spanish_relative(value: str | None, now: datetime | None = None) -> datetime | None:
    """Interpreta 'Hace 25 minutos', 'Hace 2 horas', 'Hace 1 día', etc."""
    if not value:
        return None
    text = value.strip().lower()
    if text in {"ayer", "el día de ayer"}:
        return (now or utcnow()) - timedelta(days=1)

    match = _RELATIVE_RE.search(text)
    if not match:
        return None

    amount = int(match.group(1)) if match.group(1) else 1
    unit = match.group(2).lower()
    if unit.startswith(("momento", "instante")):
        delta = timedelta(minutes=1)
    elif unit.startswith("minuto"):
        delta = timedelta(minutes=amount)
    elif unit.startswith("hora"):
        delta = timedelta(hours=amount)
    elif unit.startswith(("dia", "día")):
        delta = timedelta(days=amount)
    else:
        delta = timedelta(weeks=amount)
    return (now or utcnow()) - delta


def parse_dmy_hm(value: str | None, local_tz: tzinfo) -> datetime | None:
    """Interpreta '27/10/2026 23:43' en la zona horaria indicada."""
    if not value:
        return None
    match = _DMY_RE.search(value)
    if not match:
        return None
    day, month, year, hour, minute = map(int, match.groups())
    try:
        parsed = datetime(year, month, day, hour, minute, tzinfo=local_tz)
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def parse_reduno_url_date(url: str, local_tz: tzinfo) -> datetime | None:
    """Red Uno termina sus URLs con YYYYMMDDHHMM(SS) en hora Bolivia."""
    match = _REDUNO_CODE_RE.search(url.rstrip("/"))
    if not match:
        return None
    digits = match.group(1)
    try:
        if len(digits) >= 14:
            parsed = datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        elif len(digits) == 13:
            # Red Uno a veces omite el cero inicial de los segundos.
            parsed = datetime.strptime(digits[:12], "%Y%m%d%H%M").replace(
                second=int(digits[12])
            )
        else:
            parsed = datetime.strptime(digits[:12], "%Y%m%d%H%M")
    except ValueError:
        return None
    return parsed.replace(tzinfo=local_tz).astimezone(UTC)


def extract_code(url: str) -> str:
    """Devuelve el código estable de la nota (Unitel: OB24439250; Red Uno: timestamp)."""
    path = urlsplit(url).path.rstrip("/")
    last = path.rsplit("/", 1)[-1]
    for pattern in (_UNITEL_CODE_RE, _REDUNO_CODE_RE):
        match = pattern.search(last)
        if match:
            return match.group(1)
    return last or url


def canonical_url(url: str) -> str:
    """Normaliza la URL y elimina parámetros de tracking."""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "fbclid", "gclid"))
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def clean_html_text(value: str | None) -> str:
    """Quita entidades y etiquetas HTML de un texto."""
    if not value:
        return ""
    unescaped = html.unescape(str(value))
    text = BeautifulSoup(unescaped, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(value: str | None) -> str:
    """Clave para detectar el mismo titular con pequeñas variantes."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def truncate(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{cut}…"


def is_recent(value: datetime | None, hours: int = 24, now: datetime | None = None) -> bool:
    if value is None:
        return False
    return value >= (now or utcnow()) - timedelta(hours=hours)


def format_datetime(value: datetime | None, local_tz: tzinfo) -> str:
    if value is None:
        return "Fecha no disponible"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(local_tz).strftime("%d/%m/%Y %H:%M")


def date_sort_key(value: datetime | None) -> datetime:
    return value or datetime.min.replace(tzinfo=UTC)


def is_safe_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def find_iso_dates(value: str) -> list[str]:
    return list(dict.fromkeys(_ISO_RE.findall(value or "")))


class TTLCache:
    """Caché en memoria sencilla para no repetir peticiones en cada boletín."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at < time.monotonic():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
