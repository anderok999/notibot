from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from notibot.models import NewsItem
from notibot.pipeline import NewsPipeline
from notibot.storage import Storage


def _settings(**overrides):
    values = {
        "news_unitel": 2,
        "news_reduno": 2,
        "total_news": 4,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _item(source: str, code: str, hours_ago: float, title: str | None = None) -> NewsItem:
    return NewsItem(
        source=source,
        title=title or f"Noticia {code}",
        url=f"https://example.com/{code}",
        code=code,
        published_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )


def test_balance_fills_from_other_source() -> None:
    pipeline = NewsPipeline(_settings(), {}, None, None)
    unitel = [
        _item("Unitel", "U1", 1),
        _item("Unitel", "U2", 2),
        _item("Unitel", "U3", 3),
    ]
    reduno = [_item("Red Uno", "R1", 4)]

    selected = pipeline._balance(unitel, reduno)

    assert len(selected) == 4
    assert sum(item.source == "Unitel" for item in selected) == 3
    assert sum(item.source == "Red Uno" for item in selected) == 1
    assert selected[0].code == "U1"


def test_dedupe_by_code_and_title() -> None:
    pipeline = NewsPipeline(_settings(), {}, None, None)
    items = [
        _item("Unitel", "U1", 1),
        _item("Red Uno", "U1", 2),
        _item("Red Uno", "R2", 3, title="Noticia U1"),
        _item("Red Uno", "R3", 4),
    ]
    result = pipeline._dedupe(items)
    assert [item.code for item in result] == ["U1", "R3"]


def test_recent_automatic_skips_old_news() -> None:
    pipeline = NewsPipeline(_settings(), {}, None, None)
    recent = _item("Unitel", "U1", 1)
    old = _item("Unitel", "U2", 48)

    assert pipeline._recent([recent, old], automatic=True) == [recent]
    assert pipeline._recent([old], automatic=True) == []
    assert pipeline._recent([old], automatic=False) == [old]


class _FakeSource:
    listing_url = "https://example.com/noticias"

    def __init__(self, items: list[NewsItem]) -> None:
        self.items = items

    def fetch_items(self, _url: str, limit: int = 20) -> list[NewsItem]:
        return self.items[:limit]

    def fetch_security_items(self, limit: int = 20) -> list[NewsItem]:
        return self.items[:limit]


def test_pipeline_run_sends_and_marks_items(tmp_path) -> None:
    settings = SimpleNamespace(
        max_articles_per_source=10,
        news_unitel=2,
        news_reduno=2,
        total_news=4,
        timezone=ZoneInfo("America/La_Paz"),
    )
    unitel = [_item("Unitel", "U1", 1), _item("Unitel", "U2", 2)]
    reduno = [_item("Red Uno", "R1", 3), _item("Red Uno", "R2", 4)]
    storage = Storage(tmp_path / "notibot.db")
    pipeline = NewsPipeline(
        settings,
        {
            "unitel": _FakeSource(unitel),
            "reduno": _FakeSource(reduno),
        },
        storage,
        None,
    )

    sent: list[tuple[str, list[str]]] = []

    def sender(chat_id: str, messages: list[str]) -> bool:
        sent.append((chat_id, messages))
        return True

    assert pipeline.run("general", ["123"], automatic=True, sender=sender)
    assert sent[0][0] == "123"
    assert all(len(message) <= 4000 for message in sent[0][1])
    assert storage.stats()["seen"] == 4
    assert storage.stats()["last_run"]["status"] == "success"

    # La segunda ejecución no debe repetir las mismas noticias.
    assert not pipeline.run("general", ["123"], automatic=True, sender=sender)
    assert storage.stats()["last_run"]["status"] == "empty"
