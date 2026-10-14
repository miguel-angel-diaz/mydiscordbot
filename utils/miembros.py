######## miembros.py #######
"""
Encontrar al jugador que alguien escribe en un asistente por DM (agendar, reportar, inscribir, battle).

Antes cada asistente llamaba a buscar_usuario_en_servidor a su manera: las menciones solo se entendían al
inscribir, un nombre que encajaba con varios daba "no encontrado" sin más, y nadie aceptaba "yo".

- candidatos(): quién puede ser el texto escrito (lógica pura, sin mensajes).
- resolver_jugador(): de un texto a un miembro, preguntando cuál si hay varios.
- pedir_jugador(): pregunta por DM y resuelve.
"""
import re
import unicodedata
from types import SimpleNamespace
from typing import List, Optional

import discord

from utils import dm

PATRON_MENCION = re.compile(r"^<@!?(\d+)>$")
PALABRAS_YO = {"yo", "mi", "me"}
MAX_CANDIDATOS = 10
AYUDA_FORMATO = "`yo`, nombre, apodo, mención o ID"


def normalizar(texto) -> str:
    """Minúsculas y sin tildes: 'José' y 'jose' son lo mismo al buscar."""
    texto = unicodedata.normalize("NFKD", str(texto or "")).casefold()
    return "".join(c for c in texto if not unicodedata.combining(c)).strip()


def id_de_texto(texto) -> Optional[int]:
    """ID de Discord si el texto es un ID o una mención (<@id> / <@!id>); None si no."""
    limpio = str(texto or "").strip()
    match = PATRON_MENCION.match(limpio)
    if match:
        return int(match.group(1))
    return int(limpio) if limpio.isdigit() else None


def _nombres(miembro) -> List[str]:
    return [normalizar(n) for n in (miembro.display_name, miembro.name, getattr(miembro, "global_name", None)) if n]


def ausente(user_id) -> SimpleNamespace:
    """Quien ya no está en el servidor pero sigue en un torneo (se reporta su partida por ID)."""
    return SimpleNamespace(id=str(user_id), display_name=f"Usuario {user_id}", name=f"Usuario {user_id}",
                           mention=f"<@{user_id}>", roles=[], bot=False)


def candidatos(guild, texto, autor=None) -> List:
    """
    Miembros que encajan con el texto, de más a menos seguro:
      - `yo` → el autor.
      - ID o mención → ese miembro; si ya no está en el servidor, un ausente() (quien llama decide si lo vale).
      - nombre, apodo o nombre global exactos (sin mayúsculas ni tildes) → todos los que coincidan.
      - si no hay exactos, los que lo contienen.
    Los bots no cuentan al buscar por nombre.
    """
    t = normalizar(texto)
    if not t:
        return []
    if t in PALABRAS_YO and autor is not None:
        return [autor]

    uid = id_de_texto(texto)
    if uid is not None:
        miembro = guild.get_member(uid)
        return [miembro] if miembro else [ausente(uid)]

    personas = [m for m in guild.members if not m.bot]
    exactos = [m for m in personas if t in _nombres(m)]
    if exactos:
        return exactos
    return [m for m in personas if any(t in n for n in _nombres(m))]


def describir(miembro) -> str:
    return miembro.display_name if miembro.display_name == miembro.name else f"{miembro.display_name} (@{miembro.name})"


async def resolver_jugador(bot, autor, guild, texto, *, permitir_ausente: bool = False,
                           timeout: float = dm.TIMEOUT_POR_DEFECTO):
    """
    Miembro que corresponde al texto escrito por `autor`, o None (ya avisado por DM).
    Si encaja con varios, se le pregunta cuál. Con permitir_ausente, un ID de alguien que ya no está en el
    servidor se acepta (devuelve un ausente(), no un discord.Member): sirve para reportar su partida.
    """
    encontrados = candidatos(guild, texto, autor)

    if not encontrados:
        await autor.send(f"❌ No encuentro a nadie como «{texto}» en el servidor. Prueba con la mención o el ID.")
        return None

    if len(encontrados) == 1:
        miembro = encontrados[0]
        if isinstance(miembro, discord.Member):
            if miembro.bot:
                await autor.send(f"❌ {miembro.display_name} es un bot.")
                return None
            return miembro
        if permitir_ausente:
            return miembro
        await autor.send(f"❌ El usuario con ID `{miembro.id}` no está en el servidor.")
        return None

    if len(encontrados) > MAX_CANDIDATOS:
        await autor.send(f"❌ Hay {len(encontrados)} personas que encajan con «{texto}». Escribe más del nombre, "
                         f"la mención o el ID.")
        return None

    encontrados.sort(key=lambda m: normalizar(m.display_name))
    indice = await dm.elegir_de_lista(bot, autor, f"🔎 Varias personas encajan con «{texto}». ¿Cuál es?",
                                      [describir(m) for m in encontrados], timeout)
    return None if indice is None else encontrados[indice]


async def pedir_jugador(bot, autor, guild, pregunta: str, *, permitir_ausente: bool = False,
                        timeout: float = dm.TIMEOUT_POR_DEFECTO):
    """Pregunta por un jugador por DM y lo resuelve; None si cancela, se agota el tiempo o no está (ya avisado)."""
    texto = await dm.preguntar(bot, autor, f"{pregunta} ({AYUDA_FORMATO})", timeout)
    if texto is None:
        return None
    return await resolver_jugador(bot, autor, guild, texto, permitir_ausente=permitir_ausente, timeout=timeout)
