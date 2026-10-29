"""Pipeline de recolección, selección, resumen y envío."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .ai import AIClient
from .config import Settings
from .formatting import build_messages, fallback_summary
from .models import NewsItem
from .sources.base import BaseSource
from .storage import Storage
from .utils import date_sort_key, is_recent, normalize_title, utcnow

log = logging.getLogger(__name__)

Sender = Callable[[str, list[str]], bool]


class NewsPipeline:
    def __init__(
        self,
        settings: Settings,
        sources: dict[str, BaseSource],
        storage: Storage,
        ai: AIClient | None,
    ) -> None:
        self.settings = settings
        self.sources = sources
        self.storage = storage
        self.ai = ai
        self.last_error: str | None = None
        self._lock = threading.Lock()

    def collect(self, kind: str, automatic: bool = False) -> list[NewsItem]:
        if kind not in {"general", "seguridad"}:
            raise ValueError(f"Tipo de boletín desconocido: {kind}")

        limit = self.settings.max_articles_per_source
        if kind == "seguridad":
            unitel = self.sources["unitel"].fetch_security_items(limit=limit)
            reduno = self.sources["reduno"].fetch_security_items(limit=limit)
        else:
            unitel = self.sources["unitel"].fetch_items(
                self.sources["unitel"].listing_url, limit=limit
            )
            reduno = self.sources["reduno"].fetch_items(
                self.sources["reduno"].listing_url, limit=limit
            )

        unitel = self._recent(unitel, automatic)
        reduno = self._recent(reduno, automatic)

        if automatic:
            unitel = self.storage.filter_new(unitel)
            reduno = self.storage.filter_new(reduno)

        unitel = self._dedupe(unitel)
        reduno = self._dedupe(reduno)
        selected = self._balance(unitel, reduno)

        log.info(
            "%s: Unitel=%d, Red Uno=%d, seleccionadas=%d",
            kind,
            len(unitel),
            len(reduno),
            len(selected),
        )
        return selected

    def build(
        self, kind: str, automatic: bool = False
    ) -> tuple[list[NewsItem], list[str], str]:
        items = self.collect(kind, automatic)
        if not items:
            return [], [], "none"

        summaries: list[str] = []
        model = "fallback"
        if self.ai is not None:
            summaries, model = self.ai.generate(items, kind)

        if not summaries:
            summaries = [fallback_summary(item) for item in items]
            model = "fallback"
        else:
            summaries = [
                summary or fallback_summary(item)
                for summary, item in zip(summaries, items, strict=False)
            ]
        return items, summaries, model

    def run(
        self,
        kind: str,
        chat_ids: list[str] | tuple[str, ...],
        automatic: bool,
        sender: Sender,
    ) -> bool:
        with self._lock:
            started = utcnow()
            try:
                items, summaries, model = self.build(kind, automatic)
                if not items:
                    self.storage.record_run(kind, started, "empty", 0)
                    self.last_error = None
                    return False

                messages = build_messages(
                    items,
                    summaries,
                    kind,
                    self.settings.timezone,
                    model,
                )
                sent_ok = False
                for chat_id in chat_ids:
                    if sender(str(chat_id), messages):
                        sent_ok = True

                if automatic and sent_ok:
                    self.storage.mark_sent(items)

                error = None if sent_ok else "No se pudo enviar a ningún chat"
                self.storage.record_run(
                    kind,
                    started,
                    "success" if sent_ok else "error",
                    len(items),
                    error,
                )
                self.last_error = error
                return sent_ok
            except Exception as exc:  # noqa: BLE001 - se registra y no se cae el bot
                self.last_error = str(exc)
                self.storage.record_run(kind, started, "error", 0, str(exc))
                log.exception("Error generando el boletín %s", kind)
                return False

    def _recent(self, items: list[NewsItem], automatic: bool) -> list[NewsItem]:
        now = utcnow()
        recent = [item for item in items if is_recent(item.published_at, 24, now)]
        if recent:
            return recent

        dated = [item for item in items if item.published_at]
        if automatic:
            log.warning(
                "No hay noticias con fecha de las últimas 24h; se omite el envío automático"
            )
            return []
        log.warning(
            "No hay noticias con fecha de las últimas 24h; se usan las más recientes"
        )
        return dated or items

    @staticmethod
    def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
        ordered = sorted(
            items,
            key=lambda item: date_sort_key(item.published_at),
            reverse=True,
        )
        seen_codes: set[str] = set()
        seen_titles: set[str] = set()
        result: list[NewsItem] = []
        for item in ordered:
            code = item.code or item.url
            title = normalize_title(item.title)
            if code in seen_codes or (title and title in seen_titles):
                continue
            seen_codes.add(code)
            if title:
                seen_titles.add(title)
            result.append(item)
        return result

    def _balance(
        self, unitel: list[NewsItem], reduno: list[NewsItem]
    ) -> list[NewsItem]:
        unitel = sorted(
            unitel, key=lambda item: date_sort_key(item.published_at), reverse=True
        )
        reduno = sorted(
            reduno, key=lambda item: date_sort_key(item.published_at), reverse=True
        )

        selected = (
            unitel[: self.settings.news_unitel]
            + reduno[: self.settings.news_reduno]
        )

        if len(selected) < self.settings.total_news:
            rest = (
                unitel[self.settings.news_unitel :]
                + reduno[self.settings.news_reduno :]
            )
            rest.sort(
                key=lambda item: date_sort_key(item.published_at), reverse=True
            )
            selected.extend(rest[: self.settings.total_news - len(selected)])

        selected.sort(
            key=lambda item: date_sort_key(item.published_at), reverse=True
        )
        return selected[: self.settings.total_news]
