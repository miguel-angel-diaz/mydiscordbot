######## challonge.py #######
"""
Cliente de Challonge de SOLO LECTURA.

Los torneos se gestionan con el sistema propio (suizo); Challonge solo se consulta para mostrar los
resultados de los torneos antiguos. Este módulo es el único sitio del bot que habla con Challonge y
solo hace peticiones GET: no hay forma de crear, iniciar, modificar ni borrar nada desde aquí.
"""
import asyncio
import re

import aiohttp

import config

API_BASE = "https://api.challonge.com/v1"
TIMEOUT = aiohttp.ClientTimeout(total=30)

# Código (url) de un torneo de Challonge: letras, números y guion bajo. Se valida antes de meterlo en la URL
# para que nunca se pueda construir otra ruta (p. ej. "../" o "x/participants/1") con un código manipulado.
_PATRON_CODIGO = re.compile(r"^[A-Za-z0-9_-]{1,60}$")


class ErrorChallonge(Exception):
    """Challonge no respondió bien (código HTTP distinto de 200, red caída o tiempo agotado)."""


def _auth():
    return aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)


def _ruta_torneo(codigo: str, recurso: str) -> str:
    codigo = str(codigo or "")
    if not _PATRON_CODIGO.match(codigo):
        raise ErrorChallonge(f"Código de torneo no válido: {codigo[:60]!r}")
    return f"/tournaments/{codigo}/{recurso}.json"


async def _get(session: aiohttp.ClientSession, ruta: str, params: dict = None):
    try:
        async with session.get(f"{API_BASE}{ruta}", params=params, auth=_auth()) as resp:
            if resp.status != 200:
                raise ErrorChallonge(f"Challonge respondió {resp.status} en {ruta}")
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise ErrorChallonge(f"No se pudo contactar con Challonge ({ruta}): {e!r}") from e


async def torneos_finalizados() -> list:
    """Torneos terminados de la cuenta, ya simplificados para la caché de la web."""
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        datos = await _get(session, "/tournaments.json", {"state": "ended"})
    torneos = []
    for t in datos:
        torneo = t["tournament"]
        torneos.append({
            "codigo": torneo["url"],
            "nombre": torneo["name"],
            "fecha_inicio": torneo.get("started_at"),
            "fecha_fin": torneo.get("completed_at"),
            "participantes_count": torneo.get("participants_count"),
        })
    return torneos


async def participantes_y_partidos(codigo: str):
    """(participantes, partidos) de un torneo, en el formato original de Challonge, con una sola sesión."""
    ruta_participantes = _ruta_torneo(codigo, "participants")
    ruta_partidos = _ruta_torneo(codigo, "matches")
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        participantes = await _get(session, ruta_participantes)
        partidos = await _get(session, ruta_partidos)
    return participantes, partidos


def partidos_simplificados(partidos_raw: list) -> list:
    """Partidos de Challonge en el formato reducido que guarda la caché de la web."""
    partidos = []
    for m in partidos_raw:
        match = m.get("match", {})
        partidos.append({
            "id": match.get("id"),
            "round": match.get("round"),
            "player1_id": match.get("player1_id"),
            "player2_id": match.get("player2_id"),
            "state": match.get("state"),
            "scores_csv": match.get("scores_csv"),
            "winner_id": match.get("winner_id"),
            "loser_id": match.get("loser_id"),
        })
    return partidos


def participantes_simplificados(participantes_raw: list) -> list:
    """Participantes en formato compacto para la caché: [{"id", "name"}] (en Challonge, name = ID de Discord)."""
    compactos = []
    for p in participantes_raw:
        datos = p.get("participant", p)
        compactos.append({"id": datos.get("id"), "name": datos.get("name")})
    return compactos
