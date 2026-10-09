######## decks.py #######
"""
Todo lo de un deck en un solo sitio, compartido por la web y por Discord:
  - Reglas (nombre, formato, arquetipo, decklist y sideboard). Cada función devuelve el valor limpio o lanza
    DeckInvalido (subclase de EntradaInvalida: en la web, un 400; en Discord se muestra y se vuelve a preguntar).
  - El embed que se guarda en #submitted-decks: un único constructor y un único lector (que entiende también
    los decks subidos con los formatos anteriores).
  - Búsqueda en el canal (entero, sin el límite de 500 mensajes de antes) y publicación con lock.
"""
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, List, Optional, Tuple

import discord

from utils import canales
from utils.commons import (
    CAMPO_EDICIONES,
    PATRON_CODIGO_ETIQUETADO,
    anadir_campos_lista,
    contar_cartas,
    leer_campo_lista,
    leer_ediciones,
    limpiar_deck_raw,
    lock_edicion_deck,
    obtener_sugerencias_arquetipos,
)
from utils.validacion_web import (
    EntradaInvalida,
    FORMATOS_VALIDOS,
    MAX_DECKLIST,
    MAX_NOMBRE,
    MAX_SIDEBOARD,
    texto,
)

MIN_CARTAS_MAIN = 60
MAX_CARTAS_SIDEBOARD = 15
SIN_SIDEBOARD = "N/A"


class DeckInvalido(EntradaInvalida):
    """Deck que no cumple las reglas. `sugerencias` se rellena cuando el arquetipo no se reconoce."""
    def __init__(self, mensaje: str, sugerencias: List[str] = None):
        super().__init__(mensaje)
        self.sugerencias = sugerencias or []


def _texto(valor, campo: str, max_len: int, **kwargs) -> str:
    try:
        limpio = texto(valor, campo, max_len, **kwargs)
    except EntradaInvalida as e:
        raise DeckInvalido(e.mensaje)
    # Ningún nombre de carta lleva < ni >: rechazarlos corta de raíz el HTML en los decks, que ven otros socios en la
    # web (defensa en profundidad: la web ya escapa todo lo que pinta)
    if "<" in limpio or ">" in limpio:
        raise DeckInvalido(f"El campo {campo} no puede contener los caracteres < ni >")
    return limpio


def nombre_deck(valor) -> str:
    """Una línea, sin caracteres de control ni menciones, de 1 a MAX_NOMBRE caracteres (cabe en el título del embed)."""
    return _texto(valor, "nombre del deck", MAX_NOMBRE, markdown=True)


def formato(valor) -> Optional[str]:
    """'Premodern' / 'Pauper' si el texto los nombra (sin distinguir mayúsculas); None si no se reconoce o está vacío."""
    limpio = str(valor or "").strip().lower()
    if limpio in FORMATOS_VALIDOS:
        return FORMATOS_VALIDOS[limpio]
    nombrados = [nombre for clave, nombre in FORMATOS_VALIDOS.items() if clave in limpio]
    return nombrados[0] if len(nombrados) == 1 else None


def arquetipo(valor, formato_deck: str) -> Tuple[Optional[str], List[str]]:
    """(nombre exacto de la lista del formato o None, sugerencias). Sin coincidencia exacta no se acepta."""
    escrito = str(valor or "").strip()
    if not escrito:
        return None, []
    sugerencias = obtener_sugerencias_arquetipos(escrito, formato=formato_deck, max_sugerencias=5)
    exacto = next((s for s in sugerencias if s.lower() == escrito.lower()), None)
    return exacto, sugerencias


def arquetipo_obligatorio(valor, formato_deck: str) -> str:
    exacto, sugerencias = arquetipo(valor, formato_deck)
    if not exacto:
        raise DeckInvalido("Arquetipo no reconocido", sugerencias)
    return exacto


def decklist(valor) -> str:
    """Main limpio (solo líneas 'N Carta'); al menos MIN_CARTAS_MAIN cartas."""
    limpio = limpiar_deck_raw(_texto(valor, "decklist", MAX_DECKLIST, multilinea=True, markdown=True))
    total = contar_cartas(limpio)
    if total < MIN_CARTAS_MAIN:
        raise DeckInvalido(f"La decklist tiene {total} cartas (mínimo {MIN_CARTAS_MAIN})")
    return limpio


def sideboard(valor) -> str:
    """Sideboard limpio o 'N/A' (vacío, 'N/A' o sin ninguna línea de cartas); como mucho MAX_CARTAS_SIDEBOARD cartas."""
    escrito = str(valor or "").strip()
    if escrito.lower() in ("", "n/a"):
        return SIN_SIDEBOARD
    limpio = limpiar_deck_raw(_texto(escrito, "sideboard", MAX_SIDEBOARD, obligatorio=False, multilinea=True, markdown=True))
    if not limpio:
        return SIN_SIDEBOARD                      # un campo vacío rompería el embed
    total = contar_cartas(limpio)
    if total > MAX_CARTAS_SIDEBOARD:
        raise DeckInvalido(f"La sideboard tiene {total} cartas (máximo {MAX_CARTAS_SIDEBOARD})")
    return limpio


# ============================================================
# EMBED DE #submitted-decks
# ============================================================

CANAL_DECKS = canales.DECKS
TITULO_SUBIDO = "🃏 Deck Subido: "
TITULO_ACTUALIZADO = "🃏 Deck Actualizado: "
_PATRON_TITULO = re.compile(r"^🃏\s*Deck (?:Subido|Actualizado):\s*")
_PATRON_CODIGO = PATRON_CODIGO_ETIQUETADO
_PATRON_TORNEO = re.compile(r"Torneo:\**\s*`([^`]+)`", re.IGNORECASE)
_PATRON_FORMATO = re.compile(r"Formato:\**\s*(.+?)(?:\n|$)", re.IGNORECASE)
_PATRON_ID_JUGADOR = re.compile(r"\(ID:\s*(\d+)\)")


def codigo_deck(codigo_torneo: str, jugador_id) -> str:
    return f"{codigo_torneo}_{jugador_id}"


def construir_embed(codigo_torneo: str, jugador, nombre_deck: str, formato: str, archetype: str,
                    decklist: str, sideboard: str, ediciones: int = 0, actualizado: bool = False,
                    via_web: bool = False) -> discord.Embed:
    """
    El embed del deck tal y como se guarda en #submitted-decks (único sitio que lo construye).
    `ediciones` es el contador "N/1"; un deck sin ediciones disponibles se pinta en naranja.
    """
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    embed = discord.Embed(
        title=f"{TITULO_ACTUALIZADO if actualizado else TITULO_SUBIDO}{nombre_deck}",
        description=(f"**Código:** `{codigo_deck(codigo_torneo, jugador.id)}`\n"
                     f"**Torneo:** `{codigo_torneo}`\n**Formato:** {formato}"),
        color=discord.Color.orange() if ediciones >= 1 else discord.Color.purple(),
    )
    mencion = getattr(jugador, "mention", None) or f"<@{jugador.id}>"
    embed.add_field(name="Jugador", value=f"{mencion} (ID: {jugador.id})", inline=False)
    embed.add_field(name="Archetype", value=archetype, inline=False)
    anadir_campos_lista(embed, "Decklist", decklist)
    anadir_campos_lista(embed, "Sideboard", sideboard)
    embed.add_field(name=CAMPO_EDICIONES, value=f"{ediciones}/1", inline=False)
    origen = " (vía web)" if via_web else ""
    embed.set_footer(text=f"{'Última edición' if actualizado else 'Subido el'}: {fecha}{origen}")
    return embed


def leer_embed(embed) -> Optional[Dict]:
    """
    Datos de un embed de deck, o None si no lo es. Acepta los formatos que ha tenido el embed
    (nombre de usuario o mención en "Jugador", campos troceados, nombres antiguos del contador).
    """
    titulo = getattr(embed, "title", None) or ""
    if not titulo.startswith("🃏 Deck"):
        return None
    descripcion = getattr(embed, "description", None) or ""
    m_codigo = _PATRON_CODIGO.search(descripcion)
    if not m_codigo:
        return None
    codigo = m_codigo.group(1).strip()
    campos = {f.name: f.value for f in getattr(embed, "fields", [])}
    por_nombre = {str(k).strip().lower(): v for k, v in campos.items()}

    m_torneo = _PATRON_TORNEO.search(descripcion)
    torneo = m_torneo.group(1).strip() if m_torneo else codigo.rsplit("_", 1)[0]
    m_id = _PATRON_ID_JUGADOR.search(por_nombre.get("jugador", ""))
    jugador_id = m_id.group(1) if m_id else (codigo.rsplit("_", 1)[1] if "_" in codigo else None)
    m_formato = _PATRON_FORMATO.search(descripcion)

    return {
        "codigo_deck": codigo,
        "codigo_torneo": torneo,
        "torneo": torneo,
        "discord_id": jugador_id,
        # Como texto: es un ID de Discord de 18-19 cifras y JavaScript redondea los números de más de 15-16
        "jugador_id": jugador_id if jugador_id and jugador_id.isdigit() else None,
        "jugador": por_nombre.get("jugador", "Desconocido"),
        "nombre_deck": _PATRON_TITULO.sub("", titulo).strip() or titulo,
        "formato": m_formato.group(1).strip() if m_formato else "Premodern",
        "archetype": por_nombre.get("archetype", "Desconocido"),
        "decklist": leer_campo_lista(campos, "Decklist"),
        "sideboard": leer_campo_lista(campos, "Sideboard") or SIN_SIDEBOARD,
        "edited": leer_ediciones(campos),
    }


# ============================================================
# BÚSQUEDA Y PUBLICACIÓN EN EL CANAL
# ============================================================

def canal_decks(guild):
    return canales.get_canal(guild, CANAL_DECKS) if guild else None


async def _recorrer(guild) -> AsyncIterator[Dict]:
    """Todos los decks del canal (del más reciente al más antiguo), cada uno con su "mensaje"."""
    canal = canal_decks(guild)
    if not canal:
        return
    async for mensaje in canal.history(limit=None):
        for embed in mensaje.embeds:
            datos = leer_embed(embed)
            if datos:
                datos["mensaje"] = datos["_mensaje"] = mensaje
                yield datos


async def buscar(guild, codigo: str) -> Optional[Dict]:
    """El deck con ese código EXACTO ("torneo_idjugador"), o None."""
    async for datos in _recorrer(guild):
        if datos["codigo_deck"] == codigo:
            return datos
    return None


async def listar(guild, codigo_torneo: str = None, jugador_id=None) -> List[Dict]:
    """Decks del canal, filtrados por torneo (código exacto) y/o jugador."""
    jugador_id = str(jugador_id) if jugador_id is not None else None
    return [d async for d in _recorrer(guild)
            if (codigo_torneo is None or d["codigo_torneo"] == codigo_torneo)
            and (jugador_id is None or d["discord_id"] == jugador_id)]


async def codigos_subidos(guild) -> set:
    """Códigos de deck ("torneo_idjugador") de todos los decks subidos."""
    return {d["codigo_deck"] async for d in _recorrer(guild)}


async def publicar(guild, embed: discord.Embed, codigo: str) -> Tuple[bool, str]:
    """
    Publica un deck NUEVO. Dentro del lock del deck se comprueba que no exista ya, así subir a la vez desde la
    web y desde Discord (o dos veces) no crea dos. Devuelve (ok, motivo): "ok", "ya_existe" o "sin_canal".
    """
    canal = canal_decks(guild)
    if not canal:
        return False, "sin_canal"
    async with lock_edicion_deck(codigo):
        if await buscar(guild, codigo):
            return False, "ya_existe"
        await canal.send(embed=embed)
    return True, "ok"
