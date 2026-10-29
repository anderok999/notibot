"""Lógica común de scraping y extracción de metadatos."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import NewsItem
from ..utils import (
    UTC,
    TTLCache,
    clean_html_text,
    find_iso_dates,
    normalize_title,
    parse_iso_datetime,
    truncate,
)

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ArticleData:
    title: str | None = None
    published_at: datetime | None = None
    body: str | None = None
    description: str | None = None
    image: str | None = None
    section: str | None = None


class BaseSource:
    """Fuente base. Cada medio define su listado y el patrón de sus artículos."""

    name = "base"
    listing_url = ""
    security_url: str | None = None
    article_re: re.Pattern[str] = re.compile(r"$^")
    article_tz: tzinfo = UTC
    listing_tz: tzinfo = UTC
    user_agent = "NotiBot/2.0 (+https://github.com/anderok999/notibot)"

    def __init__(
        self,
        timeout: int = 20,
        max_workers: int = 4,
        cache_ttl: int = 300,
    ) -> None:
        self.timeout = timeout
        self.max_workers = max_workers
        self.cache = TTLCache(cache_ttl)
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=8,
            pool_maxsize=8,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-BO,es;q=0.9,en;q=0.5",
            }
        )
        return session

    def close(self) -> None:
        self.session.close()

    def fetch_html(self, url: str, use_cache: bool = True) -> str:
        if use_cache:
            cached = self.cache.get(url)
            if cached is not None:
                return cached

        response = self.session.get(url, timeout=(10, self.timeout))
        response.raise_for_status()
        # Unitel no declara charset; apparent_encoding evita el mojibake.
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        text = response.text
        if use_cache:
            self.cache.set(url, text)
        return text

    def parse_listing(self, html_text: str, base_url: str) -> list[NewsItem]:
        raise NotImplementedError

    def fetch_items(self, url: str, limit: int = 20, fetch_articles: bool = True) -> list[NewsItem]:
        try:
            html_text = self.fetch_html(url)
        except requests.RequestException as exc:
            log.warning("%s: no se pudo leer %s: %s", self.name, url, exc)
            return []

        items = self.parse_listing(html_text, url)
        items = self._dedupe(items)[:limit]
        if fetch_articles and items:
            items = self._enrich(items)
        return items

    def fetch_security_items(self, limit: int = 20) -> list[NewsItem]:
        if not self.security_url:
            return []
        return self.fetch_items(self.security_url, limit=limit)

    def _dedupe(self, items: list[NewsItem]) -> list[NewsItem]:
        seen_codes: set[str] = set()
        seen_titles: set[str] = set()
        result: list[NewsItem] = []
        for item in items:
            code = item.code or item.url
            title = normalize_title(item.title)
            if code in seen_codes or (title and title in seen_titles):
                continue
            seen_codes.add(code)
            if title:
                seen_titles.add(title)
            result.append(item)
        return result

    def _enrich(self, items: list[NewsItem]) -> list[NewsItem]:
        enriched: list[NewsItem] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._enrich_one, item): item for item in items}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    enriched.append(future.result())
                except Exception as exc:  # noqa: BLE001 - una nota no debe tumbar el boletín
                    log.debug("%s: fallo enriqueciendo %s: %s", self.name, item.url, exc)
                    enriched.append(item)

        order = {id(item): index for index, item in enumerate(items)}
        enriched.sort(key=lambda item: order.get(id(item), 10_000))
        return enriched

    def _enrich_one(self, item: NewsItem) -> NewsItem:
        try:
            html_text = self.fetch_html(item.url)
            data = self.parse_article(html_text, item.url)
        except requests.RequestException as exc:
            log.debug("%s: no se pudo abrir %s: %s", self.name, item.url, exc)
            return item

        if data.title:
            item.title = data.title
        if data.published_at:
            item.published_at = data.published_at
            item.date_estimated = False
        if data.body:
            item.body = data.body
        if data.description:
            item.summary = data.description
        if data.image:
            item.image = data.image
        if data.section:
            item.section = data.section
        return item

    def parse_article(self, html_text: str, url: str) -> ArticleData:
        soup = BeautifulSoup(html_text, "html.parser")
        article = self._find_article_jsonld(soup)

        title = clean_html_text(article.get("headline") or article.get("name"))
        if not title:
            title = clean_html_text(
                self._meta_content(soup, "og:title", "twitter:title")
            )
        if not title:
            heading = soup.find("h1")
            if heading:
                title = clean_html_text(heading.get_text(" ", strip=True))
        if not title and soup.title:
            title = clean_html_text(soup.title.get_text(" ", strip=True))

        published = parse_iso_datetime(
            article.get("datePublished"), self.article_tz
        )
        if not published:
            meta_date = self._meta_content(
                soup,
                "article:published_time",
                "datePublished",
                "date",
                "pubdate",
            )
            published = parse_iso_datetime(meta_date, self.article_tz)
        if not published:
            for time_tag in soup.find_all("time"):
                published = parse_iso_datetime(
                    time_tag.get("datetime") or time_tag.get_text(" ", strip=True),
                    self.article_tz,
                )
                if published:
                    break
        if not published:
            for candidate in find_iso_dates(html_text):
                published = parse_iso_datetime(candidate, self.article_tz)
                if published:
                    break

        body = clean_html_text(article.get("articleBody"))
        if not body:
            paragraphs = [
                clean_html_text(paragraph.get_text(" ", strip=True))
                for paragraph in soup.find_all("p")
            ]
            paragraphs = [text for text in paragraphs if len(text) >= 60]
            body = " ".join(paragraphs[:8])
        body = truncate(body, 5000) or None

        description = clean_html_text(article.get("description"))
        if not description:
            description = clean_html_text(
                self._meta_content(soup, "og:description", "description")
            )
        description = truncate(description, 500) or None

        image = self._image_url(article.get("image"))
        if not image:
            image = self._meta_content(soup, "og:image", "twitter:image")

        section = article.get("articleSection")
        if isinstance(section, list):
            section = section[0] if section else None
        section = clean_html_text(section) or None

        return ArticleData(
            title=title or None,
            published_at=published,
            body=body,
            description=description,
            image=image,
            section=section,
        )

    def _find_article_jsonld(self, soup: BeautifulSoup) -> dict[str, Any]:
        candidates = list(self._iter_jsonld(soup))
        for candidate in candidates:
            types = candidate.get("@type")
            if isinstance(types, str):
                types = [types]
            if types and any(
                isinstance(type_name, str) and "Article" in type_name
                for type_name in types
            ):
                return candidate
        for candidate in candidates:
            if candidate.get("datePublished") and (
                candidate.get("headline") or candidate.get("name")
            ):
                return candidate
        return {}

    def _iter_jsonld(self, soup: BeautifulSoup) -> Iterator[dict[str, Any]]:
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text()
            if not raw or not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield from self._walk_jsonld(data)

    def _walk_jsonld(self, data: Any) -> Iterator[dict[str, Any]]:
        if isinstance(data, list):
            for item in data:
                yield from self._walk_jsonld(item)
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if graph:
                yield from self._walk_jsonld(graph)
            yield data

    @staticmethod
    def _meta_content(soup: BeautifulSoup, *keys: str) -> str | None:
        for key in keys:
            tag = soup.find("meta", attrs={"property": key})
            if tag is None:
                tag = soup.find("meta", attrs={"name": key})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return None

    @staticmethod
    def _image_url(value: Any) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        if isinstance(value, dict):
            return (
                str(value.get("url") or value.get("contentUrl") or "").strip()
                or None
            )
        if isinstance(value, list):
            for item in value:
                url = BaseSource._image_url(item)
                if url:
                    return url
        return None

    def _absolute_url(self, base_url: str, href: str) -> str:
        return urljoin(base_url, href)
