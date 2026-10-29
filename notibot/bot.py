"""Bot de Telegram: menú, comandos, envío seguro y estado."""

from __future__ import annotations

import contextlib
import html
import logging
import time
from collections.abc import Callable
from typing import Any

import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import BotCommand

from .config import Settings
from .formatting import split_message, strip_html
from .pipeline import NewsPipeline
from .storage import Storage
from .utils import format_datetime, parse_iso_datetime, truncate, utcnow

log = logging.getLogger(__name__)

MENU_BOLETIN = "📰 Boletín del Día"
MENU_SEGURIDAD = "🚨 Noticias de Seguridad"


class NotiBot:
    def __init__(
        self,
        settings: Settings,
        pipeline: NewsPipeline,
        storage: Storage,
    ) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self.storage = storage
        self.bot = telebot.TeleBot(settings.telegram_token, parse_mode=None)
        self.bot_username: str | None = None
        self.started_at = utcnow()
        self.scheduler_status: Callable[[], bool] = lambda: False
        self.next_runs_provider: Callable[[], dict[str, str]] = lambda: {}
        self._last_request: dict[int, float] = {}
        self._stopping = False
        self._register_handlers()

    # ------------------------------------------------------------------
    # Arranque y parada
    # ------------------------------------------------------------------
    def connect(self) -> None:
        me = self.bot.get_me()
        self.bot_username = me.username
        log.info(
            "Telegram conectado como @%s (id=%s)",
            me.username,
            me.id,
        )
        try:
            self.bot.set_my_commands(
                [
                    BotCommand("boletin", "Boletín general de Bolivia"),
                    BotCommand("seguridad", "Reportes de seguridad y policía"),
                    BotCommand("estado", "Estado del bot y último envío"),
                    BotCommand("fuentes", "Fuentes de noticias"),
                    BotCommand("id", "Mostrar mi chat ID y user ID"),
                    BotCommand("help", "Ayuda"),
                ]
            )
        except Exception as exc:  # noqa: BLE001 - no es crítico
            log.warning("No se pudieron registrar los comandos: %s", exc)

    def poll(self) -> None:
        while not self._stopping:
            try:
                self.bot.infinity_polling(
                    timeout=30,
                    long_polling_timeout=30,
                    skip_pending=True,
                    allowed_updates=["message"],
                    logger_level=logging.WARNING,
                )
                return
            except ApiTelegramException as exc:
                if exc.error_code == 409:
                    log.warning(
                        "Otra instancia del bot está usando el token (409). "
                        "Reintentando en 10 segundos..."
                    )
                else:
                    log.exception(
                        "Telegram rechazó el polling; reintentando en 10 segundos"
                    )
                self._sleep_unless_stopping(10)
            except Exception:  # noqa: BLE001 - el bot debe seguir vivo
                log.exception(
                    "Polling interrumpido; reintentando en 10 segundos"
                )
                self._sleep_unless_stopping(10)

    def _sleep_unless_stopping(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stopping and time.monotonic() < deadline:
            time.sleep(0.5)

    def stop(self) -> None:
        self._stopping = True
        with contextlib.suppress(Exception):
            self.bot.stop_polling()

    # ------------------------------------------------------------------
    # Envíos
    # ------------------------------------------------------------------
    def run_automatic(self, kind: str) -> bool:
        if not self.settings.chat_ids:
            log.error(
                "No hay CHAT_ID/CHAT_IDS configurado; se omite el envío automático"
            )
            return False
        log.info(
            "Enviando boletín automático %s a %s chat(s)",
            kind,
            len(self.settings.chat_ids),
        )
        return self.pipeline.run(
            kind,
            self.settings.chat_ids,
            automatic=True,
            sender=self._send_messages,
        )

    def _send_messages(self, chat_id: str, messages: list[str]) -> bool:
        all_ok = True
        for text in messages:
            if not self._send_one(chat_id, text):
                all_ok = False
        return all_ok

    def _send_one(self, chat_id: str, text: str) -> bool:
        try:
            self.bot.send_message(
                chat_id,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except ApiTelegramException as exc:
            return self._handle_api_error(chat_id, text, exc)
        except Exception as exc:  # noqa: BLE001 - red caída, chat inválido, etc.
            log.error("No se pudo enviar el mensaje a %s: %s", chat_id, exc)
            return False

    def _handle_api_error(
        self, chat_id: str, text: str, exc: ApiTelegramException
    ) -> bool:
        description = (getattr(exc, "description", "") or "").lower()

        if exc.error_code == 400 and any(
            token in description
            for token in ("parse", "entity", "tag", "too long", "unsupported")
        ):
            log.warning(
                "Telegram rechazó el HTML (%s); se reintenta como texto plano",
                description,
            )
            return self._send_plain(chat_id, text)

        if exc.error_code == 429:
            retry_after = self._retry_after(exc)
            log.warning(
                "Límite de Telegram alcanzado; esperando %s segundos",
                retry_after,
            )
            time.sleep(retry_after)
            try:
                self.bot.send_message(
                    chat_id,
                    text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return True
            except Exception as retry_exc:  # noqa: BLE001
                log.error(
                    "El reintento tras 429 también falló para %s: %s",
                    chat_id,
                    retry_exc,
                )
                return False

        if exc.error_code == 403:
            log.warning("El chat %s bloqueó al bot o no existe", chat_id)
            return False

        log.error(
            "Error de Telegram %s al enviar a %s: %s",
            exc.error_code,
            chat_id,
            description,
        )
        return False

    @staticmethod
    def _retry_after(exc: ApiTelegramException) -> int:
        result = getattr(exc, "result_json", None)
        if not isinstance(result, dict):
            return 5
        parameters = result.get("parameters")
        if not isinstance(parameters, dict):
            return 5
        try:
            value = int(parameters.get("retry_after", 5))
        except (TypeError, ValueError):
            return 5
        return max(1, min(value, 30))

    def _send_plain(self, chat_id: str, text: str) -> bool:
        plain = strip_html(text)
        for part in split_message(plain, 4000):
            try:
                self.bot.send_message(
                    chat_id,
                    part,
                    disable_web_page_preview=True,
                )
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "No se pudo enviar el texto plano a %s: %s", chat_id, exc
                )
                return False
        return True

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _register_handlers(self) -> None:
        @self.bot.message_handler(commands=["start", "menu"])
        def _start(message: telebot.types.Message) -> None:
            self._cmd_start(message)

        @self.bot.message_handler(commands=["help", "ayuda"])
        def _help(message: telebot.types.Message) -> None:
            self._cmd_help(message)

        @self.bot.message_handler(commands=["id", "chatid"])
        def _id(message: telebot.types.Message) -> None:
            self._cmd_id(message)

        @self.bot.message_handler(commands=["boletin", "general"])
        def _boletin(message: telebot.types.Message) -> None:
            self._handle_bulletin(message, "general")

        @self.bot.message_handler(commands=["seguridad", "policia"])
        def _seguridad(message: telebot.types.Message) -> None:
            self._handle_bulletin(message, "seguridad")

        @self.bot.message_handler(commands=["estado", "status"])
        def _estado(message: telebot.types.Message) -> None:
            self._cmd_estado(message)

        @self.bot.message_handler(commands=["fuentes"])
        def _fuentes(message: telebot.types.Message) -> None:
            self._cmd_fuentes(message)

        @self.bot.message_handler(
            func=lambda message: message.text == MENU_BOLETIN,
            content_types=["text"],
        )
        def _boton_boletin(message: telebot.types.Message) -> None:
            self._handle_bulletin(message, "general")

        @self.bot.message_handler(
            func=lambda message: message.text == MENU_SEGURIDAD,
            content_types=["text"],
        )
        def _boton_seguridad(message: telebot.types.Message) -> None:
            self._handle_bulletin(message, "seguridad")

    def _authorized(self, message: telebot.types.Message) -> bool:
        if not self.settings.allowed_user_ids:
            return True
        user = getattr(message, "from_user", None)
        if user is not None and user.id in self.settings.allowed_user_ids:
            return True
        user_id = user.id if user is not None else "desconocido"
        self._reply(
            message,
            "⛔ <b>Acceso restringido.</b>\n"
            f"Tu user ID es <code>{user_id}</code>.",
        )
        return False

    def _rate_limited(self, message: telebot.types.Message) -> bool:
        if self.settings.rate_limit_seconds <= 0:
            return False
        user = getattr(message, "from_user", None)
        if user is None:
            return False

        now = time.monotonic()
        last = self._last_request.get(user.id)
        if last is not None:
            elapsed = now - last
            if elapsed < self.settings.rate_limit_seconds:
                remaining = int(self.settings.rate_limit_seconds - elapsed) + 1
                self._reply(
                    message,
                    f"⏳ Espera <b>{remaining}</b> segundo(s) antes de pedir otro boletín.",
                )
                return True

        self._last_request[user.id] = now
        if len(self._last_request) > 5000:
            cutoff = now - 3600
            self._last_request = {
                key: value
                for key, value in self._last_request.items()
                if value >= cutoff
            }
        return False

    def _handle_bulletin(self, message: telebot.types.Message, kind: str) -> None:
        if not self._authorized(message):
            return
        if self._rate_limited(message):
            return

        label = "seguridad" if kind == "seguridad" else "general"
        status = self._reply(
            message,
            f"🔎 Buscando noticias <b>{label}</b> y verificando su fecha real...",
        )
        with contextlib.suppress(Exception):
            self.bot.send_chat_action(message.chat.id, "typing")

        try:
            ok = self.pipeline.run(
                kind,
                [str(message.chat.id)],
                automatic=False,
                sender=self._send_messages,
            )
        except Exception:  # noqa: BLE001 - el pipeline ya registra, pero no dejamos el chat colgado
            log.exception("Error inesperado generando el boletín %s", kind)
            ok = False

        if ok:
            self._delete(status)
            return

        text = (
            "No se encontraron noticias nuevas en este momento. "
            "Intenta de nuevo más tarde."
        )
        if status is not None:
            self._edit(status, text)
        else:
            self._send_plain(str(message.chat.id), text)

    def _cmd_start(self, message: telebot.types.Message) -> None:
        text = (
            "<b>🇧🇴 NotiBot — Noticias de Bolivia</b>\n\n"
            "Puedo enviarte un boletín con las noticias más importantes de "
            "Unitel y Red Uno, con fecha y hora reales de publicación.\n\n"
            f"⏰ Envíos automáticos: <b>{', '.join(self.settings.schedule_times)}</b> "
            f"({self.settings.timezone_name}).\n\n"
            "Usa los botones del teclado o estos comandos:\n"
            "• /boletin — boletín general\n"
            "• /seguridad — reportes policiales y de justicia\n"
            "• /estado — último envío y estado del bot\n"
            "• /fuentes — medios consultados\n"
            "• /id — tu chat ID y user ID\n"
            "• /help — ayuda"
        )
        try:
            self.bot.send_message(
                message.chat.id,
                text,
                parse_mode="HTML",
                reply_markup=self._menu(),
                disable_web_page_preview=True,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("No se pudo enviar la bienvenida: %s", exc)

    def _cmd_help(self, message: telebot.types.Message) -> None:
        self._reply(
            message,
            "<b>Ayuda de NotiBot</b>\n\n"
            "• /boletin o «📰 Boletín del Día»: resumen general.\n"
            "• /seguridad o «🚨 Noticias de Seguridad»: reportes policiales.\n"
            "• /estado: estado del scheduler, último envío y modelo usado.\n"
            "• /id: muestra el chat ID (útil para configurar CHAT_ID).\n"
            "• /fuentes: lista de medios y secciones.\n\n"
            "Las fechas se extraen del JSON-LD de cada artículo. "
            "No se usa la fecha del listado como verdad absoluta.",
        )

    def _cmd_id(self, message: telebot.types.Message) -> None:
        user = getattr(message, "from_user", None)
        user_id = user.id if user is not None else "desconocido"
        self._reply(
            message,
            "<b>🆔 Identificadores de Telegram</b>\n"
            f"Chat ID: <code>{message.chat.id}</code>\n"
            f"User ID: <code>{user_id}</code>",
        )

    def _cmd_estado(self, message: telebot.types.Message) -> None:
        self._reply(message, self._status_text())

    def _cmd_fuentes(self, message: telebot.types.Message) -> None:
        self._reply(
            message,
            "<b>📚 Fuentes consultadas</b>\n\n"
            "• <b>Unitel</b> — https://unitel.bo/noticias\n"
            "• <b>Red Uno</b> — https://www.reduno.com.bo/noticias\n"
            "• <b>Unitel Seguridad</b> — https://unitel.bo/noticias/seguridad\n"
            "• <b>Red Uno Policial</b> — https://www.reduno.com.bo/noticias/policial\n\n"
            "El scraping del listado descubre las notas; la fecha real se lee "
            "del JSON-LD de cada artículo. Si no existe, se usa la fecha de la "
            "URL de Red Uno o la del listado de Unitel como respaldo.",
        )

    def _status_text(self) -> str:
        state = self.state()
        last_success = state.get("last_success")
        if last_success:
            parsed = parse_iso_datetime(str(last_success))
            if parsed is not None:
                last_success = format_datetime(parsed, self.settings.timezone)

        last_run = state.get("last_run")
        last_run_text = "—"
        if isinstance(last_run, dict):
            status = str(last_run.get("status") or "?")
            kind = str(last_run.get("kind") or "?")
            finished = last_run.get("finished_at")
            if finished:
                parsed = parse_iso_datetime(str(finished))
                if parsed is not None:
                    finished = format_datetime(parsed, self.settings.timezone)
            last_run_text = f"{kind} / {status} / {finished or '—'}"

        scheduler = "activo" if state.get("scheduler_running") else "detenido"
        model = str(state.get("model") or "fallback")
        bot_username = state.get("bot_username")
        bot_text = f"@{bot_username}" if bot_username else "conectando..."
        last_error = state.get("last_error")
        if last_error:
            last_error = truncate(str(last_error), 200)

        return (
            "<b>🤖 Estado de NotiBot</b>\n"
            f"Versión: <code>{html.escape(self.settings.version)}</code>\n"
            f"Bot: <code>{html.escape(bot_text)}</code>\n"
            f"Zona horaria: <code>{html.escape(self.settings.timezone_name)}</code>\n"
            f"Horarios: <code>{html.escape(', '.join(self.settings.schedule_times))}</code>\n"
            f"Scheduler: <b>{scheduler}</b>\n"
            f"Último envío correcto: {html.escape(str(last_success or '—'))}\n"
            f"Última ejecución: {html.escape(last_run_text)}\n"
            f"Modelo: <code>{html.escape(model)}</code>\n"
            f"Noticias vistas: <code>{state.get('seen', 0)}</code>\n"
            f"Último error: {html.escape(str(last_error or 'ninguno'))}"
        )

    def state(self) -> dict[str, Any]:
        stats = self.storage.stats()
        try:
            scheduler_running = bool(self.scheduler_status())
        except Exception:  # noqa: BLE001
            scheduler_running = False
        try:
            next_runs = self.next_runs_provider()
        except Exception:  # noqa: BLE001
            next_runs = {}
        return {
            "status": "ok",
            "version": self.settings.version,
            "started_at": self.started_at.isoformat(),
            "bot_username": self.bot_username,
            "scheduler_running": scheduler_running,
            "last_success": self.storage.last_success(),
            "last_error": self.pipeline.last_error,
            "seen": stats.get("seen", 0),
            "last_run": stats.get("last_run"),
            "model": self.pipeline.ai.active_model
            if self.pipeline.ai is not None
            else "fallback",
            "timezone": self.settings.timezone_name,
            "next_runs": next_runs,
        }

    # ------------------------------------------------------------------
    # Utilidades de mensajes
    # ------------------------------------------------------------------
    def _menu(self) -> telebot.types.ReplyKeyboardMarkup:
        markup = telebot.types.ReplyKeyboardMarkup(
            row_width=2, resize_keyboard=True
        )
        markup.add(
            telebot.types.KeyboardButton(MENU_BOLETIN),
            telebot.types.KeyboardButton(MENU_SEGURIDAD),
        )
        return markup

    def _reply(
        self, message: telebot.types.Message, text: str, **kwargs: Any
    ) -> telebot.types.Message | None:
        try:
            return self.bot.reply_to(
                message,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("No se pudo responder en el chat %s: %s", message.chat.id, exc)
            return None

    def _delete(self, message: telebot.types.Message | None) -> None:
        if message is None:
            return
        with contextlib.suppress(Exception):
            self.bot.delete_message(message.chat.id, message.message_id)

    def _edit(self, message: telebot.types.Message, text: str) -> None:
        with contextlib.suppress(Exception):
            self.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=message.message_id,
            )
