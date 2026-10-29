from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from notibot.utils import (
    canonical_url,
    clean_html_text,
    extract_code,
    is_recent,
    parse_dmy_hm,
    parse_iso_datetime,
    parse_reduno_url_date,
    parse_spanish_relative,
)

BOLIVIA = ZoneInfo("America/La_Paz")
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def test_parse_iso_naive_is_utc() -> None:
    parsed = parse_iso_datetime("2026-10-28T18:20:00")
    assert parsed == datetime(2026, 10, 28, 18, 20, tzinfo=UTC)


def test_parse_iso_with_z() -> None:
    parsed = parse_iso_datetime("2026-10-29T00:31:12.439Z")
    assert parsed == datetime(2026, 10, 29, 0, 31, 12, 439000, tzinfo=UTC)


def test_parse_spanish_relative() -> None:
    assert parse_spanish_relative("Hace 2 horas", NOW) == NOW - timedelta(hours=2)
    assert parse_spanish_relative("Hace 25 minutos", NOW) == NOW - timedelta(
        minutes=25
    )
    assert parse_spanish_relative("Hace 1 día", NOW) == NOW - timedelta(days=1)
    assert parse_spanish_relative("Ayer", NOW) == NOW - timedelta(days=1)
    assert parse_spanish_relative("sin fecha", NOW) is None


def test_parse_bolivia_date_to_utc() -> None:
    parsed = parse_dmy_hm("27/10/2026 23:43", BOLIVIA)
    assert parsed == datetime(2026, 10, 28, 3, 43, tzinfo=UTC)


def test_parse_reduno_url_date() -> None:
    parsed = parse_reduno_url_date(
        "https://www.reduno.com.bo/noticias/foo-20261028202249", BOLIVIA
    )
    assert parsed == datetime(2026, 10, 29, 0, 22, 49, tzinfo=UTC)

    # Algunas URLs de Red Uno tienen 13 dígitos: segundos sin cero inicial.
    parsed = parse_reduno_url_date(
        "https://www.reduno.com.bo/noticias/foo-2026102821151", BOLIVIA
    )
    assert parsed == datetime(2026, 10, 29, 1, 15, 1, tzinfo=UTC)


def test_extract_code() -> None:
    assert (
        extract_code("https://unitel.bo/noticias/seguridad/foo-OB24439250")
        == "OB24439250"
    )
    assert (
        extract_code(
            "https://www.reduno.com.bo/noticias/foo-20261028202249"
        )
        == "20261028202249"
    )


def test_canonical_url_removes_tracking() -> None:
    assert (
        canonical_url(
            "https://Unitel.bo/noticias/foo/?utm_source=x&b=1#fragmento"
        )
        == "https://unitel.bo/noticias/foo?b=1"
    )


def test_clean_html_text() -> None:
    assert clean_html_text("&lt;b&gt;Hola&lt;/b&gt; &amp; adiós") == "Hola & adiós"


def test_is_recent() -> None:
    assert is_recent(NOW - timedelta(hours=2), 24, NOW)
    assert not is_recent(NOW - timedelta(hours=30), 24, NOW)
    assert not is_recent(None, 24, NOW)
