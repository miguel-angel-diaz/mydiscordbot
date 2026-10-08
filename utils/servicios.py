"""
Operaciones que hacen igual los comandos de Discord y la API web: inscribir, desinscribir, reportar un resultado y
subir o editar un deck. Validan, guardan y publican en los canales (#cartelera, #citas, #resultados, decks); quien
las llama solo decide cómo preguntar y cómo enseñar el resultado (DM o JSON).

Devuelven un Resultado. El mensaje va sin icono delante: Discord le pone ✅/❌ y la web lo envía tal cual.
"""
import logging
from dataclasses import dataclass

import discord

from utils import canales
from utils import decks
from utils.commons import (
    EDICION_ABIERTO,
    EDICION_FINALIZADO,
    EDICION_NO_EXISTE,
    EDICION_NO_INSCRITO,
    comprobar_edicion_deck,
    lock_edicion_deck,
    nombre_miembro,
    obtener_deck_en_canal,
)
from utils.swiss import presentacion
from utils.swiss.service import (
    desinscribir_jugador,
    inscribir_jugador,
    obtener_rondas,
    obtener_torneo,
    reportar_resultado,
)

log = logging.getLogger(__name__)

# Motivos de fallo con un significado propio (la web los traduce a su código HTTP; el resto es un 400)
SIN_PERMISO = "sin_permiso"
YA_EXISTE = "ya_existe"
SIN_CANAL = "sin_canal"


@dataclass
class Resultado:
    ok: bool
    mensaje: str
    motivo: str = ""
    embed: discord.Embed | None = None


def _sin_icono(texto: str) -> str:
    for icono in ("❌ ", "✅ ", "⚠️ "):
        if texto.startswith(icono):
            return texto[len(icono):]
    return texto


# ============================================================
# INSCRIPCIONES
# ============================================================
async def _anunciar_inscripcion(bot, guild, codigo: str, texto: str):
    """Aviso en #cartelera-torneos con el recuento de inscritos y plazas."""
    canal = canales.get_canal(guild, canales.CARTELERA_TORNEOS)
    torneo = await obtener_torneo(bot, codigo)
    if not canal or not torneo:
        return
    total = len(torneo.get("inscritos_ids", []))
    maximo = torneo.get("total_maximo")
    plazas = maximo - total if maximo else "∞"
    await canal.send(f"{texto}\n👥 Inscritos: {total}/{maximo or '∞'} | 🪑 Plazas libres: {plazas}")


async def inscribir(bot, guild, usuario: discord.Member, codigo: str, *, forzar: bool = False,
                    via_web: bool = False) -> Resultado:
    """Inscribe en un torneo suizo abierto. `forzar` (un admin inscribiendo a otra persona) se salta el nivel."""
    torneo = await obtener_torneo(bot, codigo)
    if torneo and torneo.get("tipo") != "swiss":
        return Resultado(False, "Las inscripciones de este torneo no se gestionan así.")
    ok, mensaje = await inscribir_jugador(bot, codigo, usuario.id, miembro=usuario, forzar=forzar)
    if ok:
        origen = " (vía web)" if via_web else ""
        await _anunciar_inscripcion(bot, guild, codigo, f"📥 {usuario.mention} se ha inscrito en `{codigo}`{origen}.")
    return Resultado(ok, mensaje)


async def desinscribir(bot, guild, usuario: discord.Member, codigo: str, *, via_web: bool = False) -> Resultado:
    """Saca al usuario de un torneo con la inscripción abierta (y borra su deck)."""
    ok, mensaje = await desinscribir_jugador(bot, codigo, usuario.id, guild)
    if ok:
        origen = " (vía web)" if via_web else ""
        await _anunciar_inscripcion(bot, guild, codigo, f"📤 {usuario.mention} se ha desinscrito de `{codigo}`{origen}.")
    return Resultado(ok, mensaje)


# ============================================================
# RESULTADOS
# ============================================================
def puede_reportar(autor: discord.Member, jugador1_id: int, jugador2_id: int) -> bool:
    return autor.guild_permissions.administrator or autor.id in (int(jugador1_id), int(jugador2_id))


async def _anunciar_resultado(guild, codigo: str, jugador1_id: int, jugador2_id: int, resultado: str):
    canal = canales.get_canal(guild, canales.RESULTADOS)
    if not canal:
        return
    nombre1 = await nombre_miembro(guild, jugador1_id, f"Usuario {jugador1_id}")
    nombre2 = await nombre_miembro(guild, jugador2_id, f"Usuario {jugador2_id}")
    try:
        g1, g2 = map(int, resultado.split("-"))
    except ValueError:
        g1 = g2 = 0
    ganador = nombre1 if g1 > g2 else nombre2 if g2 > g1 else "Empate"
    await canal.send(
        f"🏆 Resultado reportado en `{codigo}`:\n"
        f"**{nombre1}** {resultado} **{nombre2}**\n"
        f"🏅 Ganador: {ganador}"
    )


async def reportar(bot, guild, autor: discord.Member, codigo: str, jugador1_id: int, jugador2_id: int,
                   resultado: str) -> Resultado:
    """
    Registra el resultado de una partida de la ronda actual (solo uno de los jugadores o un admin), la quita del
    mensaje de citas de su ronda y la anuncia en #resultados. La clasificación la publica reportar_resultado.
    """
    if not puede_reportar(autor, jugador1_id, jugador2_id):
        return Resultado(False, "Solo los jugadores o un administrador pueden reportar este resultado.", SIN_PERMISO)

    # Número de la ronda ANTES de reportar: si con este resultado se completa, la actual pasa a ser la siguiente
    rondas = await obtener_rondas(bot, codigo)
    ronda_num = rondas[-1].get("numero", 0) if rondas else 0

    ok, mensaje, _, _ = await reportar_resultado(bot, codigo, int(jugador1_id), resultado, int(jugador2_id), guild)
    if not ok:
        return Resultado(False, mensaje)

    try:
        await presentacion.quitar_partida_de_citas(bot, guild, codigo, ronda_num, jugador1_id, jugador2_id)
        await _anunciar_resultado(guild, codigo, jugador1_id, jugador2_id, resultado.strip())
    except discord.HTTPException as e:
        log.warning(f"⚠️ Resultado de {codigo} guardado, pero no se pudieron actualizar los canales: {e}")
    return Resultado(True, mensaje)


# ============================================================
# DECKS
# ============================================================
async def subir_deck(bot, guild, miembro: discord.Member, codigo: str, nombre_deck: str, formato: str,
                     archetype: str, decklist: str, sideboard: str, *, via_web: bool = False) -> Resultado:
    """
    Publica el deck de un inscrito si el torneo aún no ha empezado. decks.publicar comprueba con lock que no
    exista ya (web y Discord a la vez -> solo uno). El embed publicado va en el Resultado.
    """
    motivo, mensaje = await comprobar_edicion_deck(codigo, miembro, bot)
    if motivo != EDICION_ABIERTO:
        return Resultado(False, _sin_icono(mensaje))

    embed = decks.construir_embed(codigo, miembro, nombre_deck, formato, archetype, decklist, sideboard,
                                  via_web=via_web)
    ok, motivo = await decks.publicar(guild, embed, decks.codigo_deck(codigo, miembro.id))
    if motivo == "ya_existe":
        return Resultado(False, f"Ya tienes un deck subido para este torneo. Usa `!editar-deck {codigo}` "
                                "si deseas modificarlo.", YA_EXISTE)
    if not ok:
        return Resultado(False, "No se encontró el canal de decks.", SIN_CANAL)
    return Resultado(True, _sin_icono(mensaje), embed=embed)


async def editar_deck(bot, guild, miembro: discord.Member, codigo: str, nombre_deck: str, formato: str,
                      archetype: str, decklist: str, sideboard: str, *, via_web: bool = False) -> Resultado:
    """
    Usa la única edición del deck: se permite también con el torneo empezado, pero nunca sin estar inscrito ni en
    un torneo inexistente o finalizado. Todo dentro del lock del deck, que comparten la web y !editar-deck.
    """
    codigo_deck = decks.codigo_deck(codigo, miembro.id)
    async with lock_edicion_deck(codigo_deck):
        motivo, mensaje = await comprobar_edicion_deck(codigo, miembro, bot)
        if motivo in (EDICION_NO_EXISTE, EDICION_NO_INSCRITO, EDICION_FINALIZADO):
            return Resultado(False, _sin_icono(mensaje))

        deck_actual = await obtener_deck_en_canal(guild, codigo_deck)
        if not deck_actual:
            return Resultado(False, "No tienes ningún deck subido para este torneo (o lo ha retirado un admin).")
        ediciones = deck_actual.get("edited", 0)
        if ediciones >= 1:
            return Resultado(False, "Ya has usado tu única edición disponible (1/1). No puedes editar más.")

        embed = decks.construir_embed(codigo, miembro, nombre_deck, formato, archetype, decklist, sideboard,
                                      ediciones=ediciones + 1, actualizado=True, via_web=via_web)
        try:
            await deck_actual["mensaje"].edit(embed=embed)
        except discord.NotFound:
            return Resultado(False, "No se pudo actualizar el deck (el mensaje original ya no existe). "
                                    "Contacta con un administrador.")
        except discord.Forbidden:
            return Resultado(False, "No tengo permisos para editar el mensaje del deck.")

    return Resultado(True, "Deck actualizado correctamente. Has usado tu única edición disponible.", embed=embed)
