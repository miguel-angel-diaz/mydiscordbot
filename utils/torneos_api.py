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
from flask import app

import config
from utils.commons import (
    buscar_usuario_en_servidor,
    calcular_clasificacion_torneo,
    obtener_deck_en_canal,
    obtener_decks_por_usuario,
    validar_torneo_para_edicion,
    limpiar_deck_raw,
    contar_cartas,
    obtener_lista_arquetipos,
    obtener_sugerencias_arquetipos,
    inscribir_usuario_web,
    tiene_rol_permitido,
    editar_deck_web)

from utils.torneos_estado import leer_estado, leer_rondas
from utils.jugadores import actualizar_proximas_partidas
from utils.swiss_core import reportar_resultado, calcular_clasificacion, desinscribir_jugador

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
    # 1️⃣ Obtener torneos finalizados de Challonge (caché)
    data = leer_cache()
    torneos_challonge = data.get("torneos", []) if data else []

    # 2️⃣ Obtener torneos Swiss finalizados del estado
    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    estado = await leer_estado(_bot_instance)
    torneos_swiss = estado.get("torneos", [])
    torneos_swiss_finalizados = []

    for t in torneos_swiss:
        if t.get("estado") == "finalizado" and t.get("tipo") == "swiss":
            # Calcular clasificación para torneos Swiss finalizados
            try:
                clasificacion = await calcular_clasificacion(_bot_instance, t["codigo"])
                # Formatear igual que Challonge
                clasificacion_formateada = []
                for p in clasificacion:
                    try:
                        member = await guild.fetch_member(int(p["id"]))
                        nombre = member.display_name
                        avatar = str(member.display_avatar.url)
                    except:
                        nombre = f"Usuario {p['id']}"
                        avatar = None
                    clasificacion_formateada.append({
                        "rank": p["rk"],
                        "nombre": nombre,
                        "wins": p["w"],
                        "losses": p["l"],
                        "draws": p["dw"],
                        "mp": p["mp"],
                        "omw": p["omw"],
                        "buchholz": p["bch"],
                        "diff": p["dif"],
                        "discord_id": p["id"],
                        "avatar": avatar
                    })
                torneos_swiss_finalizados.append({
                    "codigo": t["codigo"],
                    "nombre": t["nombre"],
                    "fecha_fin": t.get("fecha_fin") or t.get("fecha_inicio"),
                    "participantes_count": len(t.get("inscritos_ids", [])),
                    "clasificacion": clasificacion_formateada
                })
            except Exception as e:
                print(f"Error al procesar Swiss {t['codigo']}: {e}")

    # 3️⃣ Combinar ambas listas
    todos_los_torneos = torneos_challonge + torneos_swiss_finalizados
    # Ordenar por fecha (más reciente primero)
    todos_los_torneos.sort(key=lambda x: x.get("fecha_fin") or "", reverse=True)

    response = web.json_response({"torneos": todos_los_torneos})
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

async def auth_verificar_sesion(request):
    """La web comprueba si una sesión sigue siendo válida."""

    session_token = request.query.get("session")

    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"autenticado": False})

    response = web.json_response({
        "autenticado": True,
        "username": sesion["username"],
        "discord_id": sesion["discord_id"],
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

    discord_id = sesion["discord_id"]

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    try:
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
        estado = await leer_estado(_bot_instance)
        torneos_estado = estado.get("torneos", [])

        decks_usuario = await obtener_decks_por_usuario(guild, str(miembro.id), include_message=False)
        decks_por_torneo = {d["codigo_torneo"]: d for d in decks_usuario if d.get("codigo_torneo")}

        torneos_respuesta = []
        for t in torneos_estado:
            codigo = t.get("codigo")
            if not codigo:
                continue

            if t.get("estado") not in ("abierto", "en desarrollo"):
                continue

            nivel = t.get("nivel", "todos").lower()
            roles_permitidos = config.ROLES_SOCIOS if nivel == "socios" else config.ROLES_TODOS
            if not tiene_rol_permitido(miembro, roles_permitidos):
                continue

            inscritos_ids = t.get("inscritos_ids", [])
            total_inscritos = len(inscritos_ids)
            total_maximo = t.get("total_maximo")
            if total_maximo is not None:
                try:
                    total_maximo = int(total_maximo)
                except (ValueError, TypeError):
                    total_maximo = None

            inscrito = str(miembro.id) in inscritos_ids

            deck_info = decks_por_torneo.get(codigo)
            deck_subido = bool(deck_info)
            deck_edited = deck_info.get("edited", 0) if deck_info else 0

            torneos_respuesta.append({
                "codigo": codigo,
                "nombre": t.get("nombre", "Torneo sin nombre"),
                "nivel": nivel.capitalize(),
                "fecha_inicio": t.get("fecha_inicio", "Sin fecha"),
                "total_inscritos": total_inscritos,
                "total_maximo": total_maximo,
                "plazas_restantes": total_maximo - total_inscritos if total_maximo else None,
                "inscrito": inscrito,
                "estado": t.get("estado", "abierto"),
                "deck_subido": deck_subido,
                "deck_edited": deck_edited,
                "tiene_deck": deck_subido,
                "puede_editar": (
                    t.get("estado") == "abierto" or
                    (t.get("estado") == "en desarrollo" and deck_edited < 1)
                ) if deck_subido else False,
                "puede_inscribirse": not inscrito and t.get("estado") == "abierto",
                "puede_desinscribirse": inscrito and t.get("estado") == "abierto"
            })

    except Exception as e:
        print(f"❌ [api_estado_torneos] Error: {e}")
        return web.json_response({"error": str(e)}, status=500)

    response = web.json_response({"torneos": torneos_respuesta})
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

    ok, mensaje = await inscribir_usuario_web(guild, miembro, codigo_torneo)

    if not ok:
        return web.json_response({"error": mensaje}, status=400)

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

async def api_todas_partidas(request):
    print("🔹 [api_todas_partidas] INICIO")

    session_token = request.query.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        print("❌ Sesión no válida o expirada")
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        print("❌ Bot no disponible")
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        print("❌ Guild no encontrado")
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    print(f"✅ Guild encontrado: {guild.name}")

    canal = discord.utils.get(guild.text_channels, name="partidos-agendados")
    if not canal:
        print("❌ Canal #partidos-agendados no encontrado")
        return web.json_response({"partidas": []})

    print(f"✅ Canal encontrado: #{canal.name}")

    partidas = []
    patron = re.compile(
        r"📅 \[EVENTO\] (\d{2}/\d{2}/\d{4}) (\d{2}:\d{2}) \| (.+?) vs (.+?) \| Agendado por (.+)"
    )

    async for mensaje in canal.history(limit=500):
        match = patron.search(mensaje.content)
        if not match:
            continue

        fecha, hora, jugador1_raw, jugador2_raw, agendado_por = match.groups()

        jugador1_match = re.search(r"<@!?(\d+)>", jugador1_raw)
        jugador2_match = re.search(r"<@!?(\d+)>", jugador2_raw)

        jugador1_id = int(jugador1_match.group(1)) if jugador1_match else None
        jugador2_id = int(jugador2_match.group(1)) if jugador2_match else None

        try:
            j1_member = await guild.fetch_member(jugador1_id) if jugador1_id else None
            j1_nombre = j1_member.display_name if j1_member else jugador1_raw.strip()
        except:
            j1_nombre = jugador1_raw.strip()

        try:
            j2_member = await guild.fetch_member(jugador2_id) if jugador2_id else None
            j2_nombre = j2_member.display_name if j2_member else jugador2_raw.strip()
        except:
            j2_nombre = jugador2_raw.strip()

        agendado_match = re.search(r"<@!?(\d+)>", agendado_por)
        if agendado_match:
            agendado_id = int(agendado_match.group(1))
            try:
                ag_member = await guild.fetch_member(agendado_id)
                ag_nombre = ag_member.display_name
            except:
                ag_nombre = agendado_por.strip()
        else:
            ag_nombre = agendado_por.strip()

        partidas.append({
            "fecha": fecha,
            "hora": hora,
            "jugador1": j1_nombre,
            "jugador1_id": jugador1_id,
            "jugador2": j2_nombre,
            "jugador2_id": jugador2_id,
            "agendado_por": ag_nombre
        })

    print(f"✅ Total partidas encontradas: {len(partidas)}")
    response = web.json_response({"partidas": partidas})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def api_desinscribirse(request):
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

    from utils.swiss_core import desinscribir_jugador
    ok, mensaje = await desinscribir_jugador(_bot_instance, codigo_torneo, miembro.id, guild)

    if not ok:
        return web.json_response({"error": mensaje}, status=400)

    # Anunciar en el canal público
    canal_anuncios = discord.utils.get(guild.text_channels, name="📰-cartelera‐torneos")
    if canal_anuncios:
        await canal_anuncios.send(f"📤 {miembro.mention} se ha desinscrito del torneo `{codigo_torneo}` (vía web).")

    response = web.json_response({"ok": True, "mensaje": mensaje})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def api_mis_torneos_pendientes(request):
    session_token = request.query.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    discord_id = sesion["discord_id"]
    miembro = guild.get_member(int(discord_id))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)

    try:
        estado = await leer_estado(_bot_instance)
        torneos_estado = estado.get("torneos", [])

        resultado = []

        for t in torneos_estado:
            codigo = t.get("codigo")
            if not codigo:
                continue

            if t.get("estado") == "finalizado":
                continue
            if str(discord_id) not in t.get("inscritos_ids", []):
                continue

            rondas_data = await leer_rondas(_bot_instance, codigo)
            if not rondas_data:
                continue
            rondas = rondas_data.get("rondas", [])
            if not rondas:
                continue

            ronda_actual = None
            for r in reversed(rondas):
                if not r.get("completa", False):
                    ronda_actual = r
                    break
            if not ronda_actual:
                continue

            emparejamientos = ronda_actual.get("emparejamientos", [])
            pendientes = []

            for emp in emparejamientos:
                if emp.get("resultado") is not None:
                    continue
                j1 = emp.get("j1")
                j2 = emp.get("j2")

                try:
                    member1 = await guild.fetch_member(int(j1))
                    nombre1 = member1.display_name
                except:
                    nombre1 = f"Usuario {j1}"

                if j2 is None:
                    pendientes.append({
                        "jugador1": nombre1,
                        "jugador1_id": j1,
                        "jugador2": "BYE",
                        "jugador2_id": None,
                        "resultado": None
                    })
                else:
                    try:
                        member2 = await guild.fetch_member(int(j2))
                        nombre2 = member2.display_name
                    except:
                        nombre2 = f"Usuario {j2}"

                    pendientes.append({
                        "jugador1": nombre1,
                        "jugador1_id": j1,
                        "jugador2": nombre2,
                        "jugador2_id": j2,
                        "resultado": None
                    })

            if pendientes:
                resultado.append({
                    "codigo": codigo,
                    "nombre": t.get("nombre", "Torneo sin nombre"),
                    "ronda": ronda_actual.get("numero", 0),
                    "pendientes": pendientes
                })

        response = web.json_response({"torneos": resultado})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    except Exception as e:
        print(f"❌ Error en api_mis_torneos_pendientes: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def api_reportar_resultado(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    session_token = body.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    codigo_torneo = str(body.get("codigo_torneo", "")).strip()
    jugador1_id = body.get("jugador1_id")
    jugador2_id = body.get("jugador2_id")
    resultado = str(body.get("resultado", "")).strip()

    if not codigo_torneo or not jugador1_id or not jugador2_id or not resultado:
        return web.json_response({"error": "Faltan datos"}, status=400)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    miembro = guild.get_member(int(sesion["discord_id"]))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)

    es_admin = miembro.guild_permissions.administrator
    es_jugador = miembro.id in (jugador1_id, jugador2_id)
    if not es_admin and not es_jugador:
        return web.json_response({"error": "No tienes permiso para reportar este resultado"}, status=403)

    # Importar funciones necesarias
    from utils.swiss_core import reportar_resultado, publicar_clasificacion_swiss
    from utils.torneos_estado import leer_rondas

    # 1️⃣ Reportar el resultado
    ok, mensaje, emp, emp_idx = await reportar_resultado(
        _bot_instance, codigo_torneo, jugador1_id, resultado, jugador2_id, guild
    )

    if not ok:
        return web.json_response({"error": mensaje}, status=400)

    # 2️⃣ Obtener la ronda actual para actualizar el mensaje de citas
    try:
        rondas_data = await leer_rondas(_bot_instance, codigo_torneo)
        if rondas_data:
            rondas = rondas_data.get("rondas", [])
            if rondas:
                ronda_actual = rondas[-1]
                ronda_num = ronda_actual.get("numero", 0)

                # Obtener nombres de los jugadores para el mensaje
                try:
                    j1_member = await guild.fetch_member(int(jugador1_id))
                    nombre1 = j1_member.display_name
                except:
                    nombre1 = f"Usuario {jugador1_id}"
                try:
                    j2_member = await guild.fetch_member(int(jugador2_id))
                    nombre2 = j2_member.display_name
                except:
                    nombre2 = f"Usuario {jugador2_id}"

                # 3️⃣ Actualizar mensaje de citas a ciegas (eliminar la línea del partido)
                canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
                if canal_citas and emp is not None:
                    async for msg in canal_citas.history(limit=200):
                        if msg.author == _bot_instance.user and f"Emparejamientos Ronda {ronda_num} - Torneo {codigo_torneo}" in msg.content:
                            lines = msg.content.splitlines()
                            nuevas_lines = []
                            # Mantener el título
                            if lines:
                                nuevas_lines.append(lines[0])
                            # Reconstruir las líneas de partidos, omitiendo el que se reportó
                            for line in lines[1:]:
                                # Si la línea contiene ambos jugadores, la saltamos
                                if (f"<@{jugador1_id}>" in line and f"<@{jugador2_id}>" in line) or \
                                   (f"<@{jugador2_id}>" in line and f"<@{jugador1_id}>" in line):
                                    continue
                                nuevas_lines.append(line)
                            if len(nuevas_lines) <= 1:
                                await msg.delete()
                            else:
                                await msg.edit(content="\n".join(nuevas_lines))
                            break

                # 4️⃣ Enviar anuncio al canal de resultados
                canal_resultados = discord.utils.get(guild.text_channels, name="🍺-quién‐se‐lleva‐la‐ronda")
                if canal_resultados:
                    # Determinar ganador
                    try:
                        s1, s2 = map(int, resultado.split("-"))
                    except:
                        s1 = s2 = 0
                    if s1 > s2:
                        ganador = nombre1
                    elif s2 > s1:
                        ganador = nombre2
                    else:
                        ganador = "Empate"
                    await canal_resultados.send(
                        f"🏆 Resultado reportado en `{codigo_torneo}`:\n"
                        f"**{nombre1}** {resultado} **{nombre2}**\n"
                        f"🏅 Ganador: {ganador}"
                    )

                # 5️⃣ Actualizar clasificación siempre
                await publicar_clasificacion_swiss(_bot_instance, guild, codigo_torneo)

    except Exception as e:
        print(f"⚠️ Error al actualizar canales: {e}")
        # No devolvemos error al frontend, solo log

    response = web.json_response({"ok": True, "mensaje": mensaje})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def api_mis_enfrentamientos(request):
    session_token = request.query.get("session")
    torneo_codigo = request.query.get("torneo")

    if not torneo_codigo:
        return web.json_response({"error": "Falta el código del torneo"}, status=400)

    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    discord_id = sesion["discord_id"]
    miembro = guild.get_member(int(discord_id))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)

    try:
        estado = await leer_estado(_bot_instance)
        torneo = next((t for t in estado.get("torneos", []) if t.get("codigo") == torneo_codigo), None)
        if not torneo:
            return web.json_response({"error": "Torneo no encontrado"}, status=404)
        if str(discord_id) not in torneo.get("inscritos_ids", []):
            return web.json_response({"error": "No estás inscrito en este torneo"}, status=403)

        rondas_data = await leer_rondas(_bot_instance, torneo_codigo)
        if not rondas_data:
            return web.json_response({"enfrentamientos": []})

        rondas = rondas_data.get("rondas", [])
        enfrentamientos = []

        for ronda in rondas:
            ronda_num = ronda.get("numero")
            for emp in ronda.get("emparejamientos", []):
                j1 = emp.get("j1")
                j2 = emp.get("j2")
                resultado = emp.get("resultado")

                if str(discord_id) not in (j1, j2):
                    continue

                es_j1 = str(discord_id) == j1
                rival_id = j2 if es_j1 else j1

                try:
                    rival_member = await guild.fetch_member(int(rival_id))
                    rival_nombre = rival_member.display_name
                except:
                    rival_nombre = f"Usuario {rival_id}"

                deck_rival = None
                if resultado is not None and rival_id is not None:
                    codigo_deck_rival = f"{torneo_codigo}_{rival_id}"
                    deck = await obtener_deck_en_canal(guild, codigo_deck_rival)
                    if deck:
                        deck_rival = {
                            "nombre": deck.get("nombre_deck"),
                            "archetype": deck.get("archetype"),
                            "decklist": deck.get("decklist"),
                            "sideboard": deck.get("sideboard")
                        }

                enfrentamientos.append({
                    "ronda": ronda_num,
                    "oponente": rival_nombre,
                    "oponente_id": rival_id,
                    "resultado": resultado,
                    "tiene_deck_rival": deck_rival is not None,
                    "deck_rival": deck_rival
                })

        enfrentamientos.sort(key=lambda x: x["ronda"])

        response = web.json_response({"enfrentamientos": enfrentamientos})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    except Exception as e:
        print(f"❌ Error en api_mis_enfrentamientos: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def api_torneo_enfrentamientos(request):
    """
    Devuelve TODOS los enfrentamientos de un torneo, organizados por ronda.
    """
    session_token = request.query.get("session")
    torneo_codigo = request.query.get("torneo")

    if not torneo_codigo:
        return web.json_response({"error": "Falta el código del torneo"}, status=400)

    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    discord_id = sesion["discord_id"]
    miembro = guild.get_member(int(discord_id))
    if not miembro:
        return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)

    try:
        # Verificar que el usuario está inscrito en el torneo
        estado = await leer_estado(_bot_instance)
        torneo = next((t for t in estado.get("torneos", []) if t.get("codigo") == torneo_codigo), None)
        if not torneo:
            return web.json_response({"error": "Torneo no encontrado"}, status=404)
        if str(discord_id) not in torneo.get("inscritos_ids", []):
            return web.json_response({"error": "No estás inscrito en este torneo"}, status=403)

        # Leer rondas
        rondas_data = await leer_rondas(_bot_instance, torneo_codigo)
        if not rondas_data:
            return web.json_response({"rondas": []})

        rondas = rondas_data.get("rondas", [])
        resultado = []

        for ronda in rondas:
            ronda_num = ronda.get("numero")
            emparejamientos = ronda.get("emparejamientos", [])
            ronda_data = {
                "ronda": ronda_num,
                "completa": ronda.get("completa", False),
                "partidos": []
            }

            for emp in emparejamientos:
                j1 = emp.get("j1")
                j2 = emp.get("j2")
                resultado_emp = emp.get("resultado")

                # Obtener nombres
                try:
                    member1 = await guild.fetch_member(int(j1))
                    nombre1 = member1.display_name
                except:
                    nombre1 = f"Usuario {j1}"

                if j2 is None:
                    # BYE
                    partido = {
                        "jugador1": nombre1,
                        "jugador1_id": j1,
                        "jugador2": None,
                        "jugador2_id": None,
                        "resultado": "BYE"
                    }
                else:
                    try:
                        member2 = await guild.fetch_member(int(j2))
                        nombre2 = member2.display_name
                    except:
                        nombre2 = f"Usuario {j2}"
                    partido = {
                        "jugador1": nombre1,
                        "jugador1_id": j1,
                        "jugador2": nombre2,
                        "jugador2_id": j2,
                        "resultado": resultado_emp if resultado_emp else None
                    }

                ronda_data["partidos"].append(partido)

            resultado.append(ronda_data)

        response = web.json_response({"rondas": resultado})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    except Exception as e:
        print(f"❌ Error en api_torneo_enfrentamientos: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def api_deck_rival(request):
    session_token = request.query.get("session")
    torneo_codigo = request.query.get("torneo")
    rival_id = request.query.get("rival")

    if not torneo_codigo or not rival_id:
        return web.json_response({"error": "Faltan parámetros"}, status=400)

    sesion = sesiones_activas.get(session_token) if session_token else None
    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    discord_id = sesion["discord_id"]
    estado = await leer_estado(_bot_instance)
    torneo = next((t for t in estado.get("torneos", []) if t.get("codigo") == torneo_codigo), None)
    if not torneo or str(discord_id) not in torneo.get("inscritos_ids", []):
        return web.json_response({"error": "No tienes acceso a este torneo"}, status=403)

    codigo_deck = f"{torneo_codigo}_{rival_id}"
    deck = await obtener_deck_en_canal(guild, codigo_deck)

    if deck:
        response_data = {
            "nombre": deck.get("nombre_deck"),
            "archetype": deck.get("archetype"),
            "decklist": deck.get("decklist"),
            "sideboard": deck.get("sideboard")
        }
    else:
        response_data = None

    response = web.json_response({"deck": response_data})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def api_agendar_partida(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON inválido"}, status=400)

    session_token = body.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None

    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    codigo_torneo = str(body.get("codigo_torneo", "")).strip()
    jugador1_id = body.get("jugador1_id")
    jugador2_id = body.get("jugador2_id")
    fecha = str(body.get("fecha", "")).strip()
    hora = str(body.get("hora", "")).strip()

    if not codigo_torneo or not jugador1_id or not jugador2_id or not fecha or not hora:
        return web.json_response({"error": "Faltan datos"}, status=400)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    # 🔑 Validar permisos: el usuario debe ser uno de los jugadores
    discord_id = int(sesion["discord_id"])
    # Convertir a int por si vienen como string
    try:
        j1 = int(jugador1_id)
        j2 = int(jugador2_id)
    except ValueError:
        return web.json_response({"error": "IDs de jugador inválidos"}, status=400)

    if discord_id not in (j1, j2):
        return web.json_response({"error": "No tienes permiso para agendar esta partida"}, status=403)

    # Obtener miembros
    try:
        jugador1 = await guild.fetch_member(j1)
    except:
        return web.json_response({"error": "Jugador 1 no encontrado en el servidor"}, status=404)
    try:
        jugador2 = await guild.fetch_member(j2)
    except:
        return web.json_response({"error": "Jugador 2 no encontrado en el servidor"}, status=404)

    canal = discord.utils.get(guild.text_channels, name="partidos-agendados")
    if not canal:
        return web.json_response({"error": "Canal #partidos-agendados no encontrado"}, status=404)

    mensaje = f"📅 [EVENTO] {fecha} {hora} | {jugador1.mention} vs {jugador2.mention} | Agendado por {sesion['username']} (vía web)"
    await canal.send(mensaje)

    # Mensajes privados
    for j in (jugador1, jugador2):
        try:
            await j.send(f"✅ Se ha agendado una partida para el {fecha} a las {hora} entre {jugador1.mention} y {jugador2.mention}.")
        except:
            pass
    class FakeCtx:
        def __init__(self, guild, bot):
            self.guild = guild
            self.bot = bot

    fake_ctx = FakeCtx(guild, _bot_instance)
    await actualizar_proximas_partidas(fake_ctx)
    return web.json_response({"ok": True, "mensaje": "Partida agendada correctamente"})


async def api_clasificacion_torneo(request):
    """
    Devuelve la clasificación de un torneo, ya sea de Challonge (caché) o Swiss (estado).
    """
    torneo_codigo = request.query.get("codigo")
    if not torneo_codigo:
        return web.json_response({"error": "Falta el código del torneo"}, status=400)

    # Verificar sesión (opcional, pero para saber quién pide)
    session_token = request.query.get("session")
    sesion = sesiones_activas.get(session_token) if session_token else None
    if not sesion or time.time() > sesion["expira"]:
        return web.json_response({"error": "Sesión no válida"}, status=401)

    if _bot_instance is None:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    guild = _bot_instance.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return web.json_response({"error": "Servicio no disponible"}, status=503)

    # 1️⃣ Intentar obtener clasificación de Challonge (caché)
    cache = leer_cache()
    if cache:
        for torneo in cache.get("torneos", []):
            if torneo.get("codigo") == torneo_codigo:
                return web.json_response({"clasificacion": torneo.get("clasificacion", [])})

    # 2️⃣ Intentar obtener clasificación de Swiss (desde el estado)
    try:
       
        estado = await leer_estado(_bot_instance)
        torneo = next((t for t in estado.get("torneos", []) if t.get("codigo") == torneo_codigo), None)
        if torneo and torneo.get("tipo") == "swiss":
            # Calcular clasificación (esto puede ser pesado, pero es bajo demanda)
            clasificacion = await calcular_clasificacion(_bot_instance, torneo_codigo)
            # Formatear al mismo estilo que Challonge para el frontend
            clasificacion_formateada = []
            for item in clasificacion:
                # item tiene: id, rk, mp, w, l, dw, omw, bch, dif
                try:
                    member = await guild.fetch_member(int(item["id"]))
                    nombre = member.display_name
                    discord_id = item["id"]
                except:
                    nombre = f"Usuario {item['id']}"
                    discord_id = item["id"]
                clasificacion_formateada.append({
                    "nombre": nombre,
                    "discord_id": discord_id,
                    "rank": item["rk"],
                    "mp": item["mp"],
                    "wins": item["w"],
                    "losses": item["l"],
                    "draws": item["dw"],
                    "omw": item.get("omw", 0),
                    "buchholz": item.get("bch", 0),
                    "diff": item.get("dif", 0)
                })
            return web.json_response({"clasificacion": clasificacion_formateada})
    except Exception as e:
        print(f"❌ Error al obtener clasificación Swiss: {e}")
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response({"error": "Torneo no encontrado"}, status=404)

# ============================================================
# 9. SERVIDOR WEB — registro de rutas
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

    app.router.add_get('/api/todas-partidas', api_todas_partidas)
    app.router.add_post('/api/desinscribirse', api_desinscribirse)
    app.router.add_route('OPTIONS', '/api/desinscribirse', handle_options)

    app.router.add_get('/api/mis-torneos-pendientes', api_mis_torneos_pendientes)
    app.router.add_post('/api/reportar-resultado', api_reportar_resultado)
    app.router.add_route('OPTIONS', '/api/reportar-resultado', handle_options)

    app.router.add_get('/api/mis-enfrentamientos', api_mis_enfrentamientos)
    app.router.add_get('/api/torneo-enfrentamientos', api_torneo_enfrentamientos)
    app.router.add_get('/api/deck-rival', api_deck_rival)
    app.router.add_post('/api/agendar-partida', api_agendar_partida)
    app.router.add_route('OPTIONS', '/api/agendar-partida', handle_options)
    app.router.add_get('/api/clasificacion-torneo', api_clasificacion_torneo)

    return app

async def iniciar_servidor_web():
    app = crear_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()