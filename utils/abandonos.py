"""
Qué hacer con los torneos cuando un jugador abandona el servidor.

- Suizo abierto: se le desinscribe y se borra su deck.
- Suizo en desarrollo: queda "retirado" (sigue en la clasificación, no se le empareja más)
  y su partida pendiente se da como victoria 2-0 a su rival.
- Partidas agendadas con él: se borran de #partidos-agendados y se actualiza la cartelera.
- Battle Royale en curso: sus enfrentamientos pendientes se anulan (los jugados se mantienen).
- Torneos de otro tipo (Challonge): no se tocan, se avisa para revisión manual.
"""
import asyncio
import logging
from types import SimpleNamespace
from typing import List

import discord

from utils import canales
from utils.torneos_estado import leer_estado
from utils.swiss.service import retirar_por_abandono  # reportar_resultado ya publica la clasificación
from utils.jugadores import actualizar_proximas_partidas
from utils import battle

log = logging.getLogger(__name__)

CANAL_RESULTADOS = canales.RESULTADOS
CANAL_AGENDA = canales.AGENDA

SOLO_USUARIOS = discord.AllowedMentions(everyone=False, roles=False, users=True)


async def gestionar_abandono_torneos(bot, member: discord.Member) -> List[str]:
    """Aplica la retirada en todos los torneos del jugador. Devuelve un resumen (una línea por torneo)."""
    guild = member.guild
    uid = str(member.id)
    resumen: List[str] = []

    estado = await leer_estado(bot)
    for torneo in estado.get("torneos", []):
        if torneo.get("tipo") == battle.TIPO:
            await _abandono_battle(bot, guild, torneo, uid, resumen)
            continue
        if uid not in torneo.get("inscritos_ids", []):
            continue
        codigo = torneo.get("codigo")
        if torneo.get("tipo") != "swiss":
            if torneo.get("estado", "abierto") != "finalizado":
                resumen.append(f"⚠️ `{codigo}` ({torneo.get('tipo', '?')}): revisar a mano en Challonge.")
            continue
        try:
            estado_antes = torneo.get("estado", "abierto")
            ok, msg, rival = await retirar_por_abandono(bot, codigo, member.id, guild)
            if not ok:
                continue
            resumen.append(f"`{codigo}`: {msg}")
            if estado_antes != "abierto":
                await _anunciar_retirada(bot, guild, codigo, uid, msg, rival)
        except Exception:
            log.exception(f"❌ Error retirando a {uid} de {codigo}")
            resumen.append(f"❌ `{codigo}`: error al retirarlo, revisar a mano.")

    borradas = await _borrar_partidas_agendadas(bot, guild, uid)
    if borradas:
        resumen.append(f"🗓️ {borradas} partida(s) agendada(s) eliminada(s).")
    return resumen


async def _abandono_battle(bot, guild, torneo: dict, uid: str, resumen: List[str]):
    """En un battle no hay inscritos: solo se anulan sus enfrentamientos pendientes."""
    codigo = torneo.get("codigo")
    if torneo.get("estado") != battle.EN_CURSO:
        return
    try:
        anulados = await battle.anular_pendientes_jugador(bot, codigo, uid)
        if anulados:
            resumen.append(f"`{codigo}` (battle): {anulados} enfrentamiento(s) pendiente(s) anulado(s).")
    except Exception:
        log.exception(f"❌ Error anulando enfrentamientos de {uid} en {codigo}")
        resumen.append(f"❌ `{codigo}` (battle): error al anular sus enfrentamientos, revisar a mano.")


async def _anunciar_retirada(bot, guild, codigo: str, uid: str, msg: str, rival):
    canal = canales.get_canal(guild, CANAL_RESULTADOS)
    if canal:
        await canal.send(
            f"🚪 <@{uid}> ha abandonado el servidor y se retira del torneo `{codigo}`.\n{msg}",
            allowed_mentions=SOLO_USUARIOS,
        )
    # Su línea del mensaje de citas la quita retirar_por_abandono, que conoce el número de su ronda


async def _borrar_partidas_agendadas(bot, guild, uid: str) -> int:
    canal = canales.get_canal(guild, CANAL_AGENDA)
    if not canal:
        return 0
    borradas = 0
    async for m in canal.history(limit=300):
        if "[EVENTO]" in m.content and (f"<@{uid}>" in m.content or f"<@!{uid}>" in m.content):
            try:
                await m.delete()
                borradas += 1
                await asyncio.sleep(0.3)
            except discord.HTTPException:
                pass
    if borradas:
        # actualizar_proximas_partidas solo usa ctx.guild y ctx.bot
        await actualizar_proximas_partidas(SimpleNamespace(guild=guild, bot=bot))
    return borradas
