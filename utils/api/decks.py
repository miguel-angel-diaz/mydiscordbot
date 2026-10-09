"""Decks en la web: los del usuario, arquetipos, subir y editar (mismas reglas que Discord) y el deck del rival."""
import discord
from aiohttp import web

from utils import decks
from utils import validacion_web as v
from utils import servicios
from utils.commons import obtener_deck_en_canal, obtener_decks_por_usuario, obtener_lista_arquetipos
from utils.torneos_estado import leer_rondas, obtener_torneo_estado
from utils.api import comun
from utils.api.auth import requiere_sesion


def partida_cerrada(torneo: dict, ronda: dict, emp: dict) -> bool:
    """
    Si ya se puede enseñar el deck del rival de esta partida: tiene resultado y su ronda está completa (o el torneo
    ha finalizado). Con solo "resultado reportado" bastaba que uno de los dos reportase (aunque fuera falso) para
    ver el deck del otro antes de jugar.
    """
    return emp.get("resultado") is not None and (ronda.get("completa") or torneo.get("estado") == "finalizado")


def deck_web(deck: dict) -> dict:
    """Datos del deck que se envían a la web (también los usa partidas.py para el deck del rival)."""
    return {
        "nombre": deck.get("nombre_deck"),
        "archetype": deck.get("archetype"),
        "decklist": deck.get("decklist"),
        "sideboard": deck.get("sideboard"),
    }


async def _deck_del_formulario(body: dict, codigo_torneo: str):
    """
    Campos del deck enviados desde la web, con las reglas de !subir-deck / !editar-deck (utils/decks.py); si no se
    cumplen, el middleware responde 400. Formato: el del front si es válido; si no, el del torneo. El arquetipo
    debe ser de ese formato. Devuelve (nombre, formato, arquetipo, decklist, sideboard).
    """
    nombre_deck = decks.nombre_deck(body.get("nombre_deck"))
    decklist = decks.decklist(body.get("decklist"))
    sideboard = decks.sideboard(body.get("sideboard"))
    torneo = await obtener_torneo_estado(comun.obtener_bot(), codigo_torneo)
    formato = decks.formato(body.get("formato")) or (torneo or {}).get("formato", "Premodern")
    archetype = decks.arquetipo_obligatorio(body.get("archetype"), formato)
    return nombre_deck, formato, archetype, decklist, sideboard


@requiere_sesion(servidor=True)
async def api_mis_decks(request, sesion):
    lista = await obtener_decks_por_usuario(sesion.guild, sesion.discord_id, include_message=False)
    return web.json_response({
        "username": "Usuario",            # el token no lleva el nombre; se mantiene el campo por compatibilidad
        "decks": lista,
    })


async def api_arquetipos(request):
    formato = v.formato(request.query.get("formato"))
    return web.json_response({"arquetipos": obtener_lista_arquetipos(formato)})


@requiere_sesion(jugador=True)
async def api_subir_deck(request, sesion):
    codigo_torneo = v.codigo_torneo(sesion.body.get("codigo_torneo"))
    datos = await _deck_del_formulario(sesion.body, codigo_torneo)

    resultado = await servicios.subir_deck(comun.obtener_bot(), sesion.guild, sesion.miembro, codigo_torneo, *datos,
                                           via_web=True)
    if resultado.ok:
        try:
            await sesion.miembro.send(f"✅ Tu deck **{datos[0]}** ha sido enviado con éxito al torneo "
                                      f"`{codigo_torneo}` (subido desde la web).")
        except discord.HTTPException:
            pass
    return comun.respuesta_servicio(resultado)


@requiere_sesion(jugador=True)
async def api_editar_deck(request, sesion):
    codigo_torneo = v.codigo_torneo(sesion.body.get("codigo_torneo"))
    datos = await _deck_del_formulario(sesion.body, codigo_torneo)
    return comun.respuesta_servicio(await servicios.editar_deck(
        comun.obtener_bot(), sesion.guild, sesion.miembro, codigo_torneo, *datos, via_web=True))


async def _ha_jugado_contra(torneo: dict, jugador_id: str, rival_id: str) -> bool:
    """True si ambos jugadores se han enfrentado en una partida ya cerrada (ver partida_cerrada)."""
    if jugador_id == rival_id:
        return False
    rondas_data = await leer_rondas(comun.obtener_bot(), torneo["codigo"]) or {}
    pareja = {jugador_id, rival_id}
    return any(
        {str(emp.get("j1")), str(emp.get("j2"))} == pareja and partida_cerrada(torneo, ronda, emp)
        for ronda in rondas_data.get("rondas", []) for emp in ronda.get("emparejamientos", [])
    )


@requiere_sesion(servidor=True)
async def api_deck_rival(request, sesion):
    torneo_codigo = v.codigo_torneo(request.query.get("torneo"))
    rival_id = v.discord_id(request.query.get("rival"), "Rival")

    torneo = await comun.torneo_del_estado(torneo_codigo)
    if not torneo or sesion.discord_id not in torneo.get("inscritos_ids", []):
        return web.json_response({"error": "No tienes acceso a este torneo"}, status=403)

    # Solo se ve el deck de un rival contra el que ya se ha jugado (resultado reportado).
    # Si no, se responde igual que "sin deck" para no revelar nada.
    deck = None
    if await _ha_jugado_contra(torneo, sesion.discord_id, str(rival_id)):
        deck = await obtener_deck_en_canal(sesion.guild, f"{torneo_codigo}_{rival_id}")
    return web.json_response({"deck": deck_web(deck) if deck else None})
