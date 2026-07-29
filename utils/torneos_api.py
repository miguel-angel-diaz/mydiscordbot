# utils/torneos_api.py
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
from utils.commons import (
    buscar_usuario_en_servidor,
    calcular_clasificacion_torneo,
    obtener_decks_por_usuario,
    validar_torneo_para_edicion,
    limpiar_deck_raw,
    contar_cartas,
    obtener_lista_arquetipos,
    obtener_sugerencias_arquetipos,
    obtener_estado_torneos_usuario,
    inscribir_usuario_web,
    editar_deck_web)

calcular_clasificacion = calcular_clasificacion_torneo

CANAL_ADMIN_NOMBRE = "solicitudes-admision"

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PODCAST_RSS_URL = "https://feeds.ivoox.com/feed_fg_f12806786_filtro_1.xml"
MEDIUM_RSS_URL = "https://medium.com/feed/@theklubmtg"

_bot_instance = None

def set_bot_instance(bot):
    global _bot_instance
    _bot_instance = bot

# ============================================================
# MIDDLEWARE CORS (para todas las respuestas)
# ============================================================
@web.middleware
async def cors_middleware(request, handler):
    try:
        response = await handler(request)
    except Exception as e:
        print(f"❌ Error en API: {e}")
        response = web.json_response({"error": f"Error interno: {str(e)}"}, status=500)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

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
    try:
        torneos = await obtener_torneos_finalizados()
        resultado = []
        for torneo in torneos:
            try:
                clasificacion = await calcular_clasificacion(guild, torneo["codigo"])
                resultado.append({**torneo, "clasificacion": clasificacion})
            except Exception as e:
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

    except Exception as e:
        print(f"❌ Error regenerando caché: {e}")
        return {"actualizado": datetime.now(timezone.utc).isoformat(), "torneos": []}

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
    return web.json_response(data)

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

    return web.json_response({"ok": True})

# ============================================================
# 6. LOGIN — verificación de miembros vía código por DM
# ============================================================
codigos_pendientes = {}
sesiones_activas = {}

CODIGO_EXPIRA_SEGUNDOS = 300
CODIGO_REENVIO_MINIMO = 60
SESION_DURA_SEGUNDOS = 60 * 60 * 24 * 7

async def auth_solicitar_codigo(request):
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

    return web.json_response({"ok": True, "mensaje": "Código enviado por Discord"})

async def auth_verificar_codigo(request):
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

    return web.json_response({
        "ok": True,
        "session": session_token,
        "username": pendiente["username"],
    })

# utils/torneos_api.py

async def auth_verificar_sesion(request):
    """La web comprueba si una sesión sigue siendo válida."""

    session_token = request.query.get("session")

    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"autenticado": False})

    response = web.json_response({
        "autenticado": True,
        "username": sesion["username"],
        "discord_id": sesion["discord_id"],  # <--- AÑADIR ESTO
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
    return web.json_response({"episodios": episodios})

async def api_articulos(request):
    try:
        articulos = await obtener_ultimos_articulos()
    except Exception as e:
        return web.json_response({"error": str(e)}, status=503)
    return web.json_response({"articulos": articulos})

async def handle_options(request):
    return web.Response()

# ============================================================
# 8. ENDPOINTS DE USUARIO
# ============================================================
async def api_mis_torneos(request):
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
                break

    mis_resultados.sort(key=lambda x: x["fecha_fin"] or "", reverse=True)
    return web.json_response({
        "username": sesion["username"],
        "torneos": mis_resultados,
    })


async def api_mis_decks(request):
    """Devuelve los decks del usuario logueado."""
    session_token = request.query.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    discord_id = sesion["discord_id"]  # ya es un string

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    try:
        # Llamamos sin include_message para que no devuelva objetos no serializables
        decks = await obtener_decks_por_usuario(guild, discord_id, include_message=False)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

    response = web.json_response({
        "username": sesion["username"],
        "decks": decks,
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response
async def api_torneos_disponibles(request):
    session_token = request.query.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    miembro = guild.get_member(int(sesion["discord_id"]))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)

    from utils.torneos_estado import leer_estado
    estado = await leer_estado(_bot_instance)
    torneos_estado = estado.get("torneos", [])

    torneos_usuario = []
    for t in torneos_estado:
        if str(miembro.id) in t.get("inscritos_ids", []):
            torneos_usuario.append({
                "codigo": t.get("codigo"),
                "nombre": t.get("nombre", "Torneo sin nombre"),
                "estado": "activo",
                "nivel": t.get("nivel", "todos")
            })

    return web.json_response({"torneos": torneos_usuario})

async def api_arquetipos(request):
    return web.json_response({"arquetipos": obtener_lista_arquetipos()})

async def api_subir_deck(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    session_token = body.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    codigo_torneo = str(body.get("codigo_torneo", "")).strip()
    nombre_deck = str(body.get("nombre_deck", "")).strip()
    archetype_input = str(body.get("archetype", "")).strip()
    decklist_raw = str(body.get("decklist", "")).strip()
    sideboard_raw = str(body.get("sideboard", "")).strip()

    if not codigo_torneo or not nombre_deck or not archetype_input or not decklist_raw:
        return web.json_response({"error": "Faltan campos obligatorios"}, status=400)

    if len(nombre_deck) > 100:
        return web.json_response({"error": "Nombre de deck demasiado largo"}, status=400)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    discord_id = sesion["discord_id"]
    miembro = guild.get_member(int(discord_id))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía en el servidor"}, status=403)

    sugerencias = obtener_sugerencias_arquetipos(archetype_input, max_sugerencias=5)
    coincidencia_exacta = next((s for s in sugerencias if s.lower() == archetype_input.lower()), None)

    if not coincidencia_exacta:
        return web.json_response({
            "error": "Arquetipo no reconocido",
            "sugerencias": sugerencias
        }, status=400)

    archetype = coincidencia_exacta

    # Validar que el torneo aún permite subir decks (pasando el bot)
    ok, mensaje_validacion = await validar_torneo_para_edicion(codigo_torneo, miembro, _bot_instance)
    if not ok:
        return web.json_response({"error": mensaje_validacion}, status=400)

    codigo_deck = f"{codigo_torneo}_{discord_id}"
    decks_existentes = await obtener_decks_por_usuario(guild, discord_id)

    if any(d["codigo_deck"] == codigo_deck for d in decks_existentes):
        return web.json_response(
            {"error": "Ya tienes un deck subido para este torneo. Usa la edición en Discord con !editar-deck."},
            status=409
        )

    decklist = limpiar_deck_raw(decklist_raw)
    if contar_cartas(decklist) < 60:
        return web.json_response({"error": "La decklist debe tener al menos 60 cartas"}, status=400)

    if sideboard_raw.lower() in ("", "n/a"):
        sideboard = "N/A"
    else:
        sideboard_limpio = limpiar_deck_raw(sideboard_raw)
        if contar_cartas(sideboard_limpio) > 15:
            return web.json_response({"error": "La sideboard no puede superar 15 cartas"}, status=400)
        sideboard = sideboard_limpio

    embed_final = discord.Embed(
        title=f"🃏 Deck Subido: {nombre_deck}",
        description=f"**Código:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`",
        color=discord.Color.purple()
    )
    embed_final.add_field(name="Jugador", value=f"{miembro} (ID: {discord_id})", inline=False)
    embed_final.add_field(name="Archetype", value=archetype, inline=False)
    embed_final.add_field(name="Decklist", value=decklist[:1000], inline=False)
    embed_final.add_field(name="Sideboard", value=sideboard[:1000], inline=False)
    embed_final.add_field(name="edited", value="0", inline=False)
    embed_final.set_footer(text="Deck subido correctamente (vía web).")

    canal_submitted = discord.utils.get(guild.text_channels, name="submitted-decks")
    if not canal_submitted:
        return web.json_response({"error": "Canal de decks no encontrado"}, status=500)

    await canal_submitted.send(embed=embed_final)

    try:
        await miembro.send(
            f"✅ Tu deck **{nombre_deck}** ha sido enviado con éxito al torneo `{codigo_torneo}` (subido desde la web)."
        )
    except Exception:
        pass

    return web.json_response({"ok": True, "mensaje": mensaje_validacion})

# utils/torneos_api.py - api_estado_torneos

async def api_estado_torneos(request):
    session_token = request.query.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    miembro = guild.get_member(int(sesion["discord_id"]))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)

    try:
        print(f"🔍 [api_estado_torneos] Consultando torneos para usuario {miembro.display_name} (ID: {miembro.id})")
        torneos = await obtener_estado_torneos_usuario(guild, miembro)
        print(f"   ✅ Torneos devueltos: {len(torneos)}")
        for t in torneos:
            print(f"      - {t.get('codigo')} | inscrito: {t.get('inscrito')} | deck: {t.get('deck_subido')}")
    except Exception as e:
        print(f"❌ [api_estado_torneos] Error: {e}")
        return web.json_response({"error": str(e)}, status=500)

    response = web.json_response({"torneos": torneos})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def api_inscribirse(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    session_token = body.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    codigo_torneo = str(body.get("codigo_torneo", "")).strip()
    if not codigo_torneo:
        return web.json_response({"error": "Falta el código del torneo"}, status=400)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    miembro = guild.get_member(int(sesion["discord_id"]))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)

    # Usar la nueva función (sin Challonge)
    ok, mensaje = await inscribir_usuario_web(guild, miembro, codigo_torneo)

    if not ok:
        return web.json_response({"error": mensaje}, status=400)

    # Anunciar en el canal público
    canal_anuncios = discord.utils.get(guild.text_channels, name="📰-cartelera‐torneos")
    if canal_anuncios:
        await canal_anuncios.send(f"📥 {miembro.mention} se ha inscrito en el torneo `{codigo_torneo}` (vía web).")

    response = web.json_response({"ok": True, "mensaje": mensaje})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response
async def api_editar_deck(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    session_token = body.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    codigo_torneo = str(body.get("codigo_torneo", "")).strip()
    nombre_deck = str(body.get("nombre_deck", "")).strip()
    archetype_input = str(body.get("archetype", "")).strip()
    decklist_raw = str(body.get("decklist", "")).strip()
    sideboard_raw = str(body.get("sideboard", "")).strip()

    if not codigo_torneo or not nombre_deck or not archetype_input or not decklist_raw:
        return web.json_response({"error": "Faltan campos obligatorios"}, status=400)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    discord_id = sesion["discord_id"]
    miembro = guild.get_member(int(discord_id))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía en el servidor"}, status=403)

    sugerencias = obtener_sugerencias_arquetipos(archetype_input, max_sugerencias=5)
    coincidencia_exacta = next((s for s in sugerencias if s.lower() == archetype_input.lower()), None)

    if not coincidencia_exacta:
        return web.json_response({
            "error": "Arquetipo no reconocido",
            "sugerencias": sugerencias
        }, status=400)

    archetype = coincidencia_exacta

    decklist = limpiar_deck_raw(decklist_raw)
    if contar_cartas(decklist) < 60:
        return web.json_response({"error": "La decklist debe tener al menos 60 cartas"}, status=400)

    if sideboard_raw.lower() in ("", "n/a"):
        sideboard = "N/A"
    else:
        sideboard_limpio = limpiar_deck_raw(sideboard_raw)
        if contar_cartas(sideboard_limpio) > 15:
            return web.json_response({"error": "La sideboard no puede superar 15 cartas"}, status=400)
        sideboard = sideboard_limpio

    ok, mensaje = await editar_deck_web(guild, miembro, codigo_torneo, nombre_deck, archetype, decklist, sideboard)

    if not ok:
        return web.json_response({"error": mensaje}, status=400)

    return web.json_response({"ok": True, "mensaje": mensaje})


# ============================================================
# 8. SERVIDOR WEB — registro de rutas
# ============================================================
def crear_app():
    app = web.Application(middlewares=[cors_middleware])

    app.router.add_get('/api/torneos', api_torneos)
    app.router.add_post('/api/solicitar-acceso', api_solicitar_acceso)
    app.router.add_route('OPTIONS', '/api/solicitar-acceso', handle_options)

    app.router.add_get('/api/podcast', api_podcast)
    app.router.add_get('/api/articulos', api_articulos)

    app.router.add_post('/auth/solicitar-codigo', auth_solicitar_codigo)
    app.router.add_route('OPTIONS', '/auth/solicitar-codigo', handle_options)

    app.router.add_post('/auth/verificar-codigo', auth_verificar_codigo)
    app.router.add_route('OPTIONS', '/auth/verificar-codigo', handle_options)

    app.router.add_get('/auth/verificar-sesion', auth_verificar_sesion)

    app.router.add_get('/api/mis-torneos', api_mis_torneos)
    app.router.add_get('/api/mis-decks', api_mis_decks)
    app.router.add_get('/api/torneos-disponibles', api_torneos_disponibles)
    app.router.add_get('/api/arquetipos', api_arquetipos)

    app.router.add_post('/api/subir-deck', api_subir_deck)
    app.router.add_route('OPTIONS', '/api/subir-deck', handle_options)

    app.router.add_get('/api/estado-torneos', api_estado_torneos)

    app.router.add_post('/api/inscribirse', api_inscribirse)
    app.router.add_route('OPTIONS', '/api/inscribirse', handle_options)

    app.router.add_post('/api/editar-deck', api_editar_deck)
    app.router.add_route('OPTIONS', '/api/editar-deck', handle_options)

    return app

async def iniciar_servidor_web():
    app = crear_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()