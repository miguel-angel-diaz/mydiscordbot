"""
Torneos en la web: caché de los antiguos de Challonge, listado público, estado e inscripción, rondas y clasificación.
"""
import logging
from datetime import datetime, timezone

from aiohttp import web

import config
from utils import challonge
from utils import cache_web
from utils import servicios
from utils import validacion_web as v
from utils.commons import (
    clasificacion_desde_challonge,
    nombre_miembro,
    obtener_decks_por_usuario,
    resolver_miembro,
    tiene_rol_permitido,
)
from utils.swiss.service import calcular_clasificacion as calcular_clasificacion_swiss
from utils.torneos_estado import leer_estado, leer_rondas, leer_clasificacion
from utils.api import comun
from utils.api.auth import requiere_sesion

log = logging.getLogger(__name__)


# ============================================================
# CACHÉ — evita golpear Challonge/Discord en cada visita web
# ============================================================
async def regenerar_cache(guild):
    """
    Rehace la caché de torneos antiguos de Challonge. Si un torneo falla se conserva su entrada anterior,
    y si Challonge no responde se deja la caché como estaba (nunca se sustituye por una vacía).
    """
    anterior = {t.get("codigo"): t for t in (cache_web.leer() or {}).get("torneos", [])}
    try:
        torneos = await challonge.torneos_finalizados()
    except challonge.ErrorChallonge as e:
        log.warning(f"⚠️ Challonge no responde; se mantiene la caché anterior: {e}")
        return cache_web.leer() or {"actualizado": None, "torneos": []}

    resultado, fallidos = [], []
    for torneo in torneos:
        try:
            # Una sola descarga por torneo: de ella salen la clasificación y los enfrentamientos
            participantes_raw, matches_raw = await challonge.participantes_y_partidos(torneo["codigo"])
            resultado.append({
                **torneo,
                "clasificacion": clasificacion_desde_challonge(guild, torneo["codigo"], participantes_raw, matches_raw),
                "participants": challonge.participantes_simplificados(participantes_raw),
                "matches": challonge.partidos_simplificados(matches_raw),
            })
        except Exception as e:
            log.warning(f"⚠️ No se pudo procesar el torneo {torneo['codigo']} (se conserva el anterior): {e}")
            fallidos.append(torneo["codigo"])
            if torneo["codigo"] in anterior:
                resultado.append(anterior[torneo["codigo"]])

    # Si no se ha refrescado ninguno, no se escribe: la fecha diría que está al día y no se reintentaría
    if torneos and len(fallidos) == len(torneos):
        log.error("❌ No se pudo procesar ningún torneo: se mantiene la caché anterior.")
        return cache_web.leer() or {"actualizado": None, "torneos": []}

    payload = {"actualizado": datetime.now(timezone.utc).isoformat(), "torneos": resultado}
    await cache_web.guardar(payload)
    aviso = f" ({len(fallidos)} con error, se conserva su versión anterior)" if fallidos else ""
    log.info(f"✅ Caché regenerado con {len(resultado)} torneo(s){aviso}.")
    return payload


async def refrescar_cache_al_arrancar(bot):
    """
    Tras un deploy (disco nuevo en Railway) la caché falta o es la copia del repositorio: si no existe o tiene
    más de 24 h se regenera en segundo plano, sin retrasar el arranque. Mientras, se sirve la que haya.
    """
    await bot.wait_until_ready()
    if not cache_web.necesita_regenerar():
        return
    guild = bot.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        log.warning("⚠️ No se encontró el servidor: no se regenera la caché de la web al arrancar.")
        return
    log.info("🔄 Caché de la web ausente o antigua: regenerando en segundo plano...")
    try:
        await regenerar_cache(guild)
    except Exception:
        log.exception("❌ Error regenerando la caché al arrancar")


def _torneo_en_cache(codigo: str) -> dict | None:
    return next((t for t in (cache_web.leer() or {}).get("torneos", []) if t.get("codigo") == codigo), None)


# ============================================================
# CLASIFICACIÓN Y LISTADO PÚBLICO
# ============================================================
def _fecha_iso(fecha):
    """'01/09/2026' -> '2026-09-01' (como las fechas de Challonge), para ordenar y para que JS no la lea como mes/día."""
    try:
        return datetime.strptime(str(fecha).strip(), "%d/%m/%Y").date().isoformat()
    except (ValueError, TypeError):
        return fecha


async def _clasificacion_swiss_web(guild, clasificacion: list, consultar_api: bool = False) -> list:
    """
    Clasificación suiza con el formato de la de Challonge que espera la web. Los nombres salen de la caché de
    miembros; con `consultar_api` se pide a Discord el que no esté (no en el endpoint público).
    """
    resultado = []
    for p in clasificacion:
        member = await resolver_miembro(guild, p["id"]) if consultar_api else guild.get_member(int(p["id"]))
        resultado.append({
            "rank": p["rk"],
            "nombre": member.display_name if member else f"Usuario {p['id']}",
            "wins": p["w"],
            "losses": p["l"],
            "draws": p["dw"],
            "mp": p["mp"],
            "omw": p.get("omw", 0),
            "buchholz": p.get("bch", 0),
            "diff": p.get("dif", 0),
            "discord_id": p["id"],
            "avatar": str(member.display_avatar.url) if member else None,
        })
    return resultado


async def api_torneos(request):
    torneos_challonge = (cache_web.leer() or {}).get("torneos", [])

    guild = comun.servidor()
    if not guild:
        return comun.no_disponible()

    bot = comun.obtener_bot()
    estado = await leer_estado(bot)
    torneos_swiss_finalizados = []

    for t in estado.get("torneos", []):
        if t.get("estado") == "finalizado" and t.get("tipo") == "swiss":
            try:
                # Endpoint público: se usa la clasificación ya guardada (no cambia salvo correcciones,
                # que la recalculan y guardan). Solo se calcula si aún no existe.
                guardada = await leer_clasificacion(bot, t["codigo"])
                clasificacion = (guardada or {}).get("clasificacion") or \
                    await calcular_clasificacion_swiss(bot, t["codigo"])
                torneos_swiss_finalizados.append({
                    "codigo": t["codigo"],
                    "nombre": t.get("nombre", t["codigo"]),
                    "fecha_fin": _fecha_iso(t.get("fecha_fin") or t.get("fecha_inicio")),
                    "participantes_count": len(t.get("inscritos_ids", [])),
                    "clasificacion": await _clasificacion_swiss_web(guild, clasificacion),
                })
            except Exception:
                log.exception(f"Error al procesar Swiss {t['codigo']}")

    # La web solo usa los datos del torneo y su clasificación: los partidos y participantes no se envían
    torneos_challonge = [{k: v for k, v in t.items() if k not in ("matches", "participants")} for t in torneos_challonge]
    todos_los_torneos = torneos_challonge + torneos_swiss_finalizados
    todos_los_torneos.sort(key=lambda x: x.get("fecha_fin") or "", reverse=True)

    return web.json_response({"torneos": todos_los_torneos})


@requiere_sesion(servidor=True)
async def api_clasificacion_torneo(request, sesion):
    torneo_codigo = v.codigo_torneo(request.query.get("codigo"))

    # 1) Torneos antiguos de Challonge (caché)
    torneo_cache = _torneo_en_cache(torneo_codigo)
    if torneo_cache:
        return web.json_response({"clasificacion": torneo_cache.get("clasificacion", [])})

    # 2) Torneos suizos (estado interno)
    torneo = await comun.torneo_del_estado(torneo_codigo)
    if torneo and torneo.get("tipo") == "swiss":
        clasificacion = await calcular_clasificacion_swiss(comun.obtener_bot(), torneo_codigo)
        return web.json_response(
            {"clasificacion": await _clasificacion_swiss_web(sesion.guild, clasificacion or [], consultar_api=True)})

    return web.json_response({"error": "Torneo no encontrado"}, status=404)


# ============================================================
# TORNEOS DEL USUARIO E INSCRIPCIÓN
# ============================================================
@requiere_sesion
async def api_mis_torneos(request, sesion):
    data = cache_web.leer()
    if data is None:
        return web.json_response({"error": "Datos no disponibles todavía"}, status=503)

    mis_resultados = []
    for torneo in data.get("torneos", []):
        for jugador in torneo.get("clasificacion", []):
            if jugador.get("discord_id") == sesion.discord_id:
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
        "username": "Usuario",            # el token no lleva el nombre; se mantiene el campo por compatibilidad
        "torneos": mis_resultados,
    })


@requiere_sesion(miembro=True)
async def api_torneos_disponibles(request, sesion):
    estado = await leer_estado(comun.obtener_bot())
    torneos_usuario = [
        {
            "codigo": t.get("codigo"),
            "nombre": t.get("nombre", "Torneo sin nombre"),
            "estado": "activo",
            "nivel": t.get("nivel", "todos"),
        }
        for t in estado.get("torneos", []) if sesion.discord_id in t.get("inscritos_ids", [])
    ]
    return web.json_response({"torneos": torneos_usuario})


@requiere_sesion(miembro=True)
async def api_estado_torneos(request, sesion):
    miembro = sesion.miembro
    estado = await leer_estado(comun.obtener_bot())

    decks_usuario = await obtener_decks_por_usuario(sesion.guild, sesion.discord_id, include_message=False)
    decks_por_torneo = {d["codigo_torneo"]: d for d in decks_usuario if d.get("codigo_torneo")}

    torneos_respuesta = []
    for t in estado.get("torneos", []):
        codigo = t.get("codigo")
        if not codigo:
            continue

        if t.get("estado") not in ("abierto", "en desarrollo"):
            continue
        if t.get("tipo") != "swiss":            # p. ej. Battle Royale: sin inscripción ni decks por la web
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

        inscrito = sesion.discord_id in inscritos_ids

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
            # 🔒 REGLA ÚNICA: solo puede editar si tiene deck y NO ha editado aún
            "puede_editar": (deck_edited < 1) if deck_subido else False,
            "puede_inscribirse": not inscrito and t.get("estado") == "abierto",
            "puede_desinscribirse": inscrito and t.get("estado") == "abierto"
        })

    return web.json_response({"torneos": torneos_respuesta})


@requiere_sesion(miembro=True)
async def api_inscribirse(request, sesion):
    codigo_torneo = v.codigo_torneo(sesion.body.get("codigo_torneo"))
    return comun.respuesta_servicio(await servicios.inscribir(
        comun.obtener_bot(), sesion.guild, sesion.miembro, codigo_torneo, via_web=True))


@requiere_sesion(miembro=True)
async def api_desinscribirse(request, sesion):
    codigo_torneo = v.codigo_torneo(sesion.body.get("codigo_torneo"))
    return comun.respuesta_servicio(await servicios.desinscribir(
        comun.obtener_bot(), sesion.guild, sesion.miembro, codigo_torneo, via_web=True))


# ============================================================
# RONDAS DE UN TORNEO (suizo o antiguo de Challonge)
# ============================================================
async def _rondas_challonge_web(guild, participantes: list, partidos: list) -> list:
    """
    Rondas para la web a partir de participantes y partidos de Challonge. Admite el formato original
    ({"participant": {...}} / {"match": {...}}) y el compacto de la caché ({"id", "name"} / {...}).
    """
    id_to_discord = {}
    for p in participantes:
        datos = p.get("participant", p)
        if datos.get("id") and datos.get("name"):
            id_to_discord[datos["id"]] = datos["name"]

    nombres = {}

    async def nombre(discord_id, pid):
        if not discord_id:
            return f"Participante {pid}" if pid else "TBD"
        if discord_id not in nombres:
            nombres[discord_id] = await nombre_miembro(guild, discord_id)
        return nombres[discord_id]

    rondas_dict = {}
    for match in partidos:
        m = match.get("match", match)
        ronda = m.get("round")
        if ronda is None:
            continue
        rondas_dict.setdefault(ronda, {"partidos": [], "completa": True})
        p1_id, p2_id = m.get("player1_id"), m.get("player2_id")
        discord1 = id_to_discord.get(p1_id) if p1_id else None
        discord2 = id_to_discord.get(p2_id) if p2_id else None
        nombre1 = await nombre(discord1, p1_id)
        if p2_id is None:
            partido = {"jugador1": nombre1, "jugador1_id": discord1, "jugador2": None, "jugador2_id": None,
                       "resultado": "BYE"}
        else:
            resultado_emp = (m.get("scores_csv") or None) if m.get("state") == "complete" else None
            partido = {"jugador1": nombre1, "jugador1_id": discord1, "jugador2": await nombre(discord2, p2_id),
                       "jugador2_id": discord2, "resultado": resultado_emp}
        rondas_dict[ronda]["partidos"].append(partido)
        if m.get("state") != "complete":
            rondas_dict[ronda]["completa"] = False

    return [{"ronda": r, "completa": rondas_dict[r]["completa"], "partidos": rondas_dict[r]["partidos"]}
            for r in sorted(rondas_dict)]


async def _rondas_swiss_web(guild, torneo_codigo: str) -> list:
    """Rondas de un torneo suizo para la web (nombres desde la caché de miembros)."""
    rondas_data = await leer_rondas(comun.obtener_bot(), torneo_codigo)
    resultado = []
    for ronda in (rondas_data or {}).get("rondas", []):
        partidos = []
        for emp in ronda.get("emparejamientos", []):
            j1, j2 = emp.get("j1"), emp.get("j2")
            partido = {"jugador1": await nombre_miembro(guild, j1, f"Usuario {j1}"), "jugador1_id": j1}
            if j2 is None:
                partido.update({"jugador2": None, "jugador2_id": None, "resultado": "BYE"})
            else:
                partido.update({"jugador2": await nombre_miembro(guild, j2, f"Usuario {j2}"), "jugador2_id": j2,
                                "resultado": emp.get("resultado") or None})
            partidos.append(partido)
        resultado.append({"ronda": ronda.get("numero"), "completa": ronda.get("completa", False), "partidos": partidos})
    return resultado


async def _rondas_challonge_para_web(guild, torneo_codigo: str, torneo: dict):
    """
    Rondas de un torneo antiguo de Challonge: de la caché si tiene partidos y participantes; si no, se piden a
    Challonge (solo para torneos nuestros) y se guardan. Devuelve la respuesta web.
    """
    torneo_cache = _torneo_en_cache(torneo_codigo)
    if torneo_cache and torneo_cache.get("matches") and torneo_cache.get("participants"):
        rondas = await _rondas_challonge_web(guild, torneo_cache["participants"], torneo_cache["matches"])
        return web.json_response({"rondas": rondas})

    # Un torneo propio que no es suizo (Battle Royale) no tiene rondas que mostrar ni está en Challonge
    if torneo is not None and torneo.get("tipo") not in (None, "challonge"):
        return web.json_response({"rondas": []})
    # Solo se consulta Challonge para torneos nuestros (en el estado del bot o ya en caché);
    # cualquier otro código devuelve vacío y no se escribe nada en la caché
    if torneo is None and torneo_cache is None:
        return web.json_response({"rondas": []})

    try:
        participants_data, matches_data = await challonge.participantes_y_partidos(torneo_codigo)
    except challonge.ErrorChallonge as e:
        log.warning(f"⚠️ torneo-enfrentamientos {torneo_codigo}: {e}")
        return web.json_response({"error": "No se pudieron obtener los enfrentamientos"}, status=503)
    participantes = challonge.participantes_simplificados(participants_data)
    partidos = challonge.partidos_simplificados(matches_data)
    await cache_web.actualizar_torneo(
        torneo_codigo, {"participants": participantes, "matches": partidos},
        nuevo=lambda: {"codigo": torneo_codigo, "nombre": (torneo or {}).get("nombre", torneo_codigo)})
    return web.json_response({"rondas": await _rondas_challonge_web(guild, participantes, partidos)})


@requiere_sesion(miembro=True)
async def api_torneo_enfrentamientos(request, sesion):
    torneo_codigo = v.codigo_torneo(request.query.get("torneo"))
    torneo = await comun.torneo_del_estado(torneo_codigo)
    if torneo and torneo.get("tipo") == "swiss":
        return web.json_response({"rondas": await _rondas_swiss_web(sesion.guild, torneo_codigo)})
    return await _rondas_challonge_para_web(sesion.guild, torneo_codigo, torneo)
