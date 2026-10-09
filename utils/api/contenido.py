"""
Contenido de la web: podcast (iVoox) y artículos (Medium) desde sus RSS.

El contenido de los RSS lo escribe un tercero: se devuelve como texto plano (sin HTML ni etiquetas cortadas) y los
enlaces e imágenes solo si son https. Se guarda en caché unos minutos para no descargar los RSS en cada visita.
"""
import html
import re
import time
from urllib.parse import urlparse

import aiohttp
import feedparser
from aiohttp import web

from utils.api import comun

PODCAST_RSS_URL = "https://feeds.ivoox.com/feed_fg_f12806786_filtro_1.xml"
MEDIUM_RSS_URL = "https://medium.com/feed/@theklubmtg"

CACHE_SEGUNDOS = 600                                   # 10 minutos
TIMEOUT_RSS = aiohttp.ClientTimeout(total=10)
MAX_DESCRIPCION = 200

_cache = {}   # url -> (momento, feed)


def texto_plano(valor, limite: int = None) -> str:
    """HTML del RSS -> texto: quita etiquetas, decodifica entidades y junta los espacios."""
    texto = re.sub(r"<[^>]*>", " ", str(valor or ""))
    texto = re.sub(r"\s+", " ", html.unescape(texto)).strip()
    return texto[:limite] if limite else texto


def url_https(valor):
    """La URL si es https (nada de javascript:, data: ni http); si no, None."""
    url = str(valor or "").strip()
    return url if urlparse(url).scheme == "https" and urlparse(url).netloc else None


async def _obtener_feed(url: str):
    momento, feed = _cache.get(url, (0, None))
    if feed is not None and time.monotonic() - momento < CACHE_SEGUNDOS:
        return feed
    async with aiohttp.ClientSession(timeout=TIMEOUT_RSS) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Error al obtener feed ({resp.status})")
            contenido = await resp.text()
    feed = feedparser.parse(contenido)
    _cache[url] = (time.monotonic(), feed)
    return feed


async def obtener_ultimos_episodios(limite: int = 8):
    feed = await _obtener_feed(PODCAST_RSS_URL)
    episodios = []
    for entry in feed.entries[:limite]:
        imagen = None
        if "image" in entry:
            imagen = entry.image.get("href")
        elif hasattr(feed.feed, "image"):
            imagen = feed.feed.image.get("href")
        episodios.append({
            "titulo": texto_plano(entry.get("title", "")),
            "descripcion": texto_plano(entry.get("summary", ""), MAX_DESCRIPCION),
            "fecha": texto_plano(entry.get("published", "")),
            "enlace": url_https(entry.get("link", "")),
            "imagen": url_https(imagen),
        })
    return episodios


async def obtener_ultimos_articulos(limite: int = 8):
    feed = await _obtener_feed(MEDIUM_RSS_URL)
    articulos = []
    for entry in feed.entries[:limite]:
        articulos.append({
            "titulo": texto_plano(entry.get("title", "")),
            "descripcion": texto_plano(entry.get("summary", ""), MAX_DESCRIPCION),
            "fecha": texto_plano(entry.get("published", "")),
            "enlace": url_https(entry.get("link", "")),
        })
    return articulos


async def api_podcast(request):
    try:
        episodios = await obtener_ultimos_episodios()
    except Exception:
        return comun.error_interno("api_podcast", status=503)
    return web.json_response({"episodios": episodios})


async def api_articulos(request):
    try:
        articulos = await obtener_ultimos_articulos()
    except Exception:
        return comun.error_interno("api_articulos", status=503)
    return web.json_response({"articulos": articulos})
