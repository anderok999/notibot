import os
import requests
import html
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from bs4 import BeautifulSoup
from google import genai

# Carga de credenciales desde variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Servidor HTTP ficticio para mantener activo Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo 24/7")

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- FUNCIONES DE SCRAPING CON FECHAS ---

def extraer_noticias_general():
    noticias = []
    fuentes = ["https://unitel.bo/noticias", "https://www.reduno.com.bo/noticias"]
    for url_fuente in fuentes:
        try:
            res = requests.get(url_fuente, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                titulo = a.get_text(strip=True)
                url = a["href"]
                time_tag = a.find_parent().find("time") if a.find_parent() else None
                fecha_str = time_tag.get_text(strip=True) if time_tag else "Hoy (Últimas 24h)"
                
                if len(titulo) > 25 and ("noticias" in url or "unitel.bo" in url or "reduno" in url):
                    if not url.startswith("http"):
                        domain = "https://unitel.bo" if "unitel" in url_fuente else "https://www.reduno.com.bo"
                        url = f"{domain}{url}"
                    if (titulo, url) not in [(t, u) for t, u, f in noticias]:
                        noticias.append((titulo, url, fecha_str))
        except Exception as e:
            print(f"Error scraping general: {e}")
    return noticias[:15]

def extraer_noticias_seguridad():
    noticias = []
    fuentes_seguridad = ["https://unitel.bo/noticias/seguridad", "https://www.reduno.com.bo/noticias/seguridad"]
    for url_fuente in fuentes_seguridad:
        try:
            res = requests.get(url_fuente, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                titulo = a.get_text(strip=True)
                url = a["href"]
                time_tag = a.find_parent().find("time") if a.find_parent() else None
                fecha_str = time_tag.get_text(strip=True) if time_tag else "Hoy"
                
                if len(titulo) > 20:
                    if not url.startswith("http"):
                        domain = "https://unitel.bo" if "unitel" in url_fuente else "https://www.reduno.com.bo"
                        url = f"{domain}{url}"
                    if (titulo, url) not in [(t, u) for t, u, f in noticias]:
                        noticias.append((titulo, url, fecha_str))
        except Exception as e:
            print(f"Error scraping seguridad: {e}")
    return noticias[:15]

# --- PROCESAMIENTO CON IA (GEMINI) ---

def procesar_con_ia(noticias_raw, tipo="general"):
    lista_txt = "\n".join([f"- Título: {t} | Enlace: {l} | Fecha: {f}" for t, l, f in noticias_raw])
    
    if tipo == "seguridad":
        instrucciones_tipo = """
        Selecciona las 5 noticias más relevantes enfocadas EXCLUSIVAMENTE en la POLICÍA BOLIVIANA, operativos, reportes policiales, seguridad ciudadana o casos judiciales recientes.
        Encabezado: <b>🚨 REPORTES DE SEGURIDAD Y POLICÍA BOLIVIANA 🚨</b>
        """
    else:
        instrucciones_tipo = """
        Selecciona las 5 noticias generales MÁS IMPORTANTES y de mayor impacto nacional de las últimas 24 horas.
        Encabezado: <b>🇧🇴 BOLETÍN INFORMATIVO DE BOLIVIA 🇧🇴</b>
        """

    prompt = f"""
    Eres un periodista y editor de noticias experto en Bolivia.
    Analiza la siguiente lista de titulares recientes de Unitel y Red Uno:

    {lista_txt}

    Instrucciones:
    1. {instrucciones_tipo}
    2. Solo incluye noticias publicadas recientemente (dentro de las últimas 24 horas).
    3. Para cada noticia redacta:
       - Título descriptivo en negrita.
       - Fecha/Hora de publicación indicada.
       - Breve resumen informativo de 1 a 2 oraciones.
       - Enlace directo a la fuente.
    4. Usa únicamente etiquetas HTML válidas para Telegram (<b>, <i>, <a href="...">). No uses Markdown.

    Formato por cada noticia:
    1. <b>[Título de la Noticia]</b>
    📅 <i>Fecha: [Fecha o 'Hoy']</i>
    [Resumen informativo]
    👉 <a href="[URL_ORIGINAL]">Leer noticia completa</a>
    """

    modelos = ["gemini-3.8-flash", "gemini-2.5-flash"]
    for modelo in modelos:
        try:
            response = client.models.generate_content(model=modelo, contents=prompt)
            return response.text
        except Exception:
            continue
            
    return "Error al generar el reporte con la IA."

# --- COMANDOS EN TELEGRAM ---

@bot.message_handler(commands=['seguridad', 'policia'])
def responder_seguridad(message):
    bot.reply_to(message, "🔍 Buscando y analizando los reportes policiales y de seguridad más recientes...")
    noticias = extraer_noticias_seguridad()
    if noticias:
        reporte = procesar_con_ia(noticias, tipo="seguridad")
        bot.send_message(message.chat.id, reporte, parse_mode="HTML", disable_web_page_preview=True)
    else:
        bot.send_message(message.chat.id, "No se encontraron reportes policiales recientes en este momento.")

@bot.message_handler(commands=['boletin', 'start'])
def responder_boletin(message):
    bot.reply_to(message, "📰 Generando el boletín con las noticias principales...")
    noticias = extraer_noticias_general()
    if noticias:
        boletin = procesar_con_ia(noticias, tipo="general")
        bot.send_message(message.chat.id, boletin, parse_mode="HTML", disable_web_page_preview=True)
    else:
        bot.send_message(message.chat.id, "No se encontraron noticias recientes.")

if __name__ == "__main__":
    # Inicia el servidor de salud en un hilo secundario
    threading.Thread(target=run_health_server, daemon=True).start()
    print("🤖 Bot iniciado y escuchando en Telegram...")
    bot.infinity_polling()