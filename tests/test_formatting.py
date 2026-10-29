from __future__ import annotations

from datetime import UTC, datetime

from notibot.formatting import (
    build_messages,
    format_item,
    split_message,
    strip_html,
)
from notibot.models import NewsItem


def _item(index: int, **kwargs) -> NewsItem:
    data = {
        "source": "Unitel",
        "title": f"Noticia {index}",
        "url": f"https://unitel.bo/noticias/foo-OB2443925{index}",
        "published_at": datetime(2026, 10, 28, 18, 20, tzinfo=UTC),
        "summary": f"Resumen {index}",
    }
    data.update(kwargs)
    return NewsItem(**data)


def test_format_item_escapes_html_and_url() -> None:
    item = _item(
        1,
        title="Noticia <b>importante</b> & más",
        url="https://example.com/a?x=1&y=2",
        summary="<b>Resumen</b> & más",
    )
    text = format_item(1, item, "<b>Resumen</b> & más", UTC)

    assert "Noticia importante &amp; más" in text
    assert "&lt;b&gt;" not in text
    assert 'href="https://example.com/a?x=1&amp;y=2"' in text
    assert "Hoy" not in text


def test_format_item_without_date_does_not_invent_today() -> None:
    item = _item(1, published_at=None)
    text = format_item(1, item, "Resumen", UTC)
    assert "Fecha no disponible" in text
    assert "Hoy" not in text


def test_build_messages_respects_limit() -> None:
    items = [_item(index) for index in range(1, 7)]
    summaries = [f"Resumen {index}" for index in range(1, 7)]
    messages = build_messages(items, summaries, "general", UTC)

    assert messages
    assert all(len(message) <= 4000 for message in messages)
    joined = "\n".join(messages)
    for index in range(1, 7):
        assert f"Noticia {index}" in joined


def test_split_message_hard_splits_long_blocks() -> None:
    parts = split_message("x" * 9000, 4000)
    assert len(parts) == 3
    assert all(len(part) <= 4000 for part in parts)


def test_strip_html() -> None:
    assert strip_html("<b>Hola</b><br>mundo") == "Hola\nmundo"
