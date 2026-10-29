from __future__ import annotations

from types import SimpleNamespace

from telebot.apihelper import ApiTelegramException

from notibot.bot import NotiBot


def test_poll_retries_after_409(monkeypatch) -> None:
    bot = NotiBot(
        SimpleNamespace(telegram_token="123456:ABC-DEF"),
        None,
        None,
    )
    calls = {"count": 0}

    def fake_polling(**_kwargs) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ApiTelegramException(
                "getUpdates",
                {},
                {
                    "ok": False,
                    "error_code": 409,
                    "description": "Conflict: terminated by other getUpdates request",
                },
            )
        bot._stopping = True

    monkeypatch.setattr(bot.bot, "infinity_polling", fake_polling)
    monkeypatch.setattr(bot, "_sleep_unless_stopping", lambda _seconds: None)

    bot.poll()

    assert calls["count"] == 2
