from __future__ import annotations

from datetime import UTC, datetime

from notibot.models import NewsItem
from notibot.storage import Storage


def _item(code: str) -> NewsItem:
    return NewsItem(
        source="Unitel",
        title=f"Noticia {code}",
        url=f"https://unitel.bo/noticias/foo-{code}",
        code=code,
    )


def test_storage_deduplicates_and_records_runs(tmp_path) -> None:
    storage = Storage(tmp_path / "notibot.db")
    first = _item("OB24439250")
    second = _item("OB24439251")

    assert storage.filter_new([first, second]) == [first, second]
    storage.mark_sent([first])
    assert storage.filter_new([first, second]) == [second]

    started = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    storage.record_run("general", started, "success", 1)
    assert storage.last_success() is not None
    stats = storage.stats()
    assert stats["seen"] == 1
    assert stats["last_run"]["status"] == "success"
    assert stats["last_run"]["items"] == 1


def test_storage_prune_keeps_recent(tmp_path) -> None:
    storage = Storage(tmp_path / "notibot.db")
    item = _item("OB24439252")
    storage.mark_sent([item])
    storage.prune_seen(days=30)
    assert storage.filter_new([item]) == []
