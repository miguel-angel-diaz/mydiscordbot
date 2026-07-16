# torneos_api.py
# ============================================================
# Módulo autocontenido: obtiene todos los torneos finalizados
# de Challonge, calcula sus clasificaciones cruzando con
# Discord, y expone endpoints HTTP para que la web consuma
# los datos ya procesados, envíe solicitudes de admisión,
# gestione el login de miembros vía código por DM, y sirva
# el podcast y los artículos de Medium.
# ============================================================

import aiohttp
import discord
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from aiohttp import web

import feedparser

import config
from utils.commons import buscar_usuario_en_servidor, calcular_clasificacion_torneo, obtener_decks_por_usuario

calcular_clasificacion = calcular_clasificacion_torneo


CANAL_ADMIN_NOMBRE = "solicitudes-admision"

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PODCAST_RSS_URL = "https://feeds.ivoox.com/feed_fg_f12806786_filtro_1.xml"
MEDIUM_RSS_URL = "https://medium.com/feed/@theklubmtg"

_bot_instance = None


def set_bot_instance(bot):
    """Llamar desde bot.py una vez el bot esté creado, para que este
    módulo pueda acceder a bot.get_guild() sin importarlo directamente."""
    global _bot_instance
    _bot_instance = bot


# ============================================================
# 1. CHALLONGE — listar torneos finalizados
# ============================================================

async def obtener_torneos_finalizados():
    url = "https://api.challonge.com/v1/tournaments.json"
    params = {"state": "ended"}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            params=params,
            auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)
        ) as resp:
            if resp.status != 200:
                raise Exception(f"Error al obtener torneos ({resp.status})")
            torneos_raw = await resp.json()

    torneos = []
    for t in torneos_raw:
        torneo = t["tournament"]
        torneos.append({
            "codigo": torneo["url"],
            "nombre": torneo["name"],
            "fecha_inicio": torneo.get("started_at"),
            "fecha_fin": torneo.get("completed_at"),
            "participantes_count": torneo.get("participants_count"),
        })

    return torneos

# ============================================================
# 3. CACHÉ — evita golpear Challonge/Discord en cada visita web
# ============================================================

async def regenerar_cache(guild):
    torneos = await obtener_torneos_finalizados()

    resultado = []
    for torneo in torneos:
        try:
            clasificacion = await calcular_clasificacion(guild, torneo["codigo"])
            resultado.append({**torneo, "clasificacion": clasificacion})
        except Exception as e:
            print(f"⚠️ Error procesando {torneo['codigo']}: {e}")
            continue

    payload = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "torneos": resultado
    }

    os.makedirs("cache", exist_ok=True)
    with open(config.CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"✅ Caché regenerado con {len(resultado)} torneo(s).")
    return payload


def leer_cache():
    if not os.path.exists(config.CACHE_PATH):
        return None
    with open(config.CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 4. ENDPOINTS HTTP — Torneos
# ============================================================

async def api_torneos(request):
    data = leer_cache()
    if data is None:
        return web.json_response({"error": "Caché no disponible todavía"}, status=503)

    response = web.json_response(data)
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


# ============================================================
# 5. ENDPOINTS HTTP — Admisión
# ============================================================

async def api_solicitar_acceso(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    discord_nick = str(body.get("discord_nick", "")).strip()
    email = str(body.get("email", "")).strip()
    comentario = str(body.get("comentario", "")).strip()

    if not discord_nick or len(discord_nick) > 100:
        return web.json_response({"error": "Usuario de Discord no válido"}, status=400)

    if not EMAIL_REGEX.match(email):
        return web.json_response({"error": "Email no válido"}, status=400)

    if not comentario or len(comentario) > 1000:
        return web.json_response({"error": "Comentario no válido"}, status=400)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    canal = discord.utils.get(guild.text_channels, name=CANAL_ADMIN_NOMBRE)
    if not canal:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    embed = discord.Embed(
        title="📩 Nueva solicitud de admisión",
        color=0xff8800
    )
    embed.add_field(name="Discord", value=discord_nick, inline=True)
    embed.add_field(name="Email", value=email, inline=True)
    embed.add_field(name="Comentario", value=comentario, inline=False)
    embed.timestamp = datetime.now(timezone.utc)

    await canal.send(embed=embed)

    response = web.json_response({"ok": True})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


# ============================================================
# 6. LOGIN — verificación de miembros vía código por DM
# ============================================================

codigos_pendientes = {}
sesiones_activas = {}

CODIGO_EXPIRA_SEGUNDOS = 300              # 5 minutos
CODIGO_REENVIO_MINIMO = 60                # no permitir reenvío antes de 60s
SESION_DURA_SEGUNDOS = 60 * 60 * 24 * 7   # 7 días


async def auth_solicitar_codigo(request):
    """Paso 1: el usuario pide el código, se lo mandamos por DM."""

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    nombre = str(body.get("nombre", "")).strip()

    if not nombre:
        return web.json_response({"error": "Escribe tu usuario de Discord"}, status=400)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    nombre_key = nombre.lower()

    pendiente_actual = codigos_pendientes.get(nombre_key)
    if pendiente_actual:
        segundos_desde_envio = time.time() - pendiente_actual.get("enviado_en", 0)
        if segundos_desde_envio < CODIGO_REENVIO_MINIMO:
            espera = int(CODIGO_REENVIO_MINIMO - segundos_desde_envio)
            return web.json_response(
                {"error": f"Espera {espera}s antes de pedir un nuevo código"},
                status=429
            )

    miembro = buscar_usuario_en_servidor(guild, nombre)

    if not miembro:
        return web.json_response(
            {"error": "No hemos podido verificarte. Comprueba tu usuario."},
            status=404
        )

    codigo = f"{secrets.randbelow(1000000):06d}"

    codigos_pendientes[nombre_key] = {
        "codigo": codigo,
        "discord_id": str(miembro.id),
        "username": miembro.display_name,
        "expira": time.time() + CODIGO_EXPIRA_SEGUNDOS,
        "enviado_en": time.time(),
    }

    try:
        await miembro.send(
            f"🔐 Tu código de acceso para **The Klub** es: **{codigo}**\n"
            f"Caduca en 5 minutos. Si no has solicitado esto, ignora este mensaje."
        )
    except Exception:
        del codigos_pendientes[nombre_key]
        return web.json_response(
            {"error": "No hemos podido enviarte el código. Revisa que tienes los DMs abiertos para miembros del servidor."},
            status=400
        )

    response = web.json_response({"ok": True, "mensaje": "Código enviado por Discord"})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


async def auth_verificar_codigo(request):
    """Paso 2: el usuario introduce el código recibido por DM."""

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    nombre = str(body.get("nombre", "")).strip().lower()
    codigo_introducido = str(body.get("codigo", "")).strip()

    pendiente = codigos_pendientes.get(nombre)

    if not pendiente:
        return web.json_response({"error": "No hay ningún código pendiente para ese usuario"}, status=400)

    if time.time() > pendiente["expira"]:
        del codigos_pendientes[nombre]
        return web.json_response({"error": "El código ha caducado, solicita uno nuevo"}, status=400)

    if codigo_introducido != pendiente["codigo"]:
        return web.json_response({"error": "Código incorrecto"}, status=400)

    session_token = secrets.token_urlsafe(32)

    sesiones_activas[session_token] = {
        "discord_id": pendiente["discord_id"],
        "username": pendiente["username"],
        "expira": time.time() + SESION_DURA_SEGUNDOS,
    }

    del codigos_pendientes[nombre]

    response = web.json_response({
        "ok": True,
        "session": session_token,
        "username": pendiente["username"],
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


async def auth_verificar_sesion(request):
    """La web comprueba si una sesión sigue siendo válida."""

    session_token = request.query.get("session")

    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"autenticado": False})

    response = web.json_response({
        "autenticado": True,
        "username": sesion["username"],
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


# ============================================================
# 7. CONTENIDO — Podcast y Artículos (RSS)
# ============================================================

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
    except Exception as e:
        return web.json_response({"error": str(e)}, status=503)

    response = web.json_response({"episodios": episodios})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


async def api_articulos(request):
    try:
        articulos = await obtener_ultimos_articulos()
    except Exception as e:
        return web.json_response({"error": str(e)}, status=503)

    response = web.json_response({"articulos": articulos})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


async def handle_options(request):
    return web.Response(headers={
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    })


# ============================================================
# 8. SERVIDOR WEB — registro de rutas
# ============================================================

def crear_app():
    app = web.Application()

    app.router.add_get('/api/torneos', api_torneos)

    app.router.add_post('/api/solicitar-acceso', api_solicitar_acceso)
    app.router.add_route('OPTIONS', '/api/solicitar-acceso', handle_options)

    app.router.add_get('/api/podcast', api_podcast)
    app.router.add_get('/api/articulos', api_articulos)

    app.router.add_post('/auth/solicitar-codigo', auth_solicitar_codigo)
    app.router.add_post('/auth/verificar-codigo', auth_verificar_codigo)
    app.router.add_get('/auth/verificar-sesion', auth_verificar_sesion)
    app.router.add_get('/api/mis-torneos', api_mis_torneos)
    app.router.add_get('/api/mis-decks', api_mis_decks)

    return app


async def iniciar_servidor_web():
    app = crear_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def api_mis_torneos(request):
    """Devuelve solo los torneos/resultados del usuario logueado."""

    session_token = request.query.get("session")

    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    discord_id = sesion["discord_id"]

    data = leer_cache()
    if data is None:
        return web.json_response({"error": "Datos no disponibles todavía"}, status=503)

    mis_resultados = []

    for torneo in data.get("torneos", []):
        for jugador in torneo.get("clasificacion", []):
            if jugador.get("discord_id") == discord_id:
                mis_resultados.append({
                    "torneo_nombre": torneo["nombre"],
                    "torneo_codigo": torneo["codigo"],
                    "fecha_fin": torneo["fecha_fin"],
                    "rank": jugador["rank"],
                    "total_participantes": torneo["participantes_count"],
                    "mp": jugador["mp"],
                    "wins": jugador["wins"],
                    "losses": jugador["losses"],
                    "draws": jugador["draws"],
                    "omw": jugador["omw"],
                    "buchholz": jugador["buchholz"],
                    "diff": jugador["diff"],
                })
                break  # ya encontramos su fila en este torneo, pasamos al siguiente

    # Ordenamos por fecha, más reciente primero
    mis_resultados.sort(key=lambda x: x["fecha_fin"] or "", reverse=True)

    response = web.json_response({
        "username": sesion["username"],
        "torneos": mis_resultados,
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def api_mis_decks(request):
    """Devuelve los decks del usuario logueado."""

    session_token = request.query.get("session")

    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    discord_id = sesion["discord_id"]

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    try:
        decks = await obtener_decks_por_usuario(guild, discord_id)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

    response = web.json_response({
        "username": sesion["username"],
        "decks": decks,
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response