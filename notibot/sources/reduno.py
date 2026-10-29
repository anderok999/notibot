"""Fuente Red Uno."""

from __future__ import annotations

import re
from datetime import UTC
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..models import NewsItem
from ..utils import clean_html_text, parse_reduno_url_date
from .base import BaseSource

BOLIVIA = ZoneInfo("America/La_Paz")


class RedunoSource(BaseSource):
    name = "Red Uno"
    listing_url = "https://www.reduno.com.bo/noticias"
    # /noticias/seguridad devuelve 404; la sección real es /noticias/policial.
    security_url = "https://www.reduno.com.bo/noticias/policial"
    article_re = re.compile(r"/noticias/[^/]+-\d{10,}$")
    article_tz = UTC
    listing_tz = BOLIVIA

    _SECURITY_KEYWORDS = (
        "seguridad",
        "polic",
        "fiscal",
        "judicial",
        "justicia",
        "aprehend",
        "deten",
        "operativo",
        "delito",
        "crimen",
        "investiga",
        "narcotr",
        "marset",
    )

    def parse_listing(self, html_text: str, base_url: str) -> list[NewsItem]:
        soup = BeautifulSoup(html_text, "html.parser")
        items: list[NewsItem] = []

        for anchor in soup.find_all("a", href=True):
            url = self._absolute_url(base_url, anchor["href"])
            if not self.article_re.search(urlsplit(url).path):
                continue

            title = clean_html_text(anchor.get_text(" ", strip=True))
            if not title:
                heading = anchor.find(["h2", "h3", "h4"])
                if heading:
                    title = clean_html_text(heading.get_text(" ", strip=True))
            if not title:
                continue

            card = self._find_card(anchor)
            image = None
            if card is not None:
                image_tag = card.find("img")
                if image_tag:
                    src = (
                        image_tag.get("src")
                        or image_tag.get("data-src")
                        or image_tag.get("data-lazy-src")
                    )
                    if src:
                        image = self._absolute_url(base_url, src)

            published = parse_reduno_url_date(url, self.listing_tz)
            items.append(
                NewsItem(
                    source=self.name,
                    title=title,
                    url=url,
                    published_at=published,
                    summary=None,
                    image=image,
                    # El timestamp de la URL es una aproximación; el JSON-LD manda.
                    date_estimated=published is not None,
                )
            )

        return items

    def fetch_security_items(self, limit: int = 20) -> list[NewsItem]:
        items = super().fetch_security_items(limit=limit)
        if items:
            return items

        # Fallback: si la sección policial cambia, filtramos el listado general.
        general = self.fetch_items(self.listing_url, limit=limit * 2)
        filtered = [item for item in general if self._looks_security(item)]
        return filtered[:limit]

    def _looks_security(self, item: NewsItem) -> bool:
        haystack = " ".join(
            filter(None, [item.section, item.title, item.summary, item.body])
        ).lower()
        return any(keyword in haystack for keyword in self._SECURITY_KEYWORDS)

    @staticmethod
    def _find_card(anchor):
        node = anchor
        for _ in range(4):
            node = node.parent
            if node is None:
                break
            if node.find("img"):
                return node
        return anchor.parent
