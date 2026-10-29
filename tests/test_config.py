from __future__ import annotations

import pytest

from notibot.config import ConfigError, Settings

ENV_NAMES = [
    "TELEGRAM_TOKEN",
    "BOT_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "CHAT_ID",
    "CHAT_IDS",
    "ALLOWED_USER_IDS",
    "GEMINI_MODEL",
    "GEMINI_MODELS",
    "TIMEZONE",
    "SCHEDULE_TIMES",
    "PORT",
    "DATA_DIR",
    "LOG_LEVEL",
    "MAX_ARTICLES_PER_SOURCE",
    "NEWS_UNITEL",
    "NEWS_REDUNO",
    "TOTAL_NEWS",
    "REQUEST_TIMEOUT",
    "RATE_LIMIT_SECONDS",
]


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    settings = Settings.from_env(require_credentials=False)
    assert settings.timezone_name == "America/La_Paz"
    assert settings.schedule_times == ("07:00", "12:00", "19:00")
    assert settings.total_news == 5
    assert settings.gemini_models == ("gemini-2.5-flash", "gemini-2.0-flash")


def test_required_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ConfigError):
        Settings.from_env(require_credentials=True)

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("CHAT_ID", "-100123")
    settings = Settings.from_env(require_credentials=True)
    assert settings.chat_ids == ("-100123",)


def test_multiple_chats_and_allowed_users(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CHAT_IDS", "-1001, @canal")
    monkeypatch.setenv("ALLOWED_USER_IDS", "123, 456")
    settings = Settings.from_env(require_credentials=False)
    assert settings.chat_ids == ("-1001", "@canal")
    assert settings.allowed_user_ids == frozenset({123, 456})


def test_invalid_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("SCHEDULE_TIMES", "25:00")
    with pytest.raises(ConfigError):
        Settings.from_env(require_credentials=False)


def test_invalid_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("TIMEZONE", "No/Existe")
    with pytest.raises(ConfigError):
        Settings.from_env(require_credentials=False)
