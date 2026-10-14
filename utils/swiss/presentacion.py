######## swiss/presentacion.py #######
"""
Mensajes del suizo en Discord: emparejamientos en #🍸-citas‐a‐ciegas, clasificación en #🍺-el‐ranking‐de‐la‐barra
y avisos en la cartelera. No lee ni guarda estado: recibe los datos ya calculados (los pasa service.py).
"""
import logging
from typing import List

import discord

from utils import canales
from utils.commons import cabecera_emparejamientos, es_mensaje_emparejamientos, nombre_miembro, resolver_miembro

log = logging.getLogger(__name__)

LIMITE_HISTORIAL = 200      # mensajes que se revisan al buscar los anteriores del bot

# ============================================================
# EMPAREJAMIENTOS
# ============================================================

def texto_emparejamientos(codigo: str, ronda: dict) -> str:
    """Mensaje de emparejamientos de una ronda para #🍸-citas‐a‐ciegas (las menciones "<@id>" no piden nada a la API)."""
    lineas = [cabecera_emparejamientos(codigo, ronda["numero"])]
    for emp in ronda.get("emparejamientos", []):
        lineas.append(f"<@{emp['j1']}> → BYE ✅ (victoria automática)" if emp.get("j2") is None
                      else f"<@{emp['j1']}> vs <@{emp['j2']}>")
    return "\n".join(lineas) + "\n"


async def publicar_emparejamientos(guild, codigo: str, ronda: dict):
    """Publica en #🍸-citas‐a‐ciegas los emparejamientos de la ronda (antes, 4 copias de esto)."""
    canal = canales.get_canal(guild, canales.CITAS)
    if canal and ronda:
        await canal.send(texto_emparejamientos(codigo, ronda))


def texto_aviso_ronda(codigo: str, nombre: str, ronda_num: int, rival_id=None, rival_nombre: str = None) -> str:
    """DM a un jugador con su partida de la ronda; sin rival es que le ha tocado BYE."""
    cabecera = f"🍸 **Ronda {ronda_num} del torneo {nombre}**\n\n"
    if rival_id is None:
        return cabecera + ("Esta semana te toca **BYE**: descansas y ya tienes la **victoria reportada** "
                           "automáticamente (3 puntos). ¡Nada que agendar!")
    return (
        cabecera
        + f"⚔️ Tu partida de esta semana es contra **{rival_nombre}** (<@{rival_id}>).\n\n"
        f"📅 Poneos de acuerdo y **agendad la partida** con `!agendar-partida` en `#{canales.COMANDOS}`.\n"
        f"❓ ¿No sabes cómo? Escribe `!mis-comandos` en `#{canales.COMANDOS}` y elige **agendar-partida** "
        f"de la lista: te explica paso a paso cómo hacerlo."
    )


async def anunciar_byes(guild, nombre: str, ronda: dict):
    """
    Anuncia en #resultados los BYE de la ronda como un resultado más. El BYE ya nace con resultado ("BYE", 3 puntos
    en engine.nueva_ronda): nadie tiene que reportarlo, solo faltaba que se viera.
    """
    canal = canales.get_canal(guild, canales.RESULTADOS)
    if not canal:
        return
    for emp in ronda.get("emparejamientos", []):
        if emp.get("j2") is None:
            jugador = await nombre_miembro(guild, emp["j1"])
            await canal.send(f"🏆 Resultado reportado automáticamente en **{nombre}** (ronda {ronda['numero']}):\n"
                             f"**{jugador}** descansa con **BYE**\n"
                             f"🏅 Ganador: {jugador} (3 puntos)")


async def avisar_emparejamientos(guild, codigo: str, nombre: str, ronda: dict) -> int:
    """Manda a cada jugador de la ronda un DM con su rival. Devuelve cuántos se enviaron (DMs cerrados se saltan)."""
    enviados = 0
    for emp in ronda.get("emparejamientos", []):
        pareja = [(emp["j1"], emp.get("j2"))] + ([(emp["j2"], emp["j1"])] if emp.get("j2") is not None else [])
        for jugador_id, rival_id in pareja:
            miembro = await resolver_miembro(guild, jugador_id)
            if miembro is None:
                continue                                   # ya no está en el servidor
            rival_nombre = await nombre_miembro(guild, rival_id) if rival_id is not None else None
            try:
                await miembro.send(texto_aviso_ronda(codigo, nombre, ronda["numero"], rival_id, rival_nombre))
                enviados += 1
            except discord.HTTPException as e:              # incluye Forbidden (DMs cerrados)
                log.info(f"Sin DM de ronda {ronda['numero']} de {codigo} a {jugador_id}: {e}")
    return enviados


async def borrar_emparejamientos(bot, guild, codigo: str, ronda_num: int = None, todos: bool = False):
    """Borra el mensaje de emparejamientos del torneo (de esa ronda si se indica; todos=True, todos los que haya)."""
    canal = canales.get_canal(guild, canales.CITAS)
    if not canal:
        return
    async for msg in canal.history(limit=LIMITE_HISTORIAL):
        if msg.author == bot.user and es_mensaje_emparejamientos(msg.content, codigo, ronda_num):
            try:
                await msg.delete()
            except discord.HTTPException as e:
                log.warning(f"No pude borrar los emparejamientos de {codigo}: {e}")
            if not todos:
                break


async def quitar_partida_de_citas(bot, guild, codigo: str, ronda_num: int, jugador1_id, jugador2_id):
    """Quita la línea de una partida ya reportada del mensaje de citas de su ronda (lo borra si no queda ninguna)."""
    canal = canales.get_canal(guild, canales.CITAS)
    if not canal:
        return
    m1, m2 = f"<@{jugador1_id}>", f"<@{jugador2_id}>"
    async for msg in canal.history(limit=LIMITE_HISTORIAL):
        if msg.author == bot.user and es_mensaje_emparejamientos(msg.content, codigo, ronda_num):
            lineas = [l for l in msg.content.splitlines() if not (m1 in l and m2 in l)]
            if len(lineas) <= 1:
                await msg.delete()
            else:
                await msg.edit(content="\n".join(lineas))
            return

# ============================================================
# CLASIFICACIÓN
# ============================================================

def cabecera_clasificacion(codigo: str) -> str:
    return f"📊 **Clasificación del torneo `{codigo}`:**"


def _nombre(guild, pid) -> str:
    try:
        member = guild.get_member(int(pid))
    except (ValueError, TypeError):
        member = None
    return member.display_name if member else f"<@{pid}>"


def textos_clasificacion(guild, codigo: str, clasificacion: List[dict]) -> List[str]:
    """Tabla de la clasificación para el canal de ranking; si no cabe en un mensaje, en trozos de 10 jugadores."""
    cabecera = [
        cabecera_clasificacion(codigo),
        "```markdown",
        f"{'Rk':<3} | {'Participante':<22} | {'G-P-E':<5} | {'Pts':<3} | {'OMW%':<5} | {'Bch':<6} | {'Dif':<3}",
    ]
    filas = ["-" * 72]
    for p in clasificacion:
        gpe = f"{p.get('w', 0)}-{p.get('l', 0)}-{p.get('dw', 0)}"
        filas.append(f"{p['rk']:<3} | {_nombre(guild, p['id'])[:22]:<22} | {gpe:<5} | {p.get('mp', 0):<3} | "
                     f"{p.get('omw', 0.0):.3f}  | {p.get('bch', 0.0):.5f}  | {p.get('dif', 0):+}")

    completo = "\n".join(cabecera + filas + ["```"])
    if len(completo) <= 1900:
        return [completo]
    return ["\n".join(cabecera + filas[i:i + 10] + ["```"]) for i in range(0, len(filas), 10)]


def texto_clasificacion_dm(guild, clasificacion: List[dict], limite: int = 10) -> str:
    """Resumen corto (los primeros) para !clasificacion-swiss por DM."""
    lineas = ["📊 **Clasificación actual**", "Rk | Jugador | Pts | W-L-D | Dif"]
    for p in clasificacion[:limite]:
        lineas.append(f"{p['rk']:2} | {_nombre(guild, p['id']):12} | {p['mp']:3.0f} | {p['w']}-{p['l']}-{p['dw']} | {p['dif']:+}")
    return "\n".join(lineas)


async def borrar_clasificacion(bot, guild, codigo: str):
    """Borra TODOS los mensajes de clasificación del torneo (las largas van en varios trozos)."""
    canal = canales.get_canal(guild, canales.RANKING)
    if not canal:
        return
    cabecera = cabecera_clasificacion(codigo)
    async for msg in canal.history(limit=LIMITE_HISTORIAL):
        if msg.author == bot.user and not msg.embeds and msg.content.startswith(cabecera):
            try:
                await msg.delete()
            except discord.HTTPException:
                pass


async def publicar_clasificacion(bot, guild, codigo: str, clasificacion: List[dict]):
    """Sustituye en el canal de ranking la clasificación publicada del torneo por esta."""
    canal = canales.get_canal(guild, canales.RANKING)
    if not canal:
        return
    await borrar_clasificacion(bot, guild, codigo)
    for texto in textos_clasificacion(guild, codigo, clasificacion):
        await canal.send(texto)

# ============================================================
# AVISOS
# ============================================================

async def anunciar_fin_automatico(guild, codigo: str, motivo: str):
    canal = canales.get_canal(guild, canales.CARTELERA_TORNEOS)
    if canal:
        await canal.send(f"🏁 El torneo `{codigo}` ha finalizado automáticamente ({motivo}).")
