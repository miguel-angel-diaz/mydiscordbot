import discord
import asyncio
import functools
import hashlib
import math
import random
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict
import config

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
from utils.commons import cabecera_emparejamientos, es_mensaje_emparejamientos

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
    Lock de un torneo para leer-modificar-escribir su estado y sus rondas. Las operaciones de este módulo ya lo
    toman; los asistentes lo usan SOLO en el tramo final de escritura (nunca mientras esperan una respuesta por DM).
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

# ============================================================
# GESTIÓN DE TORNEOS
# ============================================================

async def crear_torneo(bot, nombre: str, formato: str, max_jugadores: int, nivel: str, fecha_inicio: str) -> str:
    nivel_slug = slugify_challonge(nivel)
    formato_slug = slugify_challonge(formato)
    codigo = f"{formato_slug}{nivel_slug}{generar_codigo_unico(6)}"

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

    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": []})
    await guardar_clasificacion(bot, codigo, {"codigo": codigo, "clasificacion": []})

    return codigo

async def eliminar_torneo_swiss(bot, codigo: str) -> bool:
    await eliminar_torneo_estado(bot, codigo)
    return True

async def obtener_torneos_activos(bot) -> List[Dict]:
    estado = await leer_estado(bot)
    torneos = estado.get("torneos", []) if isinstance(estado, dict) else []
    return [t for t in torneos if t.get("tipo") == "swiss"]

async def obtener_torneo(bot, codigo: str) -> Optional[Dict]:
    return await obtener_torneo_estado(bot, codigo)

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
    if not torneo:
        return False, "El torneo no existe."
    if torneo.get("tipo") != "swiss":
        return False, "Este torneo no es suizo."
    if torneo.get("estado", "abierto") != "abierto":
        return False, "Las inscripciones de este torneo están cerradas."
    if not forzar and str(torneo.get("nivel", "todos")).lower() == "socios":
        roles = {r.name.lower() for r in getattr(miembro, "roles", [])}
        if not roles & {r.lower() for r in config.ROLES_SOCIOS}:
            return False, "Este torneo es solo para socios."

    inscritos = torneo.get("inscritos_ids", [])
    if str(usuario_id) in inscritos:
        return False, "Ya estás inscrito."

    maximo = torneo.get("total_maximo")
    if maximo and len(inscritos) >= maximo:
        return False, "No quedan plazas disponibles."

    inscritos.append(str(usuario_id))
    await actualizar_torneo_estado(bot, codigo, {"inscritos_ids": inscritos})
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
            print(f"⚠️ No se pudo eliminar el deck {codigo}_{usuario_id}: {e}")
            return True, "Desinscripción completada, pero no se pudo eliminar tu deck. Avisa a un admin."

    return True, "Desinscripción completada."

# ============================================================
# CÁLCULO DE RONDAS NECESARIAS (POTENCIA DE 2)
# ============================================================

def rondas_necesarias(num_jugadores: int) -> int:
    """Devuelve el número mínimo de rondas para un torneo suizo con N jugadores."""
    if num_jugadores <= 1:
        return 0
    return math.ceil(math.log2(num_jugadores))

# ============================================================
# GENERAR RONDA (CON LÍMITE DE INTENTOS)
# ============================================================

@_con_lock_torneo
async def generar_ronda(bot, codigo: str) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    if torneo.get("estado") == "finalizado":
        return False, "El torneo ya ha finalizado."

    inscritos = torneo.get("inscritos_ids", [])
    # Los retirados (p. ej. salieron del servidor) conservan sus resultados pero no se emparejan más
    retirados = set(torneo.get("retirados", []))
    participantes = [p for p in inscritos if p not in retirados]
    if len(participantes) < 2:
        return False, "Se necesitan al menos 2 jugadores."

    rondas_data = await leer_rondas(bot, codigo)
    rondas = rondas_data.get("rondas", []) if rondas_data else []

    # No se genera una ronda nueva dejando partidas sin resultado en la anterior
    if rondas:
        pendientes = sum(1 for e in rondas[-1].get("emparejamientos", []) if e.get("resultado") is None)
        if pendientes:
            return False, f"La ronda {rondas[-1].get('numero')} tiene {pendientes} partida(s) sin resultado."

    total = rondas_necesarias(len(inscritos))
    if torneo.get("ronda_actual", 0) >= total:
        return False, f"Ya se han jugado las {total} rondas del torneo. Usa `!finalizar-swiss`."

    stats = await _calcular_stats_completos(bot, codigo, inscritos, rondas)
    if not rondas:
        random.shuffle(participantes)
    historial = _cargar_historial_emparejamientos(rondas)
    jugadores_con_bye = _jugadores_con_bye(rondas)

    # Orden de emparejamiento: clasificación actual (en la ronda 1, el orden sorteado)
    if rondas:
        orden = sorted(
            participantes,
            key=lambda p: (-stats[p]["mp"], -stats[p]["omw"], -stats[p]["dif"], _desempate_final(codigo, p)),
        )
    else:
        orden = list(participantes)

    parejas, bye = _emparejar_ronda(orden, historial, jugadores_con_bye)
    emparejamientos: List[dict] = [{"j1": a, "j2": b, "resultado": None} for a, b in parejas]
    if bye:
        emparejamientos.append({"j1": bye, "j2": None, "resultado": "BYE"})

    # ============================================================
    # GUARDAR RONDA
    # ============================================================
    nueva_ronda = torneo.get("ronda_actual", 0) + 1
    ronda_data = {
        "numero": nueva_ronda,
        "emparejamientos": emparejamientos,
        "completa": False,
    }
    rondas.append(ronda_data)
    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": rondas})
    await actualizar_torneo_estado(bot, codigo, {"ronda_actual": nueva_ronda})

    return True, f"Ronda {nueva_ronda} generada con {len(emparejamientos)} emparejamientos."

# ============================================================
# CALCULAR ESTADÍSTICAS
# ============================================================

MWP_MINIMO = 1 / 3   # MTR (Apéndice C): el % de victorias de cada rival se cuenta como mínimo 33 %


def calcular_estadisticas(rondas: List[dict], jugadores: List[str]) -> Dict[str, dict]:
    """
    Única fuente de estadísticas del suizo (emparejamientos y clasificación usan esta función).
      - mp: 3 por victoria o BYE, 1 por empate.
      - mwp: mp / (3 · rondas jugadas, BYE incluido), con mínimo del 33 %.
      - omw: media del mwp de los rivales (el BYE no cuenta como rival). Siempre entre 0,33 y 1.
      - bch: media recortada (sin el mejor ni el peor) del mwp de los rivales.
      - dif: juegos ganados - juegos perdidos.
    Un jugador que aparece en las rondas pero no en `jugadores` se crea igualmente (sin KeyError).
    """
    stats = defaultdict(lambda: {"mp": 0.0, "w": 0, "l": 0, "dw": 0, "rondas": 0, "opponents": [],
                                 "games_won": 0, "games_played": 0, "mwp": MWP_MINIMO,
                                 "omw": 0.0, "bch": 0.0, "dif": 0})
    for pid in jugadores:
        stats[pid]

    for ronda in rondas:
        for emp in ronda.get("emparejamientos", []):
            j1, j2, res = emp.get("j1"), emp.get("j2"), emp.get("resultado")
            if res is None or j1 is None:
                continue
            if res == "BYE" or j2 is None:
                stats[j1]["mp"] += 3.0
                stats[j1]["w"] += 1
                stats[j1]["rondas"] += 1
                continue
            try:
                s1, s2 = map(int, res.split("-"))
            except (ValueError, AttributeError):
                continue
            a, b = stats[j1], stats[j2]
            a["opponents"].append(j2)
            b["opponents"].append(j1)
            a["rondas"] += 1
            b["rondas"] += 1
            a["games_won"] += s1
            b["games_won"] += s2
            a["games_played"] += s1 + s2
            b["games_played"] += s1 + s2
            if s1 > s2:
                a["mp"] += 3.0; a["w"] += 1; b["l"] += 1
            elif s2 > s1:
                b["mp"] += 3.0; b["w"] += 1; a["l"] += 1
            else:
                a["mp"] += 1.0; b["mp"] += 1.0; a["dw"] += 1; b["dw"] += 1

    for data in stats.values():
        if data["rondas"]:
            data["mwp"] = max(MWP_MINIMO, data["mp"] / (3 * data["rondas"]))
        data["dif"] = data["games_won"] - (data["games_played"] - data["games_won"])

    for data in stats.values():
        mwps = [stats[o]["mwp"] for o in data["opponents"]]
        data["omw"] = sum(mwps) / len(mwps) if mwps else 0.0
        recortados = sorted(mwps)[1:-1] if len(mwps) > 2 else mwps
        data["bch"] = sum(recortados) / len(recortados) if recortados else 0.0

    return dict(stats)


def _desempate_final(codigo: str, pid: str) -> str:
    """Orden pseudoaleatorio fijo por torneo: reproducible y sin favorecer IDs antiguos o nuevos."""
    return hashlib.sha256(f"{codigo}:{pid}".encode()).hexdigest()


async def _calcular_stats_completos(bot, codigo: str, participantes: List[str], rondas: List[dict]) -> dict:
    return calcular_estadisticas(rondas, participantes)


# ============================================================
# REPORTAR RESULTADO
# ============================================================

@_con_lock_torneo
async def reportar_resultado(bot, codigo: str, jugador1_id: int, resultado: str, jugador2_id: int,
                             guild: discord.Guild = None, publicar: bool = True) -> Tuple[bool, str, dict, int]:
    """
    Registra un resultado. Es el único responsable de publicar la clasificación tras reportar:
    si se completa la ronda lo hace _siguiente_ronda_automatica; si no, se publica aquí
    (publicar=False lo evita, p. ej. al cerrar varias partidas seguidas).
    """
    # Última barrera: ningún camino (Discord, web, abandonos) puede guardar un resultado inválido
    try:
        resultado = validar_resultado(resultado)
    except EntradaInvalida as e:
        return False, e.mensaje, None, -1

    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe.", None, -1

    rondas_data = await leer_rondas(bot, codigo)
    if not rondas_data:
        return False, "El torneo no tiene rondas generadas.", None, -1

    rondas = rondas_data.get("rondas", [])
    if not rondas:
        return False, "El torneo no tiene rondas generadas.", None, -1

    ronda_actual = rondas[-1]
    if ronda_actual.get("completa", False):
        return False, "La ronda actual ya está completa.", None, -1

    emp_index = -1
    emp_encontrado = None
    resultado_normalizado = resultado
    for i, emp in enumerate(ronda_actual["emparejamientos"]):
        if emp["j1"] == str(jugador1_id) and emp["j2"] == str(jugador2_id):
            # Orden correcto: j1 = jugador1, j2 = jugador2
            emp_index = i
            emp_encontrado = emp
            resultado_normalizado = resultado
            break
        elif emp["j1"] == str(jugador2_id) and emp["j2"] == str(jugador1_id):
            # Orden inverso: hay que invertir el resultado
            emp_index = i
            emp_encontrado = emp
            try:
                s1, s2 = resultado.split("-")
                resultado_normalizado = f"{s2}-{s1}"
            except Exception:
                resultado_normalizado = resultado
            break

    if not emp_encontrado:
        return False, "Ese partido no existe en la ronda actual.", None, -1

    if emp_encontrado.get("resultado") is not None:
        return False, "Este partido ya tiene un resultado reportado.", None, -1

    emp_encontrado["resultado"] = resultado_normalizado

    todos_reportados = all(e.get("resultado") is not None for e in ronda_actual["emparejamientos"])
    if todos_reportados:
        ronda_actual["completa"] = True

    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": rondas})

    if todos_reportados:
        await _siguiente_ronda_automatica(bot, codigo, guild)
        return True, "Resultado reportado y ronda completada. Siguiente ronda generada o torneo finalizado.", emp_encontrado, emp_index

    if guild and publicar:
        await publicar_clasificacion_swiss(bot, guild, codigo)
    return True, "Resultado reportado.", emp_encontrado, emp_index

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

    rondas_data = await leer_rondas(bot, codigo)
    rondas = rondas_data.get("rondas", []) if rondas_data else []
    if rondas and not rondas[-1].get("completa", False):
        for emp in rondas[-1].get("emparejamientos", []):
            if emp.get("resultado") is not None or uid not in (emp.get("j1"), emp.get("j2")):
                continue
            rival = emp["j2"] if emp.get("j1") == uid else emp.get("j1")
            if rival is None:
                continue
            # Si el rival también se ha retirado, la partida queda en empate
            resultado = "1-1" if rival in retirados else "2-0"
            ok, msg, _, _ = await reportar_resultado(bot, codigo, rival, resultado, uid, guild)
            if ok:
                if resultado == "2-0":
                    return True, f"Retirado. Su partida pendiente se da como victoria 2-0 para <@{rival}>.", rival
                return True, "Retirado. Su partida pendiente queda en empate (el rival también se retiró).", None
            return True, f"Retirado, pero no se pudo cerrar su partida pendiente: {msg}", None

    return True, "Retirado. No tenía partidas pendientes en la ronda actual.", None

# ============================================================
# SIGUIENTE RONDA AUTOMÁTICA (CON CÁLCULO DE RONDAS NECESARIAS)
# ============================================================

@_con_lock_torneo
async def _siguiente_ronda_automatica(bot, codigo: str, guild: discord.Guild = None):
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return

    ronda_actual = torneo.get("ronda_actual", 0)
    participantes = torneo.get("inscritos_ids", [])
    num_jugadores = len(participantes)

    # Calcular rondas necesarias
    rondas_totales = rondas_necesarias(num_jugadores)

    # Si ya se alcanzó el número de rondas requerido, finalizar
    if ronda_actual >= rondas_totales:
        await actualizar_torneo_estado(bot, codigo, {"estado": "finalizado"})
        if guild:
            canal_anuncios = discord.utils.get(guild.text_channels, name="📰-cartelera‐torneos")
            if canal_anuncios:
                await canal_anuncios.send(f"🏁 El torneo `{codigo}` ha finalizado automáticamente (se completaron las {rondas_totales} rondas necesarias).")
            await publicar_clasificacion_swiss(bot, guild, codigo)
        return

    # Intentar generar la siguiente ronda
    ok, msg = await generar_ronda(bot, codigo)
    if not ok:
        await actualizar_torneo_estado(bot, codigo, {"estado": "finalizado"})
        if guild:
            canal_anuncios = discord.utils.get(guild.text_channels, name="📰-cartelera‐torneos")
            if canal_anuncios:
                await canal_anuncios.send(f"🏁 El torneo `{codigo}` ha finalizado automáticamente (no se pudo generar más rondas).")
            await publicar_clasificacion_swiss(bot, guild, codigo)
        return

    # ============================================================
    # ELIMINAR MENSAJE DE CITAS DE LA RONDA ANTERIOR
    # ============================================================
    if guild:
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            async for msg in canal_citas.history(limit=100):
                if msg.author == bot.user and es_mensaje_emparejamientos(msg.content, codigo):
                    await msg.delete()
                    break

    # ============================================================
    # PUBLICAR NUEVOS EMPAREJAMIENTOS EN EL CANAL DE CITAS
    # ============================================================
    if guild:
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            rondas_data = await leer_rondas(bot, codigo)
            if rondas_data:
                rondas = rondas_data.get("rondas", [])
                if rondas:
                    ultima_ronda = rondas[-1]
                    mensaje_citas = cabecera_emparejamientos(codigo, ultima_ronda['numero']) + "\n"
                    for emp in ultima_ronda.get("emparejamientos", []):
                        j1 = emp["j1"]
                        j2 = emp["j2"]
                        if j2 is None:
                            mensaje_citas += f"<@{j1}> → BYE\n"
                        else:
                            mensaje_citas += f"<@{j1}> vs <@{j2}>\n"
                    await canal_citas.send(mensaje_citas)

    # Actualizar clasificación
    # publicar_clasificacion_swiss ya recalcula; sin guild solo se calcula y guarda
    if guild:
        await publicar_clasificacion_swiss(bot, guild, codigo)
    else:
        await calcular_clasificacion(bot, codigo)
# ============================================================
# CALCULAR CLASIFICACIÓN
# ============================================================

async def calcular_clasificacion(bot, codigo: str) -> List[Dict]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return []
    inscritos_ids = torneo.get("inscritos_ids", [])
    if not inscritos_ids:
        return []

    rondas_data = await leer_rondas(bot, codigo)
    rondas = rondas_data.get("rondas", []) if rondas_data else []
    stats = calcular_estadisticas(rondas, inscritos_ids)

    # Puntos, OMW%, diferencia de juegos, Buchholz y, si todo empata, un orden fijo por torneo
    ranking = sorted(
        stats.items(),
        key=lambda x: (-x[1]["mp"], -x[1]["omw"], -x[1]["dif"], -x[1]["bch"], _desempate_final(codigo, x[0])),
    )

    clasificacion = []
    for i, (pid, data) in enumerate(ranking, 1):
        clasificacion.append({
            "id": pid,
            "rk": i,
            "mp": data["mp"],
            "w": data["w"],
            "l": data["l"],
            "dw": data["dw"],
            "omw": data["omw"],
            "bch": data["bch"],
            "dif": data["dif"]
        })

    await guardar_clasificacion(bot, codigo, {"codigo": codigo, "clasificacion": clasificacion})
    return clasificacion

# ============================================================
# ELIMINAR RONDA
# ============================================================

@_con_lock_torneo
async def eliminar_ronda_swiss(bot, codigo: str, ronda_num: int, guild: discord.Guild = None) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    if torneo.get("tipo") != "swiss":
        return False, "Este torneo no es suizo."

    rondas_data = await leer_rondas(bot, codigo)
    if not rondas_data:
        return False, "El torneo no tiene rondas."

    rondas = rondas_data.get("rondas", [])
    idx = -1
    for i, r in enumerate(rondas):
        if r.get("numero") == ronda_num:
            idx = i
            break

    if idx == -1:
        return False, f"La ronda {ronda_num} no existe."

    # Solo la última: borrar una intermedia dejaría las posteriores emparejadas con datos
    # que ya no existen y rompería la numeración
    if idx != len(rondas) - 1:
        return False, (
            f"Solo se puede eliminar la última ronda (Ronda {rondas[-1].get('numero')}). "
            f"Para corregir una anterior usa `!modificar-resultado-swiss`."
        )

    rondas.pop(idx)

    # El torneo vuelve a la ronda anterior y, si estaba finalizado, se reabre para poder continuar
    cambios = {"ronda_actual": rondas[-1]["numero"] if rondas else 0}
    if torneo.get("estado") == "finalizado":
        cambios["estado"] = "en desarrollo"
    await actualizar_torneo_estado(bot, codigo, cambios)

    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": rondas})
    # publicar_clasificacion_swiss ya recalcula; sin guild solo se calcula y guarda
    if guild:
        await publicar_clasificacion_swiss(bot, guild, codigo)
    else:
        await calcular_clasificacion(bot, codigo)

    if guild:
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            async for msg in canal_citas.history(limit=200):
                if msg.author == bot.user and es_mensaje_emparejamientos(msg.content, codigo, ronda_num):
                    await msg.delete()
                    break

    reabierto = " El torneo estaba finalizado y se ha reabierto." if "estado" in cambios else ""
    return True, f"Ronda {ronda_num} eliminada correctamente.{reabierto}"

# ============================================================
# PUBLICAR CLASIFICACIÓN (sin dependencia de ctx)
# ============================================================

async def publicar_clasificacion_swiss(bot, guild, codigo: str):
    canal_ranking = discord.utils.get(guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return

    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return

    # Siempre se recalcula: así la clasificación publicada incluye la última ronda jugada
    clasificacion = await calcular_clasificacion(bot, codigo)

    lines = [f"📊 **Clasificación del torneo `{codigo}`:**"]
    lines.append("```markdown")
    lines.append(f"{'Rk':<3} | {'Participante':<22} | {'G-P-E':<5} | {'Pts':<3} | {'OMW%':<5} | {'Bch':<6} | {'Dif':<3}")
    lines.append("-" * 72)

    for p in clasificacion:
        try:
            member = guild.get_member(int(p["id"]))
            nombre = member.display_name if member else f"<@{p['id']}>"
        except:
            nombre = f"<@{p['id']}>"
        nombre_truncado = nombre[:22] if len(nombre) > 22 else nombre

        gpe = f"{p.get('w', 0)}-{p.get('l', 0)}-{p.get('dw', 0)}"
        mp = p.get('mp', 0)
        omw = p.get('omw', 0.0)
        bch = p.get('bch', 0.0)
        dif = p.get('dif', 0)

        line = f"{p['rk']:<3} | {nombre_truncado:<22} | {gpe:<5} | {mp:<3} | {omw:.3f}  | {bch:.5f}  | {dif:+}"
        lines.append(line)

    lines.append("```")
    mensaje_completo = "\n".join(lines)

    # Borrar TODOS los mensajes anteriores de este torneo (las clasificaciones largas van en varios trozos)
    async for msg in canal_ranking.history(limit=100):
        if msg.author == bot.user and not msg.embeds and msg.content.startswith(f"📊 **Clasificación del torneo `{codigo}`:**"):
            try:
                await msg.delete()
            except discord.HTTPException:
                pass

    if len(mensaje_completo) <= 1900:
        await canal_ranking.send(mensaje_completo)
    else:
        header_lines = lines[:3]
        player_lines = lines[3:-1]
        footer = "```"
        chunks = []
        for i in range(0, len(player_lines), 10):
            chunk_lines = header_lines + player_lines[i:i+10] + [footer]
            chunks.append("\n".join(chunk_lines))
        for chunk in chunks:
            await canal_ranking.send(chunk)

LIMITE_PASOS_EMPAREJAMIENTO = 200_000   # salvaguarda: con torneos normales sobra con creces


def _cargar_historial_emparejamientos(rondas: List[dict]) -> Dict[str, Dict[str, int]]:
    """Devuelve un diccionario {j1: {j2: veces}} con todos los enfrentamientos previos."""
    historial = defaultdict(lambda: defaultdict(int))
    for ronda in rondas:
        for emp in ronda.get("emparejamientos", []):
            j1, j2 = emp.get("j1"), emp.get("j2")
            if j1 is not None and j2 is not None:
                historial[j1][j2] += 1
                historial[j2][j1] += 1
    return historial


def _jugadores_con_bye(rondas: List[dict]) -> Set[str]:
    """Devuelve el conjunto de IDs de jugadores que ya han tenido un BYE."""
    byes = set()
    for ronda in rondas:
        for emp in ronda.get("emparejamientos", []):
            if emp.get("j2") is None and emp.get("j1") is not None:
                byes.add(emp["j1"])
    return byes


def _emparejar(orden: List[str], historial, permitir_revanchas: bool) -> Optional[List[Tuple[str, str]]]:
    """
    Empareja a todos (número par) respetando el orden de clasificación: el primero libre juega
    contra el más cercano posible; si eso deja a alguien sin rival, se retrocede (backtracking).
    Sin revanchas devuelve None si no existe solución; con revanchas, prefiere las menos repetidas.
    """
    fallidos = set()
    pasos = [0]

    def buscar(restantes: Tuple[str, ...]):
        if not restantes:
            return []
        if restantes in fallidos or pasos[0] > LIMITE_PASOS_EMPAREJAMIENTO:
            return None
        pasos[0] += 1
        a = restantes[0]
        candidatos = list(restantes[1:])
        if permitir_revanchas:
            candidatos.sort(key=lambda b: historial[a][b])   # estable: a igual nº de cruces, el más cercano
        for b in candidatos:
            if not permitir_revanchas and historial[a][b]:
                continue
            sub = buscar(tuple(x for x in restantes if x != a and x != b))
            if sub is not None:
                return [(a, b)] + sub
        fallidos.add(restantes)
        return None

    return buscar(tuple(orden))


def _emparejar_ronda(orden: List[str], historial, jugadores_con_bye: Set[str]):
    """
    Emparejamiento de una ronda (MTR). Prioridades, de mayor a menor:
      1. Con número impar, el BYE va a quien aún no lo haya tenido (el peor clasificado posible).
      2. Sin revanchas: se prueba cada candidato a BYE hasta que el resto se pueda emparejar sin ellas.
      3. Revanchas solo si no hay otro reparto; un BYE repetido solo si todos lo han tenido ya.
    Devuelve (parejas, id_con_bye o None).
    """
    if len(orden) % 2 == 0:
        grupos_bye = [[None]]
    else:
        sin_bye = [p for p in reversed(orden) if p not in jugadores_con_bye]
        con_bye = [p for p in reversed(orden) if p in jugadores_con_bye]
        # No repetir BYE tiene prioridad sobre evitar revanchas (el BYE son 3 puntos gratis)
        grupos_bye = [g for g in (sin_bye, con_bye) if g]

    for candidatos_bye in grupos_bye:
        for permitir_revanchas in (False, True):
            for bye in candidatos_bye:
                resto = [p for p in orden if p != bye]
                parejas = _emparejar(resto, historial, permitir_revanchas)
                if parejas is not None:
                    return parejas, bye

    # Salvaguarda (no debería ocurrir): parejas consecutivas
    bye = grupos_bye[0][0]
    resto = [p for p in orden if p != bye]
    return [(resto[i], resto[i + 1]) for i in range(0, len(resto) - 1, 2)], bye
