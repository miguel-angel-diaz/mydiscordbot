######## analisis.py #######
"""
Análisis automático de fin de torneo en #🧠📈analisis-torneos: las TOP_CARTAS cartas más jugadas (main, sin
tierras básicas) y el porcentaje de decks de cada arquetipo. Se publica al finalizar un suizo, a partir de los
decks de #submitted-decks; si ya hay un análisis de ese torneo en el canal, se edita en lugar de repetirlo.
"""
import asyncio
import io
import logging
from collections import Counter
from typing import Dict, List, Optional, Tuple

import discord

import config
from utils import canales
from utils import decks as decks_util
from utils.commons import trocear_lista
from utils.torneos_estado import leer_estado, obtener_torneo_estado

log = logging.getLogger(__name__)

TOP_CARTAS = 10
CARTAS_BASICAS = {"mountain", "swamp", "plains", "island", "forest", "wastes"}
SIN_ARQUETIPO = "Sin arquetipo"
MAX_PORCIONES = 8              # en el donut, el resto de arquetipos se agrupa en "Otros" (el texto los lista todos)
TITULO = "🧠 Análisis del torneo"
PIE_CODIGO = "Torneo "          # el pie lleva el código: así se encuentra el análisis para editarlo


# ============================================================
# CÁLCULOS (sin Discord)
# ============================================================

def _lineas_main(decklist: str):
    """(cantidad, carta) de cada línea "N Carta" (también "Nx Carta")."""
    for linea in (decklist or "").splitlines():
        partes = linea.strip().split(" ", 1)
        if len(partes) != 2:
            continue
        cantidad, carta = partes[0].lower().rstrip("x"), partes[1].strip()
        if cantidad.isdigit() and carta:
            yield int(cantidad), carta


def top_cartas(decks: List[Dict], n: int = TOP_CARTAS) -> List[Tuple[str, int, int]]:
    """[(carta, copias en total, nº de decks que la juegan)] de las n más jugadas, sin tierras básicas."""
    copias, en_decks = Counter(), Counter()
    for deck in decks:
        vistas = set()
        for cantidad, carta in _lineas_main(deck.get("decklist")):
            if carta.lower() in CARTAS_BASICAS:
                continue
            copias[carta] += cantidad
            vistas.add(carta)
        en_decks.update(vistas)
    # Empate de copias: primero la que aparece en más decks
    orden = sorted(copias, key=lambda c: (-copias[c], -en_decks[c], c.lower()))
    return [(c, copias[c], en_decks[c]) for c in orden[:n]]


def reparto_arquetipos(decks: List[Dict]) -> List[Tuple[str, int, float]]:
    """[(arquetipo, nº de decks, %)] de más a menos jugado."""
    contador = Counter()
    for deck in decks:
        nombre = (deck.get("archetype") or "").strip()
        contador[SIN_ARQUETIPO if not nombre or nombre.lower() in ("desconocido", "no especificado") else nombre] += 1
    total = sum(contador.values())
    orden = sorted(contador, key=lambda a: (-contador[a], a.lower()))
    return [(a, contador[a], contador[a] * 100 / total) for a in orden]


# ============================================================
# PRESENTACIÓN
# ============================================================

def construir_embed(codigo: str, nombre: str, decks: List[Dict]) -> discord.Embed:
    cartas = top_cartas(decks)
    arquetipos = reparto_arquetipos(decks)
    embed = discord.Embed(title=f"{TITULO}: {nombre}",
                          description=f"Datos de los **{len(decks)}** decks presentados.",
                          color=discord.Color.teal())
    embed.add_field(
        name=f"🃏 Top {len(cartas)} cartas más jugadas (sin básicas)",
        value="\n".join(f"**{i}.** {carta} — {copias} copias · en {n_decks} deck{'s' if n_decks != 1 else ''}"
                        for i, (carta, copias, n_decks) in enumerate(cartas, start=1)) or "—",
        inline=False)
    lineas = [f"**{pct:.1f}%** {arquetipo} ({n})" for arquetipo, n, pct in arquetipos]
    for i, trozo in enumerate(trocear_lista("\n".join(lineas))):
        embed.add_field(name="📊 Decks jugados" if i == 0 else "📊 Decks jugados (cont.)", value=trozo, inline=False)
    embed.set_footer(text=f"{PIE_CODIGO}{codigo}")
    return embed


def _grafico(codigo: str, decks: List[Dict]) -> bytes:
    """PNG con las dos estadísticas. Usa Figure (no pyplot) para poder ejecutarse en un hilo sin bloquear el bot."""
    from matplotlib.figure import Figure
    cartas = top_cartas(decks)
    arquetipos = reparto_arquetipos(decks)

    fig = Figure(figsize=(12, 6))
    ax_cartas, ax_decks = fig.subplots(1, 2)

    nombres = [c for c, _, _ in cartas][::-1]
    ax_cartas.barh(nombres, [n for _, n, _ in cartas][::-1], color="#2a9d8f")
    ax_cartas.set_title(f"Top {len(cartas)} cartas más jugadas")
    ax_cartas.set_xlabel("Copias")
    ax_cartas.tick_params(axis="y", labelsize=9)

    porciones = [(a, n) for a, n, _ in arquetipos[:MAX_PORCIONES]]
    if len(arquetipos) > MAX_PORCIONES:
        porciones[-1] = ("Otros", sum(n for _, n, _ in arquetipos[MAX_PORCIONES - 1:]))
    ax_decks.pie([n for _, n in porciones], labels=[a for a, _ in porciones], autopct="%1.1f%%",
                 startangle=90, pctdistance=0.8, textprops={"fontsize": 9}, wedgeprops={"width": 0.4})
    ax_decks.axis("equal")
    ax_decks.set_title("Decks jugados")

    fig.suptitle(f"Torneo {codigo}")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="PNG")
    return buf.getvalue()


# ============================================================
# PUBLICACIÓN
# ============================================================

async def torneos_analizables(bot) -> List[dict]:
    """Suizos finalizados (con el torneo en juego los decks son privados), el más reciente primero."""
    torneos = (await leer_estado(bot)).get("torneos", [])
    return [t for t in reversed(torneos) if t.get("codigo") and t.get("tipo") == "swiss" and t.get("estado") == "finalizado"]


async def _analisis_existente(canal, bot, codigo: str) -> Optional[discord.Message]:
    async for mensaje in canal.history(limit=100):
        if mensaje.author == bot.user and any(
                e.title and e.title.startswith(TITULO) and getattr(e.footer, "text", None) == f"{PIE_CODIGO}{codigo}"
                for e in mensaje.embeds):
            return mensaje
    return None


async def publicar_analisis(bot, codigo: str, guild: discord.Guild = None) -> Tuple[bool, str]:
    guild = guild or bot.get_guild(config.GUILD_ID_ADMISION)
    canal = canales.get_canal(guild, canales.ANALISIS_TORNEOS)
    if not canal:
        return False, f"No existe el canal #{canales.ANALISIS_TORNEOS}."
    decks = await decks_util.listar(guild, codigo_torneo=codigo)
    if not decks:
        return False, f"El torneo `{codigo}` no tiene decks: no hay análisis."

    torneo = await obtener_torneo_estado(bot, codigo) or {}
    embed = construir_embed(codigo, torneo.get("nombre", codigo), decks)
    try:
        png = await asyncio.to_thread(_grafico, codigo, decks)
        archivo = discord.File(io.BytesIO(png), filename=f"analisis_{codigo}.png")
        embed.set_image(url=f"attachment://analisis_{codigo}.png")
    except Exception:
        log.exception("⚠️ No se pudo dibujar el gráfico del análisis de %s: se publica solo el texto", codigo)
        archivo = None

    existente = await _analisis_existente(canal, bot, codigo)
    if existente:
        await existente.edit(embed=embed, attachments=[archivo] if archivo else [])
    elif archivo:
        await canal.send(embed=embed, file=archivo)
    else:
        await canal.send(embed=embed)
    return True, f"Análisis de `{codigo}` publicado en #{canales.ANALISIS_TORNEOS} ({len(decks)} decks)."


async def al_finalizar_torneo(bot, codigo: str, guild: discord.Guild = None):
    """Gancho del suizo al terminar: nunca rompe la finalización aunque falle."""
    try:
        ok, msg = await publicar_analisis(bot, codigo, guild)
        (log.info if ok else log.warning)("🧠 %s", msg)
    except Exception:
        log.exception("❌ No se pudo publicar el análisis de %s", codigo)
