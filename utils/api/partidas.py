"""
Partidas en la web: agenda (#partidos-agendados), emparejamientos pendientes, reportar resultados y enfrentamientos.
"""
import logging
import re
from types import SimpleNamespace

import discord
from aiohttp import web

from utils import canales
from utils import validacion_web as v
from utils import servicios
from utils.commons import nombre_miembro, obtener_deck_en_canal, resolver_miembro
from utils.jugadores import actualizar_proximas_partidas, etiqueta_torneo, torneo_de_agenda
from utils.torneos_estado import leer_estado, leer_rondas
from utils.api import comun
from utils.api.auth import requiere_sesion
from utils.api.decks import deck_web, partida_cerrada

log = logging.getLogger(__name__)

# Formato de los mensajes de #partidos-agendados (lo escriben !agendar-partida y la web)
PATRON_AGENDA = re.compile(r"📅 \[EVENTO\] (\d{2}/\d{2}/\d{4}) (\d{2}:\d{2}) \| (.+?) vs (.+?) \| "
                           r"Agendado por (.+?)(?: \| Torneo `[^`]+`)?$")


def _menciona(texto: str, uid) -> bool:
    return f"<@{uid}>" in texto or f"<@!{uid}>" in texto


async def _refrescar_proximas(guild):
    """Rehace el resumen semanal de #próximas-partidas (actualizar_proximas_partidas solo usa guild y bot)."""
    await actualizar_proximas_partidas(SimpleNamespace(guild=guild, bot=comun.obtener_bot()))


async def _buscar_partida_agendada(canal, fecha: str, hora: str, jugador1_id: int, jugador2_id: int):
    """Mensaje de la agenda con esa fecha y hora entre esos dos jugadores (en cualquier orden), o None."""
    async for msg in canal.history(limit=500):
        match = PATRON_AGENDA.search(msg.content)
        if not match:
            continue
        fecha_msg, hora_msg, j1_str, j2_str, _ = match.groups()
        jugadores = f"{j1_str} | {j2_str}"
        if fecha_msg == fecha and hora_msg == hora and \
           _menciona(jugadores, jugador1_id) and _menciona(jugadores, jugador2_id):
            return msg
    return None


async def _partida_de_la_agenda(sesion, jugador1_id: int, jugador2_id: int, fecha: str, hora: str, accion: str):
    """
    Comprobaciones comunes de modificar y eliminar: permiso (admin o uno de los jugadores), jugadores en el servidor
    y mensaje en la agenda. Devuelve (jugador1, jugador2, mensaje); si algo falla lanza EntradaInvalida con su código.
    """
    es_admin = sesion.miembro.guild_permissions.administrator
    if not es_admin and int(sesion.discord_id) not in (jugador1_id, jugador2_id):
        raise v.EntradaInvalida(f"No tienes permiso para {accion} esta partida", status=403)

    jugador1 = await resolver_miembro(sesion.guild, jugador1_id)
    if not jugador1:
        raise v.EntradaInvalida("Jugador 1 no encontrado", status=404)
    jugador2 = await resolver_miembro(sesion.guild, jugador2_id)
    if not jugador2:
        raise v.EntradaInvalida("Jugador 2 no encontrado", status=404)

    canal = canales.get_canal(sesion.guild, canales.AGENDA)
    if not canal:
        raise v.EntradaInvalida("Canal #partidos-agendados no encontrado", status=404)

    mensaje = await _buscar_partida_agendada(canal, fecha, hora, jugador1_id, jugador2_id)
    if not mensaje:
        raise v.EntradaInvalida("No se encontró la partida agendada", status=404)
    return jugador1, jugador2, mensaje


# ============================================================
# AGENDA
# ============================================================
@requiere_sesion(servidor=True)
async def api_todas_partidas(request, sesion):
    guild = sesion.guild
    canal = canales.get_canal(guild, canales.AGENDA)
    if not canal:
        return web.json_response({"partidas": []})

    partidas = []
    async for mensaje in canal.history(limit=500):
        match = PATRON_AGENDA.search(mensaje.content)
        if not match:
            continue

        fecha, hora, jugador1_raw, jugador2_raw, agendado_por = match.groups()

        jugador1_match = re.search(r"<@!?(\d+)>", jugador1_raw)
        jugador2_match = re.search(r"<@!?(\d+)>", jugador2_raw)

        jugador1_id = int(jugador1_match.group(1)) if jugador1_match else None
        jugador2_id = int(jugador2_match.group(1)) if jugador2_match else None

        j1_nombre = await nombre_miembro(guild, jugador1_id, jugador1_raw.strip())
        j2_nombre = await nombre_miembro(guild, jugador2_id, jugador2_raw.strip())

        agendado_match = re.search(r"<@!?(\d+)>", agendado_por)
        if agendado_match:
            ag_nombre = await nombre_miembro(guild, agendado_match.group(1), agendado_por.strip())
        else:
            ag_nombre = agendado_por.strip()

        partidas.append({
            "fecha": fecha,
            "hora": hora,
            "jugador1": j1_nombre,
            "jugador1_id": str(jugador1_id) if jugador1_id else None,
            "jugador2": j2_nombre,
            "jugador2_id": str(jugador2_id) if jugador2_id else None,
            "agendado_por": ag_nombre
        })

    return web.json_response({"partidas": partidas})


async def _son_rivales(codigo_torneo: str, j1: str, j2: str) -> bool:
    """
    Ambos inscritos en el torneo y, si ya hay rondas, emparejados entre sí en alguna.
    (Antes de generar rondas basta con estar inscritos.)
    """
    torneo = await comun.torneo_del_estado(codigo_torneo)
    if not torneo:
        return False
    inscritos = set(map(str, torneo.get("inscritos_ids", [])))
    if j1 not in inscritos or j2 not in inscritos:
        return False

    rondas = (await leer_rondas(comun.obtener_bot(), codigo_torneo) or {}).get("rondas", [])
    if not rondas:
        return True
    pareja = {j1, j2}
    return any(
        {str(e.get("j1")), str(e.get("j2"))} == pareja
        for r in rondas for e in r.get("emparejamientos", [])
    )


@requiere_sesion(jugador=True)
async def api_agendar_partida(request, sesion):
    body = sesion.body
    discord_id = int(sesion.discord_id)
    codigo_torneo = v.codigo_torneo(body.get("codigo_torneo"))
    j1 = v.discord_id(body.get("jugador1_id"), "Jugador 1")
    j2 = v.discord_id(body.get("jugador2_id"), "Jugador 2")
    fecha = v.fecha(body.get("fecha"))
    hora = v.hora(body.get("hora"))
    if j1 == j2:
        return web.json_response({"error": "Los jugadores deben ser distintos"}, status=400)

    if discord_id not in (j1, j2):
        return web.json_response({"error": "No tienes permiso para agendar esta partida"}, status=403)

    if not await _son_rivales(codigo_torneo, str(j1), str(j2)):
        return web.json_response({"error": "Esos jugadores no se enfrentan en este torneo"}, status=403)

    jugador1 = await resolver_miembro(sesion.guild, j1)
    if not jugador1:
        return web.json_response({"error": "Jugador 1 no encontrado en el servidor"}, status=404)
    jugador2 = await resolver_miembro(sesion.guild, j2)
    if not jugador2:
        return web.json_response({"error": "Jugador 2 no encontrado en el servidor"}, status=404)

    canal = canales.get_canal(sesion.guild, canales.AGENDA)
    if not canal:
        return web.json_response({"error": "Canal #partidos-agendados no encontrado"}, status=404)

    autor = jugador1 if jugador1.id == discord_id else jugador2
    mensaje = (f"📅 [EVENTO] {fecha} {hora} | {jugador1.mention} vs {jugador2.mention} | "
               f"Agendado por {autor.mention} (vía web){etiqueta_torneo(codigo_torneo)}")
    # Solo se notifica a los dos jugadores; nunca @everyone, @here ni roles
    await canal.send(mensaje, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False,
                                                                     users=[jugador1, jugador2]))

    for j in (jugador1, jugador2):
        try:
            await j.send(f"✅ Se ha agendado una partida para el {fecha} a las {hora} entre {jugador1.mention} y {jugador2.mention}.")
        except discord.HTTPException:
            pass

    await _refrescar_proximas(sesion.guild)
    return web.json_response({"ok": True, "mensaje": "Partida agendada correctamente"})


@requiere_sesion(jugador=True)
async def api_modificar_partida(request, sesion):
    body = sesion.body
    jugador1_id = v.discord_id(body.get("jugador1_id"), "Jugador 1")
    jugador2_id = v.discord_id(body.get("jugador2_id"), "Jugador 2")
    # La partida actual puede ser de hoy o ya pasada: solo se valida el formato
    fecha_actual = v.fecha(body.get("fecha_actual"), "fecha actual", futura=False)
    hora_actual = v.hora(body.get("hora_actual"), "hora actual")
    nueva_fecha = v.fecha(body.get("nueva_fecha"), "nueva fecha") if body.get("nueva_fecha") else ""
    nueva_hora = v.hora(body.get("nueva_hora"), "nueva hora") if body.get("nueva_hora") else ""

    if not nueva_fecha and not nueva_hora:
        return web.json_response({"error": "Debes proporcionar al menos una fecha u hora nueva"}, status=400)

    jugador1, jugador2, mensaje = await _partida_de_la_agenda(
        sesion, jugador1_id, jugador2_id, fecha_actual, hora_actual, "modificar")

    nueva_fecha_str = nueva_fecha or fecha_actual
    nueva_hora_str = nueva_hora or hora_actual

    agendado_match = PATRON_AGENDA.search(mensaje.content)
    agendado_por = agendado_match.group(5) if agendado_match else "un usuario"

    await mensaje.edit(content=(
        f"📅 [EVENTO] {nueva_fecha_str} {nueva_hora_str} | {jugador1.mention} vs {jugador2.mention} | "
        f"Agendado por {agendado_por}{etiqueta_torneo(torneo_de_agenda(mensaje.content))}"
    ))
    await _refrescar_proximas(sesion.guild)

    for jugador in (jugador1, jugador2):
        try:
            await jugador.send(
                f"🔄 Partida modificada: {fecha_actual} {hora_actual} → {nueva_fecha_str} {nueva_hora_str}\n"
                f"🆚 {jugador1.display_name} vs {jugador2.display_name}"
            )
        except discord.HTTPException:
            pass

    return web.json_response({"ok": True, "mensaje": "Partida modificada correctamente"})


@requiere_sesion(jugador=True)
async def api_eliminar_partida(request, sesion):
    body = sesion.body
    jugador1_id = v.discord_id(body.get("jugador1_id"), "Jugador 1")
    jugador2_id = v.discord_id(body.get("jugador2_id"), "Jugador 2")
    fecha = v.fecha(body.get("fecha"), futura=False)
    hora = v.hora(body.get("hora"))

    jugador1, jugador2, mensaje = await _partida_de_la_agenda(
        sesion, jugador1_id, jugador2_id, fecha, hora, "eliminar")

    await mensaje.delete()

    for jugador in (jugador1, jugador2):
        try:
            await jugador.send(
                f"🗑️ La partida del {fecha} a las {hora} entre {jugador1.display_name} y {jugador2.display_name} ha sido eliminada."
            )
        except discord.HTTPException:
            pass

    await _refrescar_proximas(sesion.guild)
    return web.json_response({"ok": True, "mensaje": "Partida eliminada correctamente"})


# ============================================================
# EMPAREJAMIENTOS Y RESULTADOS
# ============================================================
async def mensajes_agenda(guild) -> list:
    """Textos de #partidos-agendados (se leen una vez por petición)."""
    canal = canales.get_canal(guild, canales.AGENDA)
    if not canal:
        return []
    return [msg.content async for msg in canal.history(limit=500)]


def esta_agendada(mensajes: list, codigo: str, j1, j2) -> bool:
    """Algún mensaje de la agenda de ese torneo (etiqueta al final) entre esos dos jugadores."""
    return any(torneo_de_agenda(msg) == codigo and _menciona(msg, j1) and _menciona(msg, j2) for msg in mensajes)


@requiere_sesion(miembro=True)
async def api_mis_torneos_pendientes(request, sesion):
    guild, discord_id = sesion.guild, sesion.discord_id
    bot = comun.obtener_bot()
    estado = await leer_estado(bot)

    mensajes_agendados = await mensajes_agenda(guild)     # una vez para todos los torneos

    resultado = []
    for t in estado.get("torneos", []):
        codigo = t.get("codigo")
        # Solo torneos no finalizados en los que el usuario está inscrito
        if not codigo or t.get("estado") == "finalizado" or discord_id not in t.get("inscritos_ids", []):
            continue

        rondas = ((await leer_rondas(bot, codigo)) or {}).get("rondas", [])
        # Última ronda incompleta
        ronda_actual = next((r for r in reversed(rondas) if not r.get("completa", False)), None)
        if not ronda_actual:
            continue

        pendientes = []
        for emp in ronda_actual.get("emparejamientos", []):
            if emp.get("resultado") is not None:
                continue

            j1, j2 = emp.get("j1"), emp.get("j2")
            nombre1 = await nombre_miembro(guild, j1, f"Usuario {j1}")

            if j2 is None:
                pendientes.append({"jugador1": nombre1, "jugador1_id": j1, "jugador2": "BYE", "jugador2_id": None,
                                   "resultado": None, "agendada": False})   # un BYE no se agenda
                continue

            pendientes.append({
                "jugador1": nombre1,
                "jugador1_id": j1,
                "jugador2": await nombre_miembro(guild, j2, f"Usuario {j2}"),
                "jugador2_id": j2,
                "resultado": None,
                "agendada": esta_agendada(mensajes_agendados, codigo, j1, j2),
            })

        # Solo torneos con partidas pendientes
        if pendientes:
            resultado.append({
                "codigo": codigo,
                "nombre": t.get("nombre", "Torneo sin nombre"),
                "ronda": ronda_actual.get("numero", 0),
                "pendientes": pendientes
            })

    return web.json_response({"torneos": resultado})


@requiere_sesion(jugador=True)
async def api_reportar_resultado(request, sesion):
    body = sesion.body
    codigo_torneo = v.codigo_torneo(body.get("codigo_torneo"))
    jugador1_id = v.discord_id(body.get("jugador1_id"), "Jugador 1")
    jugador2_id = v.discord_id(body.get("jugador2_id"), "Jugador 2")
    resultado = v.resultado(body.get("resultado"))
    if jugador1_id == jugador2_id:
        return web.json_response({"error": "Los jugadores deben ser distintos"}, status=400)

    return comun.respuesta_servicio(await servicios.reportar(
        comun.obtener_bot(), sesion.guild, sesion.miembro, codigo_torneo, jugador1_id, jugador2_id, resultado))


@requiere_sesion(miembro=True)
async def api_mis_enfrentamientos(request, sesion):
    torneo_codigo = v.codigo_torneo(request.query.get("torneo"))
    guild, discord_id = sesion.guild, sesion.discord_id

    torneo = await comun.torneo_del_estado(torneo_codigo)
    if not torneo:
        return web.json_response({"error": "Torneo no encontrado"}, status=404)
    if discord_id not in torneo.get("inscritos_ids", []):
        return web.json_response({"error": "No estás inscrito en este torneo"}, status=403)

    rondas_data = await leer_rondas(comun.obtener_bot(), torneo_codigo)
    enfrentamientos = []
    for ronda in (rondas_data or {}).get("rondas", []):
        for emp in ronda.get("emparejamientos", []):
            j1, j2, resultado = emp.get("j1"), emp.get("j2"), emp.get("resultado")
            if discord_id not in (j1, j2):
                continue

            rival_id = j2 if discord_id == j1 else j1
            deck_rival = None
            if rival_id is not None and partida_cerrada(torneo, ronda, emp):
                deck = await obtener_deck_en_canal(guild, f"{torneo_codigo}_{rival_id}")
                deck_rival = deck_web(deck) if deck else None

            enfrentamientos.append({
                "ronda": ronda.get("numero"),
                "oponente": await nombre_miembro(guild, rival_id, f"Usuario {rival_id}"),
                "oponente_id": rival_id,
                "resultado": resultado,
                "tiene_deck_rival": deck_rival is not None,
                "deck_rival": deck_rival
            })

    enfrentamientos.sort(key=lambda x: x["ronda"])
    return web.json_response({"enfrentamientos": enfrentamientos})
