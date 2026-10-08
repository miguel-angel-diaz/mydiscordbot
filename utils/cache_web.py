######## cache_web.py #######
"""
Caché de la web (torneos antiguos de Challonge: clasificación, participantes y partidos).

- Vive en memoria: las peticiones web no leen el disco (antes, un open() síncrono en cada visita).
- Se guarda en config.CACHE_PATH de forma atómica (temporal + os.replace), en un hilo y con un lock,
  así dos escrituras a la vez (!actualizar-web y el endpoint de enfrentamientos) no se pisan.
- En Railway el disco se rehace en cada deploy: al arrancar se regenera en segundo plano si falta o está
  vieja (ver necesita_regenerar). Con un Volume montado y CACHE_PATH apuntando a él, además persiste.
"""
import asyncio
import copy
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import config

log = logging.getLogger(__name__)

MAX_ANTIGUEDAD = timedelta(hours=24)

_memoria: Optional[dict] = None
_cargada = False
_lock = asyncio.Lock()


def _leer_disco() -> Optional[dict]:
    ruta = config.CACHE_PATH
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else None
    except (OSError, ValueError) as e:
        log.error("Caché web ilegible en %s (%s): se ignora y se regenerará", ruta, e)
        return None


def _escribir_disco(datos: dict):
    ruta = config.CACHE_PATH
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    tmp = f"{ruta}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


async def cargar():
    """Carga la caché del disco a memoria (al arrancar, sin bloquear el bucle)."""
    global _memoria, _cargada
    _memoria = await asyncio.to_thread(_leer_disco)
    _cargada = True
    return leer()


def leer() -> Optional[dict]:
    """Copia de la caché (los llamadores pueden modificarla sin tocar la memoria compartida)."""
    global _memoria, _cargada
    if not _cargada:                       # por si alguien lee antes de cargar(): lectura única
        _memoria, _cargada = _leer_disco(), True
    return copy.deepcopy(_memoria) if _memoria is not None else None


async def guardar(datos: dict):
    async with _lock:
        await _guardar_sin_lock(datos)


async def _guardar_sin_lock(datos: dict):
    global _memoria, _cargada
    await asyncio.to_thread(_escribir_disco, datos)
    _memoria, _cargada = copy.deepcopy(datos), True


async def actualizar_torneo(codigo: str, cambios: dict, nuevo: Callable[[], dict] = None):
    """Leer-modificar-escribir de UN torneo dentro del lock (si no existe y hay `nuevo`, se añade)."""
    async with _lock:
        datos = leer() or {"torneos": []}
        torneo = next((t for t in datos.setdefault("torneos", []) if t.get("codigo") == codigo), None)
        if torneo is None:
            if nuevo is None:
                return
            torneo = nuevo()
            datos["torneos"].append(torneo)
        torneo.update(cambios)
        await _guardar_sin_lock(datos)


def necesita_regenerar(ahora: datetime = None) -> bool:
    """Sin caché, sin fecha, con fecha ilegible o con más de MAX_ANTIGUEDAD."""
    datos = leer()
    if not datos:
        return True
    try:
        actualizado = datetime.fromisoformat(datos["actualizado"])
    except (KeyError, TypeError, ValueError):
        return True
    if actualizado.tzinfo is None:
        actualizado = actualizado.replace(tzinfo=timezone.utc)
    return (ahora or datetime.now(timezone.utc)) - actualizado > MAX_ANTIGUEDAD
