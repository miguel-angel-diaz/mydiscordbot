# utils/torneos_estado.py
"""
Persistencia de los torneos en mensajes del bot (#torneos-estado, #rondas-torneo, #clasificaciones-torneo).

Formato de cada mensaje (la primera línea es la cabecera):
    📊 TORNEO: <codigo> | v=<versión>                     -> datos completos en un mensaje
    📊 TORNEO: <codigo> | PARTE i/n | v=<versión>          -> trozo i de n (JSON compacto)
seguido de un bloque ```json```. Los mensajes antiguos sin "v=" se siguen leyendo (versión 0).

Garantías:
  - Se lee el canal ENTERO (sin límite de 200 mensajes) y el código se compara exacto ("abc" no es "abc1").
  - Guardar es atómico: primero se publica la versión nueva completa y solo después se borra la anterior.
    Si algo falla a mitad, al leer se usa la versión completa más reciente, así que nunca se pierde un torneo.
  - Un JSON corrupto o una versión a medias no se ignora en silencio: queda registrado en el log.
  - Un lock por (canal, torneo) evita que dos escrituras del mismo torneo se pisen, y actualizar_torneo_estado
    hace leer-modificar-escribir dentro del lock.
"""
import asyncio
import discord
import json
import logging
import re
import random
import string
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from utils import canales

log = logging.getLogger(__name__)

CANALES = {
    "estado": canales.ESTADO_TORNEOS,
    "rondas": canales.RONDAS_TORNEOS,
    "clasificacion": canales.CLASIFICACIONES_TORNEOS
}
PREFIX = "📊 TORNEO: "
CABECERA = re.compile(r"^📊 TORNEO: (\S+)(?:\s*\|\s*PARTE\s*(\d+)/(\d+))?(?:\s*\|\s*v=(\d+))?\s*$")
BLOQUE_JSON = re.compile(r"```json\n(.*)\n```", re.DOTALL)
LIMITE_MENSAJE = 1900      # Discord admite 2000 caracteres por mensaje
TAM_TROZO = 1800
SIN_MENCIONES = discord.AllowedMentions.none()

_locks: Dict[Tuple[str, str], asyncio.Lock] = {}


def _lock(tipo: str, codigo: str) -> asyncio.Lock:
    return _locks.setdefault((tipo, codigo), asyncio.Lock())


# ============================================================
# FUNCIONES GENÉRICAS PARA CANALES
# ============================================================

async def _get_channel(bot, tipo: str):
    """Obtiene el canal correspondiente según el tipo."""
    for guild in bot.guilds:
        channel = canales.get_canal(guild, CANALES[tipo])
        if channel:
            return channel
    return None


def _cabecera(contenido: str):
    """(codigo, parte, total, version) de un mensaje de datos, o None si no lo es."""
    m = CABECERA.match((contenido or "").split("\n", 1)[0])
    if not m:
        return None
    codigo, parte, total, version = m.groups()
    return (codigo, int(parte) if parte else None, int(total) if total else None, int(version) if version else 0)


async def _mensajes_por_codigo(bot, channel, codigo: str = None) -> Dict[str, list]:
    """Recorre el canal entero una vez y agrupa los mensajes del bot por código EXACTO."""
    grupos = defaultdict(list)
    async for msg in channel.history(limit=None):
        if msg.author != bot.user:
            continue
        cab = _cabecera(msg.content)
        if not cab or (codigo is not None and cab[0] != codigo):
            continue
        grupos[cab[0]].append((msg, *cab[1:]))
    return grupos


def _decodificar(codigo: str, entradas: list) -> Optional[dict]:
    """
    Datos de la versión completa y válida más reciente. `entradas` = [(msg, parte, total, version)] en el orden
    del historial (más reciente primero).
    """
    versiones = defaultdict(lambda: {"sueltos": [], "partes": {}, "totales": set()})
    for msg, parte, total, version in entradas:
        m = BLOQUE_JSON.search(msg.content)
        if not m:
            continue
        v = versiones[version]
        if parte is None:
            v["sueltos"].append(m.group(1))
        else:
            v["partes"].setdefault(parte, m.group(1))
            v["totales"].add(total)

    mas_reciente = max(versiones, default=None)
    for version in sorted(versiones, reverse=True):
        v = versiones[version]
        candidatos = list(v["sueltos"])
        if v["partes"]:
            total = max(v["totales"])
            if len(v["totales"]) == 1 and all(i in v["partes"] for i in range(1, total + 1)):
                candidatos.insert(0, "".join(v["partes"][i] for i in range(1, total + 1)))
        for texto in candidatos:
            try:
                datos = json.loads(texto)
            except ValueError:
                continue
            if isinstance(datos, dict):
                if version != mas_reciente:
                    log.warning("Torneo %s: la versión %s está incompleta o corrupta; se usa la %s",
                                codigo, mas_reciente, version)
                return datos
    log.error("Torneo %s: ningún dato legible (%d mensajes). Revisa el canal a mano.", codigo, len(entradas))
    return None


def _componer_mensajes(codigo: str, datos: dict, version: int) -> List[str]:
    legible = json.dumps(datos, indent=2, separators=(",", ":"), ensure_ascii=False)
    contenido = f"{PREFIX}{codigo} | v={version}\n```json\n{legible}\n```"
    if len(contenido) <= LIMITE_MENSAJE:
        return [contenido]
    compacto = json.dumps(datos, separators=(",", ":"), ensure_ascii=False)
    trozos = [compacto[i:i + TAM_TROZO] for i in range(0, len(compacto), TAM_TROZO)]
    return [f"{PREFIX}{codigo} | PARTE {i}/{len(trozos)} | v={version}\n```json\n{t}\n```"
            for i, t in enumerate(trozos, 1)]


async def _leer_sin_lock(bot, channel, codigo: str) -> Optional[dict]:
    entradas = (await _mensajes_por_codigo(bot, channel, codigo)).get(codigo, [])
    return _decodificar(codigo, entradas) if entradas else None


async def _guardar_sin_lock(bot, channel, codigo: str, datos: dict):
    datos["codigo"] = codigo
    previos = (await _mensajes_por_codigo(bot, channel, codigo)).get(codigo, [])
    version = max((v for *_, v in previos), default=0) + 1
    mensajes = _componer_mensajes(codigo, datos, version)

    # Un único mensaje que sigue cabiendo en uno: editarlo es atómico
    if len(mensajes) == 1 and len(previos) == 1:
        await previos[0][0].edit(content=mensajes[0], allowed_mentions=SIN_MENCIONES)
        return

    # 1) Versión nueva completa. Si falla a mitad, la anterior sigue intacta y es la que se lee.
    for contenido in mensajes:
        await channel.send(contenido, allowed_mentions=SIN_MENCIONES)
    # 2) Solo entonces se borra la anterior (si algo no se borra, al leer gana la versión nueva).
    for msg, *_ in previos:
        try:
            await msg.delete()
        except discord.HTTPException as e:
            log.warning("Torneo %s: no se pudo borrar un mensaje de la versión anterior (%s)", codigo, e)


async def _guardar_dato_torneo(bot, tipo: str, codigo: str, datos: dict):
    """Guarda los datos del torneo en el canal del tipo indicado (troceados si no caben en un mensaje)."""
    channel = await _get_channel(bot, tipo)
    if not channel:
        log.error("No existe el canal #%s: no se guardan los datos de %s", CANALES[tipo], codigo)
        return
    async with _lock(tipo, codigo):
        await _guardar_sin_lock(bot, channel, codigo, datos)


async def _leer_dato_torneo(bot, tipo: str, codigo: str) -> Optional[dict]:
    """Lee los datos de un torneo, uniendo las partes si están divididas."""
    channel = await _get_channel(bot, tipo)
    if not channel:
        return None
    async with _lock(tipo, codigo):
        return await _leer_sin_lock(bot, channel, codigo)


async def _eliminar_mensaje_torneo(bot, tipo: str, codigo: str):
    """Elimina todos los mensajes de un torneo en un canal."""
    channel = await _get_channel(bot, tipo)
    if not channel:
        return
    async with _lock(tipo, codigo):
        for msg, *_ in (await _mensajes_por_codigo(bot, channel, codigo)).get(codigo, []):
            try:
                await msg.delete()
            except discord.HTTPException as e:
                log.warning("Torneo %s: no se pudo borrar un mensaje de #%s (%s)", codigo, CANALES[tipo], e)

# ============================================================
# FUNCIONES ESPECÍFICAS PARA CADA TIPO
# ============================================================

async def leer_estado(bot):
    """
    Lee el estado de todos los torneos desde el canal #torneos-estado (una sola pasada por el canal).
    Devuelve un diccionario con la clave 'torneos' que contiene una lista de torneos (uno por código).
    """
    channel = await _get_channel(bot, "estado")
    if not channel:
        return {"torneos": []}

    torneos = []
    for codigo, entradas in (await _mensajes_por_codigo(bot, channel)).items():
        data = _decodificar(codigo, entradas)
        if data:
            torneos.append(data)
    return {"torneos": torneos}

async def actualizar_torneo_estado(bot, codigo: str, datos: dict):
    """Mezcla `datos` con el estado guardado del torneo (leer-modificar-escribir dentro del lock)."""
    channel = await _get_channel(bot, "estado")
    if not channel:
        log.error("No existe el canal #%s: no se guarda el estado de %s", CANALES["estado"], codigo)
        return
    async with _lock("estado", codigo):
        entradas = (await _mensajes_por_codigo(bot, channel, codigo)).get(codigo, [])
        actual = _decodificar(codigo, entradas) if entradas else None
        if entradas and actual is None:
            # Hay datos pero ilegibles: escribir solo `datos` borraría el resto del torneo
            raise RuntimeError(f"El estado guardado del torneo {codigo} está corrupto; no se sobrescribe.")
        if actual:
            actual.update(datos)
            datos = actual
        await _guardar_sin_lock(bot, channel, codigo, datos)

async def eliminar_torneo_estado(bot, codigo: str):
    for tipo in ["estado", "rondas", "clasificacion"]:
        await _eliminar_mensaje_torneo(bot, tipo, codigo)

async def obtener_torneo_estado(bot, codigo: str) -> Optional[dict]:
    return await _leer_dato_torneo(bot, "estado", codigo)

# --- RONDAS ---
async def leer_rondas(bot, codigo: str) -> Optional[dict]:
    return await _leer_dato_torneo(bot, "rondas", codigo)

async def guardar_rondas(bot, codigo: str, datos: dict):
    await _guardar_dato_torneo(bot, "rondas", codigo, datos)

# --- CLASIFICACIÓN ---
async def leer_clasificacion(bot, codigo: str) -> Optional[dict]:
    return await _leer_dato_torneo(bot, "clasificacion", codigo)

async def guardar_clasificacion(bot, codigo: str, datos: dict):
    await _guardar_dato_torneo(bot, "clasificacion", codigo, datos)

# ============================================================
# UTILIDADES
# ============================================================

def slugify_challonge(value: str) -> str:
    value = value.lower()
    return re.sub(r'[^a-z0-9]', '', value)

def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))
