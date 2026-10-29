"""Fuente Unitel."""

from __future__ import annotations

import re
from datetime import UTC
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..models import NewsItem
from ..utils import clean_html_text, parse_dmy_hm, parse_spanish_relative, truncate
from .base import BaseSource

BOLIVIA = ZoneInfo("America/La_Paz")


class UnitelSource(BaseSource):
    name = "Unitel"
    listing_url = "https://unitel.bo/noticias"
    security_url = "https://unitel.bo/noticias/seguridad"
    article_re = re.compile(r"/noticias/[^/]+/[^/]+-[A-Z]{2}\d{8}$")
    # El JSON-LD de Unitel viene en UTC sin sufijo; verificado contra su sitemap.
    article_tz = UTC
    # Las fechas visibles del listado están en hora Bolivia.
    listing_tz = BOLIVIA

    def parse_listing(self, html_text: str, base_url: str) -> list[NewsItem]:
        soup = BeautifulSoup(html_text, "html.parser")
        items: list[NewsItem] = []

        for anchor in soup.find_all("a", href=True):
            url = self._absolute_url(base_url, anchor["href"])
            if not self.article_re.search(urlsplit(url).path):
                continue

            title = clean_html_text(anchor.get_text(" ", strip=True))
            if not title:
                heading = anchor.find(["h3", "h2"])
                if heading:
                    title = clean_html_text(heading.get_text(" ", strip=True))
            if not title:
                continue

            card = anchor.find_parent("div", class_="texts")
            if card is None:
                card = self._find_card(anchor)

            section = None
            date_text = None
            summary = None
            image = None
            if card is not None:
                section_tag = card.select_one(".section a")
                if section_tag:
                    section = clean_html_text(section_tag.get_text(" ", strip=True)) or None
                date_tag = card.select_one(".publicationDate")
                if date_tag:
                    date_text = date_tag.get_text(" ", strip=True)
                lead_tag = card.select_one("h4.lead")
                if lead_tag:
                    summary = truncate(
                        clean_html_text(lead_tag.get_text(" ", strip=True)), 300
                    ) or None
                image_tag = card.find("img")
                if image_tag:
                    src = (
                        image_tag.get("src")
                        or image_tag.get("data-src")
                        or image_tag.get("data-lazy-src")
                    )
                    if src:
                        image = self._absolute_url(base_url, src)

            published = parse_spanish_relative(date_text) or parse_dmy_hm(
                date_text, self.listing_tz
            )
            items.append(
                NewsItem(
                    source=self.name,
                    title=title,
                    url=url,
                    published_at=published,
                    summary=summary,
                    section=section,
                    image=image,
                    # La fecha del listado es aproximada; se reemplaza por la del artículo.
                    date_estimated=published is not None,
                )
            )

        return items

    def _find_card(self, anchor):
        node = anchor
        for _ in range(6):
            node = node.parent
            if node is None:
                break
            if node.select_one(".publicationDate"):
                return node
        return None
