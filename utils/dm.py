######## dm.py #######
"""
Piezas comunes de los asistentes por mensaje privado (antes había 32 copias de dm_check y 82 wait_for).

- esperar_respuesta(): el siguiente mensaje del usuario por DM. Lanza asyncio.TimeoutError igual que wait_for,
  así los asistentes conservan su manejo del tiempo agotado.
- indice_elegido(): número de una lista mostrada (1..N). Antes se hacía lista[int(texto) - 1] y "0" elegía el
  ÚLTIMO elemento sin avisar ("-1" el penúltimo).
- es_si() / es_cancelar(): respuestas de confirmación y de salida.
- preguntar() / elegir_de_lista(): pregunta completa con sus avisos (tiempo agotado, cancelar, número no válido).
"""
import asyncio
from typing import List, Optional

import discord

RESPUESTAS_SI = {"sí", "si", "s", "yes", "y"}
PALABRA_CANCELAR = "cancelar"
TIMEOUT_POR_DEFECTO = 90


def es_respuesta_de(usuario):
    """Check para wait_for: mensaje del usuario en su DM con el bot (Member == User compara por ID en discord.py)."""
    return lambda m: m.author == usuario and isinstance(m.channel, discord.DMChannel)


async def esperar_respuesta(bot, usuario, timeout: float = TIMEOUT_POR_DEFECTO):
    """Siguiente mensaje del usuario por DM. Lanza asyncio.TimeoutError si no contesta a tiempo."""
    return await bot.wait_for("message", check=es_respuesta_de(usuario), timeout=timeout)


def indice_elegido(texto, total: int) -> Optional[int]:
    """'3' -> 2 si 1 <= 3 <= total; cualquier otra cosa (incluidos '0' y negativos) -> None."""
    limpio = str(texto or "").strip()
    if not limpio.isdigit():
        return None
    numero = int(limpio)
    return numero - 1 if 1 <= numero <= total else None


def es_si(texto) -> bool:
    return str(texto or "").strip().lower() in RESPUESTAS_SI


def es_cancelar(texto) -> bool:
    return str(texto or "").strip().lower() == PALABRA_CANCELAR


async def preguntar(bot, usuario, texto: str, timeout: float = TIMEOUT_POR_DEFECTO) -> Optional[str]:
    """Pregunta por DM y devuelve la respuesta, o None si se agota el tiempo o escribe 'cancelar' (avisando)."""
    await usuario.send(texto)
    try:
        resp = await esperar_respuesta(bot, usuario, timeout)
    except asyncio.TimeoutError:
        await usuario.send("⏰ Tiempo agotado. Vuelve a intentarlo.")
        return None
    if es_cancelar(resp.content):
        await usuario.send("❌ Operación cancelada.")
        return None
    return resp.content.strip()


async def elegir_de_lista(bot, usuario, titulo: str, opciones: List[str],
                          timeout: float = TIMEOUT_POR_DEFECTO) -> Optional[int]:
    """Muestra una lista numerada (troceada si es larga) y devuelve el índice elegido, o None."""
    from utils.commons import trocear_lista   # import local: commons es grande y no hace falta al cargar
    texto = f"{titulo}\n" + "\n".join(f"{i}. {o}" for i, o in enumerate(opciones, 1))
    trozos = trocear_lista(texto, 1900)
    for trozo in trozos[:-1]:
        await usuario.send(trozo)
    resp = await preguntar(bot, usuario, f"{trozos[-1]}\n\nEscribe el número (o `cancelar`).", timeout)
    if resp is None:
        return None
    indice = indice_elegido(resp, len(opciones))
    if indice is None:
        await usuario.send("❌ Número no válido. Operación cancelada.")
    return indice
