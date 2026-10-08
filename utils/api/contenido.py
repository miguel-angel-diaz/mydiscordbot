"""Contenido de la web: podcast (iVoox) y artículos (Medium) desde sus RSS."""
import aiohttp
import feedparser
from aiohttp import web

from utils.api import comun

PODCAST_RSS_URL = "https://feeds.ivoox.com/feed_fg_f12806786_filtro_1.xml"
MEDIUM_RSS_URL = "https://medium.com/feed/@theklubmtg"


async def _obtener_feed(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Error al obtener feed ({resp.status})")
            contenido = await resp.text()
    return feedparser.parse(contenido)


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
            "titulo": entry.get("title", ""),
            "descripcion": entry.get("summary", "")[:200],
            "fecha": entry.get("published", ""),
            "enlace": entry.get("link", ""),
            "imagen": imagen,
        })
    return episodios


async def obtener_ultimos_articulos(limite: int = 8):
    feed = await _obtener_feed(MEDIUM_RSS_URL)
    articulos = []
    for entry in feed.entries[:limite]:
        articulos.append({
            "titulo": entry.get("title", ""),
            "descripcion": entry.get("summary", "")[:200].replace("<p>", "").replace("</p>", ""),
            "fecha": entry.get("published", ""),
            "enlace": entry.get("link", ""),
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
