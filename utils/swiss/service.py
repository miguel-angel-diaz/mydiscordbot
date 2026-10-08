######## swiss/service.py #######
"""
Operaciones del suizo sobre el estado guardado: leen, aplican la lógica de engine.py y guardan, siempre con el
lock del torneo. Es el único sitio que modifica un torneo suizo (comandos, web y abandonos pasan por aquí);
los mensajes de Discord los escribe presentacion.py.
"""
import asyncio
import functools
import logging
from typing import Dict, List, Optional, Tuple

import discord

import config
from utils.swiss import engine, presentacion
from utils.torneos_estado import (
    actualizar_torneo_estado,
    eliminar_torneo_estado,
    obtener_torneo_estado,
    leer_rondas,
    guardar_rondas,
    guardar_clasificacion,
    leer_estado,
    slugify_challonge,
    generar_codigo_unico
)
from utils.validacion_web import EntradaInvalida, resultado as validar_resultado

log = logging.getLogger(__name__)

# ============================================================
# LOCK POR TORNEO
# ============================================================

class _LockReentrante:
    """
    asyncio.Lock que la MISMA tarea puede volver a tomar. Hace falta porque las operaciones se llaman entre sí
    (reportar_resultado -> _siguiente_ronda_automatica -> generar_ronda; retirar_por_abandono -> reportar_resultado)
    y con un Lock normal la tarea se quedaría esperándose a sí misma.
    """
    def __init__(self):
        self._lock = asyncio.Lock()
        self._dueno = None
        self._nivel = 0

    async def __aenter__(self):
        tarea = asyncio.current_task()
        if self._dueno is tarea:
            self._nivel += 1
            return self
        await self._lock.acquire()
        self._dueno, self._nivel = tarea, 1
        return self

    async def __aexit__(self, *exc):
        self._nivel -= 1
        if self._nivel == 0:
            self._dueno = None
            self._lock.release()


_locks_torneo: Dict[str, _LockReentrante] = {}


def lock_torneo(codigo: str) -> _LockReentrante:
    """
    Lock de un torneo para leer-modificar-escribir su estado y sus rondas. Lo toman todas las operaciones de este
    módulo; los asistentes por DM nunca lo sujetan mientras esperan una respuesta.
    """
    return _locks_torneo.setdefault(str(codigo), _LockReentrante())


def _con_lock_torneo(func):
    """Ejecuta la operación (bot, codigo, ...) con el lock del torneo."""
    @functools.wraps(func)
    async def envoltura(*args, **kwargs):
        codigo = kwargs["codigo"] if "codigo" in kwargs else args[1]
        async with lock_torneo(codigo):
            return await func(*args, **kwargs)
    return envoltura


async def _leer_lista_rondas(bot, codigo: str) -> List[dict]:
    return ((await leer_rondas(bot, codigo)) or {}).get("rondas", [])


async def _guardar_lista_rondas(bot, codigo: str, rondas: List[dict]):
    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": rondas})

# ============================================================
# CONSULTAS
# ============================================================

async def obtener_torneos_activos(bot) -> List[Dict]:
    estado = await leer_estado(bot)
    torneos = estado.get("torneos", []) if isinstance(estado, dict) else []
    return [t for t in torneos if t.get("tipo") == "swiss"]


async def obtener_torneo(bot, codigo: str) -> Optional[Dict]:
    return await obtener_torneo_estado(bot, codigo)


async def obtener_rondas(bot, codigo: str) -> List[dict]:
    return await _leer_lista_rondas(bot, codigo)


async def calcular_clasificacion(bot, codigo: str) -> List[Dict]:
    """Recalcula la clasificación desde las rondas y la guarda."""
    torneo = await obtener_torneo(bot, codigo)
    if not torneo or not torneo.get("inscritos_ids"):
        return []
    clasificacion = engine.clasificacion(codigo, await _leer_lista_rondas(bot, codigo), torneo["inscritos_ids"])
    await guardar_clasificacion(bot, codigo, {"codigo": codigo, "clasificacion": clasificacion})
    return clasificacion


async def publicar_clasificacion_swiss(bot, guild, codigo: str):
    """Recalcula y guarda la clasificación y, si hay servidor, la publica (así incluye la última ronda jugada)."""
    clasificacion = await calcular_clasificacion(bot, codigo)
    if guild and await obtener_torneo(bot, codigo):
        await presentacion.publicar_clasificacion(bot, guild, codigo, clasificacion)


async def publicar_emparejamientos(bot, guild, codigo: str):
    """Publica los emparejamientos de la última ronda del torneo."""
    rondas = await _leer_lista_rondas(bot, codigo)
    if guild and rondas:
        await presentacion.publicar_emparejamientos(guild, codigo, rondas[-1])

# ============================================================
# GESTIÓN DE TORNEOS
# ============================================================

async def crear_torneo(bot, nombre: str, formato: str, max_jugadores: int, nivel: str, fecha_inicio: str) -> str:
    codigo = f"{slugify_challonge(formato)}{slugify_challonge(nivel)}{generar_codigo_unico(6)}"
    await actualizar_torneo_estado(bot, codigo, {
        "nombre": nombre,
        "formato": formato,
        "nivel": nivel,
        "total_maximo": int(max_jugadores),
        "tipo": "swiss",
        "fecha_inicio": fecha_inicio,
        "estado": "abierto",
        "ronda_actual": 0,
        "inscritos_ids": [],
        "recordatorio_3d_enviado": False,
        "recordatorio_1d_enviado": False,
    })
    await _guardar_lista_rondas(bot, codigo, [])
    await guardar_clasificacion(bot, codigo, {"codigo": codigo, "clasificacion": []})
    return codigo


@_con_lock_torneo
async def eliminar_torneo_swiss(bot, codigo: str) -> bool:
    await eliminar_torneo_estado(bot, codigo)
    return True


@_con_lock_torneo
async def iniciar_torneo(bot, codigo: str, quitar_ids=()) -> Tuple[bool, str]:
    """
    Cierra inscripciones (quitando a `quitar_ids`, p. ej. los que no subieron deck) y genera la ronda 1, sobre los
    datos ACTUALES: mientras el admin respondía por DM otro pudo iniciarlo o alguien inscribirse. Si falla, todo
    vuelve atrás.
    """
    actual = await obtener_torneo(bot, codigo)
    if not actual or actual.get("estado") != "abierto" or actual.get("ronda_actual", 0) != 0:
        return False, f"El torneo `{codigo}` ya no está abierto (¿lo ha iniciado otro admin?). No se ha cambiado nada."
    inscritos_ahora = actual.get("inscritos_ids", [])
    restantes = [uid for uid in inscritos_ahora if uid not in set(quitar_ids)]
    if len(restantes) < 2:
        return False, "Quedan menos de 2 jugadores. No se puede iniciar el torneo."
    cambios = {"estado": "en desarrollo"}
    if quitar_ids:
        cambios["inscritos_ids"] = restantes
    await actualizar_torneo_estado(bot, codigo, cambios)
    ok, msg = await generar_ronda(bot, codigo)
    if not ok:
        await actualizar_torneo_estado(bot, codigo, {"estado": "abierto", "inscritos_ids": inscritos_ahora})
    return ok, msg


@_con_lock_torneo
async def reiniciar_torneo(bot, codigo: str, guild: discord.Guild = None):
    """Borra rondas y clasificación (mantiene los inscritos), lo deja abierto y quita sus mensajes de Discord."""
    await actualizar_torneo_estado(bot, codigo, {"ronda_actual": 0, "estado": "abierto"})
    await _guardar_lista_rondas(bot, codigo, [])
    await guardar_clasificacion(bot, codigo, {"codigo": codigo, "clasificacion": []})
    if guild:
        await presentacion.borrar_emparejamientos(bot, guild, codigo, todos=True)
        await presentacion.borrar_clasificacion(bot, guild, codigo)


@_con_lock_torneo
async def finalizar_torneo(bot, codigo: str, guild: discord.Guild = None):
    """Marca el torneo como finalizado y publica la clasificación final."""
    await actualizar_torneo_estado(bot, codigo, {"estado": "finalizado"})
    await publicar_clasificacion_swiss(bot, guild, codigo)

# ============================================================
# INSCRIPCIONES
# ============================================================

@_con_lock_torneo
async def inscribir_jugador(bot, codigo: str, usuario_id: int, miembro=None, forzar: bool = False) -> Tuple[bool, str]:
    """
    Inscribe en un torneo suizo abierto. Si el torneo es de nivel "socios", `miembro` debe tener un rol
    de config.ROLES_SOCIOS; `forzar=True` (un admin inscribiendo a otra persona) permite saltarse el nivel.
    """
    torneo = await obtener_torneo(bot, codigo)
    roles = [r.name for r in getattr(miembro, "roles", [])]
    error = engine.error_inscripcion(torneo, usuario_id, roles, config.ROLES_SOCIOS, forzar)
    if error:
        return False, error
    await actualizar_torneo_estado(bot, codigo, {"inscritos_ids": torneo.get("inscritos_ids", []) + [str(usuario_id)]})
    return True, "Inscripción completada."


@_con_lock_torneo
async def desinscribir_jugador(bot, codigo: str, usuario_id: int, guild: discord.Guild = None) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."
    if torneo.get("estado", "abierto") != "abierto":
        return False, "El torneo ya ha empezado o ha terminado; no puedes desinscribirte. Habla con un admin."

    inscritos = torneo.get("inscritos_ids", [])
    if str(usuario_id) not in inscritos:
        return False, "No estás inscrito en este torneo."

    inscritos.remove(str(usuario_id))
    await actualizar_torneo_estado(bot, codigo, {"inscritos_ids": inscritos})

    # 🔹 Eliminar su deck de #submitted-decks (coincidencia EXACTA del código: no toca decks de otros)
    from utils.commons import obtener_deck_en_canal  # import local: evita ciclos al cargar
    if guild is None:
        guild = bot.get_guild(config.GUILD_ID_ADMISION)
    if not guild:
        return True, "Desinscripción completada, pero no se pudo eliminar el deck (servidor no encontrado)."

    deck = await obtener_deck_en_canal(guild, f"{codigo}_{usuario_id}")
    if deck and deck.get("mensaje"):
        try:
            await deck["mensaje"].delete()
            return True, f"Desinscripción completada. Se ha eliminado tu deck `{deck.get('nombre_deck', '')}`."
        except discord.HTTPException as e:
            log.warning(f"⚠️ No se pudo eliminar el deck {codigo}_{usuario_id}: {e}")
            return True, "Desinscripción completada, pero no se pudo eliminar tu deck. Avisa a un admin."

    return True, "Desinscripción completada."

# ============================================================
# RONDAS
# ============================================================

@_con_lock_torneo
async def generar_ronda(bot, codigo: str) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."
    rondas = await _leer_lista_rondas(bot, codigo)
    error = engine.error_nueva_ronda(torneo, rondas)
    if error:
        return False, error

    ronda = engine.nueva_ronda(codigo, torneo, rondas)
    await _guardar_lista_rondas(bot, codigo, rondas + [ronda])
    await actualizar_torneo_estado(bot, codigo, {"ronda_actual": ronda["numero"]})
    return True, f"Ronda {ronda['numero']} generada con {len(ronda['emparejamientos'])} emparejamientos."


@_con_lock_torneo
async def _siguiente_ronda_automatica(bot, codigo: str, guild: discord.Guild = None):
    """Tras completarse una ronda: genera y publica la siguiente o, si no hay más, finaliza el torneo."""
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return

    rondas_totales = engine.rondas_necesarias(len(torneo.get("inscritos_ids", [])))
    if torneo.get("ronda_actual", 0) >= rondas_totales:
        motivo = f"se completaron las {rondas_totales} rondas necesarias"
        ok = False
    else:
        ok, _ = await generar_ronda(bot, codigo)
        motivo = "no se pudo generar más rondas"

    if not ok:
        await actualizar_torneo_estado(bot, codigo, {"estado": "finalizado"})
        if guild:
            await presentacion.anunciar_fin_automatico(guild, codigo, motivo)
        await publicar_clasificacion_swiss(bot, guild, codigo)
        return

    if guild:
        await presentacion.borrar_emparejamientos(bot, guild, codigo)     # el de la ronda anterior
        await publicar_emparejamientos(bot, guild, codigo)
    await publicar_clasificacion_swiss(bot, guild, codigo)


@_con_lock_torneo
async def eliminar_ronda_swiss(bot, codigo: str, ronda_num: int, guild: discord.Guild = None) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."
    if torneo.get("tipo") != "swiss":
        return False, "Este torneo no es suizo."

    rondas = await _leer_lista_rondas(bot, codigo)
    if not rondas:
        return False, "El torneo no tiene rondas."
    if not any(r.get("numero") == ronda_num for r in rondas):
        return False, f"La ronda {ronda_num} no existe."

    # Solo la última: borrar una intermedia dejaría las posteriores emparejadas con datos
    # que ya no existen y rompería la numeración
    if rondas[-1].get("numero") != ronda_num:
        return False, (
            f"Solo se puede eliminar la última ronda (Ronda {rondas[-1].get('numero')}). "
            f"Para corregir una anterior usa `!modificar-resultado-swiss`."
        )

    rondas.pop()

    # El torneo vuelve a la ronda anterior y, si estaba finalizado, se reabre para poder continuar
    cambios = {"ronda_actual": rondas[-1]["numero"] if rondas else 0}
    if torneo.get("estado") == "finalizado":
        cambios["estado"] = "en desarrollo"
    await actualizar_torneo_estado(bot, codigo, cambios)
    await _guardar_lista_rondas(bot, codigo, rondas)

    await publicar_clasificacion_swiss(bot, guild, codigo)
    if guild:
        await presentacion.borrar_emparejamientos(bot, guild, codigo, ronda_num)

    reabierto = " El torneo estaba finalizado y se ha reabierto." if "estado" in cambios else ""
    return True, f"Ronda {ronda_num} eliminada correctamente.{reabierto}"

# ============================================================
# RESULTADOS
# ============================================================

@_con_lock_torneo
async def reportar_resultado(bot, codigo: str, jugador1_id: int, resultado: str, jugador2_id: int,
                             guild: discord.Guild = None, publicar: bool = True) -> Tuple[bool, str, dict, int]:
    """
    Registra un resultado de la ronda actual. Es el único responsable de publicar la clasificación tras reportar:
    si se completa la ronda lo hace _siguiente_ronda_automatica; si no, se publica aquí
    (publicar=False lo evita, p. ej. al cerrar varias partidas seguidas).
    """
    # Última barrera: ningún camino (Discord, web, abandonos) puede guardar un resultado inválido
    try:
        resultado = validar_resultado(resultado)
    except EntradaInvalida as e:
        return False, e.mensaje, None, -1

    if not await obtener_torneo(bot, codigo):
        return False, "El torneo no existe.", None, -1
    rondas = await _leer_lista_rondas(bot, codigo)
    if not rondas:
        return False, "El torneo no tiene rondas generadas.", None, -1

    ok, msg, emp, idx = engine.registrar_resultado(rondas[-1], jugador1_id, resultado, jugador2_id)
    if not ok:
        return False, msg, None, -1
    await _guardar_lista_rondas(bot, codigo, rondas)

    if rondas[-1]["completa"]:
        await _siguiente_ronda_automatica(bot, codigo, guild)
        return True, "Resultado reportado y ronda completada. Siguiente ronda generada o torneo finalizado.", emp, idx

    if guild and publicar:
        await publicar_clasificacion_swiss(bot, guild, codigo)
    return True, msg, emp, idx


@_con_lock_torneo
async def modificar_resultado(bot, codigo: str, ronda_num: int, j1: str, j2: str, resultado: str,
                              guild: discord.Guild = None) -> Tuple[bool, str]:
    """
    Corrige el resultado de una partida ya jugada (j1/j2 en el orden guardado). Se aplica sobre las rondas
    ACTUALES: guardar las leídas al empezar el asistente borraría lo reportado entretanto. Los emparejamientos
    posteriores no se rehacen; la clasificación sí se recalcula y republica.
    """
    try:
        resultado = validar_resultado(resultado)
    except EntradaInvalida as e:
        return False, e.mensaje
    rondas = await _leer_lista_rondas(bot, codigo)
    ronda = next((r for r in rondas if r.get("numero") == ronda_num), None)
    emp = next((e for e in (ronda or {}).get("emparejamientos", []) if e.get("j1") == j1 and e.get("j2") == j2), None)
    if not emp:
        return False, "Ese partido ya no existe (¿se ha eliminado la ronda?). No se ha modificado nada."
    emp["resultado"] = resultado
    await _guardar_lista_rondas(bot, codigo, rondas)
    await publicar_clasificacion_swiss(bot, guild, codigo)
    return True, f"Resultado modificado a **{resultado}** correctamente."

# ============================================================
# RETIRADA POR ABANDONO (el jugador sale del servidor)
# ============================================================

@_con_lock_torneo
async def retirar_por_abandono(bot, codigo: str, usuario_id, guild: discord.Guild = None) -> Tuple[bool, str, Optional[str]]:
    """
    Retira a un jugador que ha dejado el servidor.
      - Torneo abierto: se le desinscribe (y se borra su deck).
      - Torneo en desarrollo: queda como "retirado" (conserva resultados, no se le empareja más)
        y su partida pendiente de la ronda actual se da como victoria 2-0 a su rival.
    Devuelve (ok, mensaje, id_del_rival_beneficiado o None).
    """
    torneo = await obtener_torneo(bot, codigo)
    uid = str(usuario_id)
    if not torneo or torneo.get("tipo") != "swiss" or uid not in torneo.get("inscritos_ids", []):
        return False, "No está inscrito en este torneo suizo.", None

    estado = torneo.get("estado", "abierto")
    if estado == "abierto":
        ok, msg = await desinscribir_jugador(bot, codigo, usuario_id, guild)
        return ok, msg, None
    if estado == "finalizado":
        return False, "El torneo ya ha finalizado; no se modifica.", None

    retirados = list(torneo.get("retirados", []))
    if uid not in retirados:
        retirados.append(uid)
        await actualizar_torneo_estado(bot, codigo, {"retirados": retirados})

    rondas = await _leer_lista_rondas(bot, codigo)
    emp = engine.partida_pendiente_de(rondas[-1] if rondas else None, uid)
    if emp is None:
        return True, "Retirado. No tenía partidas pendientes en la ronda actual.", None

    rival = emp["j2"] if emp.get("j1") == uid else emp.get("j1")
    # Si el rival también se ha retirado, la partida queda en empate
    resultado = "1-1" if rival in retirados else "2-0"
    ok, msg, _, _ = await reportar_resultado(bot, codigo, rival, resultado, uid, guild)
    if not ok:
        return True, f"Retirado, pero no se pudo cerrar su partida pendiente: {msg}", None
    if resultado == "2-0":
        return True, f"Retirado. Su partida pendiente se da como victoria 2-0 para <@{rival}>.", rival
    return True, "Retirado. Su partida pendiente queda en empate (el rival también se retiró).", None
