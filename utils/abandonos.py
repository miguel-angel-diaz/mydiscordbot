"""
Qué hacer con los torneos cuando un jugador abandona el servidor.

- Suizo abierto: se le desinscribe y se borra su deck.
- Suizo en desarrollo: queda "retirado" (sigue en la clasificación, no se le empareja más)
  y su partida pendiente se da como victoria 2-0 a su rival.
- Partidas agendadas con él: se borran de #partidos-agendados y se actualiza la cartelera.
- Torneos de otro tipo (Challonge / Battle Royale): no se tocan, se avisa para revisión manual.
"""
import asyncio
import traceback
from typing import List

import discord

from utils.torneos_estado import leer_estado
from utils.swiss_core import retirar_por_abandono  # reportar_resultado ya publica la clasificación
from utils.jugadores import actualizar_proximas_partidas

CANAL_RESULTADOS = "🍺-quién‐se‐lleva‐la‐ronda"
CANAL_CITAS = "🍸-citas‐a‐ciegas"
CANAL_AGENDA = "partidos-agendados"

SOLO_USUARIOS = discord.AllowedMentions(everyone=False, roles=False, users=True)


async def gestionar_abandono_torneos(bot, member: discord.Member) -> List[str]:
    """Aplica la retirada en todos los torneos del jugador. Devuelve un resumen (una línea por torneo)."""
    guild = member.guild
    uid = str(member.id)
    resumen: List[str] = []

    estado = await leer_estado(bot)
    for torneo in estado.get("torneos", []):
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
            print(f"❌ Error retirando a {uid} de {codigo}:\n{traceback.format_exc()}")
            resumen.append(f"❌ `{codigo}`: error al retirarlo, revisar a mano.")

    borradas = await _borrar_partidas_agendadas(bot, guild, uid)
    if borradas:
        resumen.append(f"🗓️ {borradas} partida(s) agendada(s) eliminada(s).")
    return resumen


async def _anunciar_retirada(bot, guild, codigo: str, uid: str, msg: str, rival):
    canal = discord.utils.get(guild.text_channels, name=CANAL_RESULTADOS)
    if canal:
        await canal.send(
            f"🚪 <@{uid}> ha abandonado el servidor y se retira del torneo `{codigo}`.\n{msg}",
            allowed_mentions=SOLO_USUARIOS,
        )

    # Quitar su línea del mensaje de emparejamientos de la ronda, si sigue publicado
    if rival:
        canal_citas = discord.utils.get(guild.text_channels, name=CANAL_CITAS)
        if canal_citas:
            async for m in canal_citas.history(limit=100):
                if m.author != bot.user or f"Torneo {codigo}" not in m.content or "Emparejamientos Ronda" not in m.content:
                    continue
                lineas = m.content.splitlines()
                restantes = [l for l in lineas[1:] if not (f"<@{uid}>" in l and f"<@{rival}>" in l)]
                if len(restantes) != len(lineas) - 1:
                    try:
                        if restantes:
                            await m.edit(content="\n".join([lineas[0], *restantes]))
                        else:
                            await m.delete()
                    except discord.HTTPException:
                        pass
                break


async def _borrar_partidas_agendadas(bot, guild, uid: str) -> int:
    canal = discord.utils.get(guild.text_channels, name=CANAL_AGENDA)
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
        class _Ctx:  # actualizar_proximas_partidas solo usa ctx.guild y ctx.bot
            pass
        ctx = _Ctx()
        ctx.guild, ctx.bot = guild, bot
        await actualizar_proximas_partidas(ctx)
    return borradas
