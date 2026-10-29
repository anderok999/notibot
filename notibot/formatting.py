"""Formato seguro para Telegram (HTML) y división de mensajes."""

from __future__ import annotations

import html
from datetime import tzinfo

from bs4 import BeautifulSoup

from .models import NewsItem
from .utils import (
    clean_html_text,
    format_datetime,
    is_safe_url,
    truncate,
)

HEADERS = {
    "general": "🇧🇴 <b>BOLETÍN INFORMATIVO DE BOLIVIA</b> 🇧🇴",
    "seguridad": "🚨 <b>REPORTES DE SEGURIDAD Y POLICÍA BOLIVIANA</b> 🚨",
}

FOOTER_AI = "<i>Resumen generado con IA · Fuentes: Unitel y Red Uno.</i>"
FOOTER_FALLBACK = "<i>Resumen automático · Fuentes: Unitel y Red Uno.</i>"


def fallback_summary(item: NewsItem) -> str:
    text = clean_html_text(item.summary or item.body or "")
    return truncate(text, 240) or "Consulta los detalles en la fuente original."


def format_item(index: int, item: NewsItem, summary: str | None, local_tz: tzinfo) -> str:
    title = truncate(clean_html_text(item.title), 220) or "Sin título"
    date = format_datetime(item.published_at, local_tz)
    body = truncate(clean_html_text(summary) if summary else fallback_summary(item), 600)

    lines = [
        f"{index}. <b>{html.escape(title)}</b>",
        f"📅 <i>{html.escape(date)} · {html.escape(item.source)}</i>",
        html.escape(body),
    ]
    if is_safe_url(item.url):
        safe_url = html.escape(item.url, quote=True)
        lines.append(f'👉 <a href="{safe_url}">Leer noticia completa</a>')
    return "\n".join(lines)


def build_messages(
    items: list[NewsItem],
    summaries: list[str],
    kind: str,
    local_tz: tzinfo,
    model_used: str = "fallback",
    limit: int = 4000,
) -> list[str]:
    header = HEADERS.get(kind, HEADERS["general"])
    footer = FOOTER_AI if model_used != "fallback" else FOOTER_FALLBACK

    blocks = [
        format_item(
            index + 1,
            item,
            summaries[index] if index < len(summaries) else None,
            local_tz,
        )
        for index, item in enumerate(items)
    ]

    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current != header:
            messages.append(current)
            current = block
        else:
            # Un bloque individual demasiado largo: se recorta para no romper Telegram.
            current = f"{header}\n\n{truncate(block, max(200, limit - len(header) - 2))}"

    current = f"{current}\n\n{footer}"
    if len(current) > limit:
        current = truncate(current, limit)
    messages.append(current)
    return messages


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Divide texto plano (fallback sin HTML) sin superar el límite de Telegram."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        if len(block) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.extend(
                block[index : index + limit]
                for index in range(0, len(block), limit)
            )
            continue

        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) > limit and current:
            parts.append(current)
            current = block
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
