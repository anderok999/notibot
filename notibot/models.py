"""Modelos de datos del bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .utils import canonical_url, extract_code


@dataclass(slots=True)
class NewsItem:
    source: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str | None = None
    body: str | None = None
    section: str | None = None
    image: str | None = None
    code: str | None = None
    date_estimated: bool = False

    def __post_init__(self) -> None:
        self.url = canonical_url(self.url)
        if not self.code:
            self.code = extract_code(self.url)
