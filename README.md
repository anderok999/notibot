# NotiBot 🇧🇴

Bot de Telegram que envía un boletín con noticias de Bolivia, usando **scraping como fuente principal** y las **fechas reales de publicación** de cada artículo.

Fuentes actuales:

- [Unitel](https://unitel.bo/noticias)
- [Red Uno](https://www.reduno.com.bo/noticias)
- Secciones de seguridad: Unitel `/noticias/seguridad` y Red Uno `/noticias/policial`

## Qué hace

- Descubre notas desde los listados de Unitel y Red Uno.
- Abre cada artículo candidato y extrae `datePublished`, titular, descripción, imagen y cuerpo desde JSON-LD.
- Si un artículo no tiene JSON-LD, usa metadatos (`article:published_time`), `<time>` o la fecha de la URL de Red Uno / del listado de Unitel como respaldo.
- **No inventa “Hoy”**: si no hay fecha disponible, lo indica explícitamente.
- Filtra las últimas 24 horas y balancea el boletín (por defecto 3 notas de Unitel + 2 de Red Uno).
- Genera resúmenes con Gemini usando salida JSON estructurada. Si Gemini falla, envía un resumen automático de respaldo.
- Guarda en SQLite los códigos ya enviados para no repetir noticias en los envíos automáticos.
- Envía a Telegram con HTML escapado, división de mensajes y reintento como texto plano si Telegram rechaza el HTML.
- Tiene un scheduler con zona horaria `America/La_Paz` y horarios configurables.
- Expone `/healthz` y `/status` para Render y para el keep-alive.

## Requisitos

- Python 3.11 o superior.
- Un token de bot de Telegram (`TELEGRAM_TOKEN`).
- Una API key de Google AI Studio / Gemini (`GEMINI_API_KEY`).
- El chat, grupo o canal de destino (`CHAT_ID` o `CHAT_IDS`).

## Configuración local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Edita .env con tus valores reales
python main.py --check
```

El proyecto carga `.env` automáticamente si existe. En Render no se usa `.env`: las variables se configuran en **Environment**.

### Variables de entorno

| Variable | Obligatoria | Valor por defecto | Descripción |
|---|---:|---|---|
| `TELEGRAM_TOKEN` | Sí | — | Token del bot. También acepta `BOT_TOKEN`. |
| `GEMINI_API_KEY` | Sí | — | API key de Gemini. También acepta `GOOGLE_API_KEY`. |
| `CHAT_ID` | Sí* | — | Chat/grupo/canal destino. |
| `CHAT_IDS` | Sí* | — | Varios destinos separados por coma. Tiene prioridad sobre `CHAT_ID`. |
| `ALLOWED_USER_IDS` | No | vacío | Si se define, solo esos user IDs pueden pedir boletines. |
| `TIMEZONE` | No | `America/La_Paz` | Zona horaria del scheduler. |
| `SCHEDULE_TIMES` | No | `07:00,12:00,19:00` | Horarios de envío automático, separados por coma. |
| `GEMINI_MODELS` | No | `gemini-2.5-flash,gemini-2.0-flash` | Modelos en orden de intento. |
| `MAX_ARTICLES_PER_SOURCE` | No | `20` | Artículos candidatos a inspeccionar por fuente. |
| `NEWS_UNITEL` | No | `3` | Notas de Unitel en el boletín. |
| `NEWS_REDUNO` | No | `2` | Notas de Red Uno en el boletín. |
| `TOTAL_NEWS` | No | `5` | Total de notas del boletín. |
| `REQUEST_TIMEOUT` | No | `20` | Timeout de scraping en segundos. |
| `RATE_LIMIT_SECONDS` | No | `60` | Espera mínima entre pedidos manuales por usuario. |
| `PORT` | No | `8080` | Puerto del health server (Render lo asigna). |
| `DATA_DIR` | No | `data` | Carpeta de SQLite. |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL`. |

\* Debes configurar `CHAT_ID` o `CHAT_IDS`. Para obtener el ID, inicia el bot y usa `/id`.

## Uso

```powershell
# Validación de configuración (no muestra secretos)
python main.py --check

# Scraping real, sin enviar nada a Telegram
python main.py --dry-run

# Dry-run usando Gemini (requiere GEMINI_API_KEY)
python main.py --dry-run --with-ai

# Un envío inmediato y termina
python main.py --once general
python main.py --once seguridad

# Servicio completo: Telegram + scheduler + health server
python main.py
```

En Telegram:

- `/start` o `/menu`: bienvenida y teclado.
- `/boletin` o «📰 Boletín del Día»: boletín general.
- `/seguridad` o «🚨 Noticias de Seguridad»: reportes policiales y de justicia.
- `/estado`: estado del scheduler, último envío y modelo usado.
- `/fuentes`: fuentes y secciones.
- `/id`: chat ID y user ID.
- `/help`: ayuda.

## Endpoints

| Ruta | Respuesta |
|---|---|
| `/` | `NotiBot activo 24/7` (texto plano). |
| `/healthz` | JSON. `200` si el scheduler está activo; `503` si está caído. |
| `/status` | JSON con versión, usuario del bot, último envío, último error, cantidad de noticias vistas y próximas ejecuciones. |

`/status` no expone tokens ni claves.

## Render

El servicio actual está en `https://notibot-ww99.onrender.com/`.

Configuración recomendada en Render:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `python main.py`
- **Health check path:** `/healthz`
- **Environment:** `TELEGRAM_TOKEN`, `GEMINI_API_KEY`, `CHAT_ID` o `CHAT_IDS`.
- Opcionalmente: `ALLOWED_USER_IDS`, `TIMEZONE`, `SCHEDULE_TIMES`, `GEMINI_MODELS`, `DATA_DIR`.

Si el servicio está conectado al repositorio con **Auto-Deploy**, un push a `main` reconstruye y reinicia el bot. Después del deploy verifica:

```powershell
Invoke-RestMethod https://notibot-ww99.onrender.com/healthz
Invoke-RestMethod https://notibot-ww99.onrender.com/status
```

El endpoint `/status` debe mostrar `"scheduler_running": true` y un `bot_username`. Si no aparece el usuario del bot, revisa los logs de Render y el token.

### Persistencia

SQLite se guarda en `DATA_DIR/notibot.db`. En el plan gratuito de Render el disco es efímero: al redeploy o reinicio se pierde el historial de noticias vistas. Para persistirlo, monta un disco persistente y configura `DATA_DIR` a su ruta (por ejemplo `/var/data`). El bot funciona sin disco persistente, pero puede repetir alguna noticia después de un reinicio.

## Keep-alive

`.github/workflows/keepalive.yml` hace ping a `/healthz` cada 10 minutos. Render duerme los servicios gratuitos tras unos 15 minutos sin tráfico; el ping reduce las probabilidades de suspensión, pero **no es una garantía**:

- GitHub Actions puede retrasar el cron.
- GitHub desactiva los workflows programados tras 60 días sin actividad en el repositorio.
- El plan gratuito de Render tiene límite mensual de horas.

Para producción estable, usa un plan pago de Render o un monitor externo (UptimeRobot, cron-job.org, etc.) que llame a `/healthz`.

## Pruebas

```powershell
ruff check .
pytest
```

Las pruebas no llaman a Telegram, Gemini ni a los sitios de noticias: usan HTML sintético y mocks.

## Estructura

```
main.py                    # CLI y arranque
notibot/
  config.py                # variables de entorno validadas
  models.py                # NewsItem
  utils.py                 # fechas, URLs, texto, caché
  sources/
    base.py                # HTTP, JSON-LD, parseo de artículo
    unitel.py              # listado de Unitel
    reduno.py              # listado de Red Uno
  ai.py                    # Gemini + salida JSON + fallback
  formatting.py            # HTML seguro y división de mensajes
  storage.py               # SQLite (vistas/ejecuciones)
  pipeline.py              # recolección, filtro, balance, envío
  scheduler.py             # APScheduler
  health.py                # /healthz y /status
  bot.py                   # Telegram
tests/                     # pruebas unitarias
```

## Notas de seguridad

- No subas `.env` ni tokens al repositorio.
- Si un token se expone, rótalo en BotFather y en Render.
- Usa `ALLOWED_USER_IDS` si el bot no debe ser público.
- Los logs no imprimen tokens ni la API key.
