# utils/swiss_core.py
import discord
import random
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from utils.torneos_estado import (
    actualizar_torneo_estado,
    eliminar_torneo_estado,
    obtener_torneo_estado,
    leer_rondas,
    guardar_rondas,
    leer_clasificacion,
    guardar_clasificacion,
    leer_estado,              # <--- AÑADIDO
    slugify_challonge,
    generar_codigo_unico
)

# ============================================================
# GESTIÓN DE TORNEOS
# ============================================================

async def crear_torneo(bot, nombre: str, max_jugadores: int, nivel: str, fecha_inicio: str) -> str:
    nivel_slug = slugify_challonge(nivel)
    codigo = f"premodern{nivel_slug}{generar_codigo_unico(6)}"

    await actualizar_torneo_estado(bot, codigo, {
        "nombre": nombre,
        "nivel": nivel,
        "total_maximo": int(max_jugadores),
        "tipo": "swiss",
        "fecha_inicio": fecha_inicio,
        "estado": "abierto",
        "ronda_actual": 0,
        "inscritos_ids": []
    })

    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": []})
    await guardar_clasificacion(bot, codigo, {"codigo": codigo, "clasificacion": []})

    return codigo

async def eliminar_torneo_swiss(bot, codigo: str) -> bool:
    await eliminar_torneo_estado(bot, codigo)
    return True

async def obtener_torneos_activos(bot) -> List[Dict]:
    """Devuelve todos los torneos de tipo swiss (sin filtrar por estado)."""
    torneos = await leer_estado(bot)  # Devuelve lista
    return [t for t in torneos if t.get("tipo") == "swiss"]

async def obtener_torneo(bot, codigo: str) -> Optional[Dict]:
    return await obtener_torneo_estado(bot, codigo)

# ============================================================
# INSCRIPCIONES
# ============================================================

async def inscribir_jugador(bot, codigo: str, usuario_id: int) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."
    if torneo.get("tipo") != "swiss":
        return False, "Este torneo no es suizo."

    inscritos = torneo.get("inscritos_ids", [])
    if str(usuario_id) in inscritos:
        return False, "Ya estás inscrito."

    maximo = torneo.get("total_maximo")
    if maximo and len(inscritos) >= maximo:
        return False, "No quedan plazas disponibles."

    inscritos.append(str(usuario_id))
    await actualizar_torneo_estado(bot, codigo, {"inscritos_ids": inscritos})
    return True, "Inscripción completada."

async def desinscribir_jugador(bot, codigo: str, usuario_id: int) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    inscritos = torneo.get("inscritos_ids", [])
    if str(usuario_id) not in inscritos:
        return False, "No estás inscrito en este torneo."

    inscritos.remove(str(usuario_id))
    await actualizar_torneo_estado(bot, codigo, {"inscritos_ids": inscritos})
    return True, "Desinscripción completada."

# ============================================================
# ALGORITMO SWISS ESTÁNDAR (MAGIC: THE GATHERING)
# ============================================================

async def generar_ronda(bot, codigo: str) -> Tuple[bool, str]:
    """
    Genera la siguiente ronda usando el método Swiss estándar por grupos de puntos.
    - Empareja dentro del mismo grupo de puntos (o el más cercano).
    - Solo un BYE por ronda (al jugador con menor puntuación si el número es impar).
    - Evita repeticiones de enfrentamientos.
    """
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    participantes = torneo.get("inscritos_ids", [])
    if len(participantes) < 2:
        return False, "Se necesitan al menos 2 jugadores."

    # Leer rondas anteriores
    rondas_data = await leer_rondas(bot, codigo)
    rondas = rondas_data.get("rondas", []) if rondas_data else []

    # Calcular estadísticas
    stats = await _calcular_stats_completos(bot, codigo, participantes, rondas)

    # Ordenar por puntos (desc) y OMW (desc) para tener un orden consistente
    ordenados = sorted(
        participantes,
        key=lambda pid: (-stats[pid]["mp"], -stats[pid]["omw"])
    )

    historial = _cargar_historial_emparejamientos(rondas)
    usados = set()
    emparejamientos = []

    # ---- Algoritmo por grupos de puntos ----
    # Agrupar por puntos
    grupos = {}
    for pid in ordenados:
        mp = stats[pid]["mp"]
        grupos.setdefault(mp, []).append(pid)

    # Lista para almacenar jugadores sin emparejar (arrastre)
    sin_emparejar = []

    # Procesar grupos de mayor a menor puntos
    for mp in sorted(grupos.keys(), reverse=True):
        grupo = grupos[mp]
        # Añadir jugadores que vinieron en arrastre de grupos superiores
        if sin_emparejar:
            grupo = sin_emparejar + grupo
            sin_emparejar = []

        # Ordenar dentro del grupo por OMW (desc) y luego por diferencia (opcional)
        grupo.sort(key=lambda pid: (-stats[pid]["omw"], -stats[pid].get("dif", 0)))

        # Emparejar dentro del grupo
        i = 0
        while i < len(grupo):
            if i + 1 < len(grupo):
                j1 = grupo[i]
                j2 = grupo[i+1]
                # Verificar que no se hayan enfrentado antes
                if historial.get(j1, {}).get(j2, 0) == 0:
                    emparejamientos.append({"j1": j1, "j2": j2, "resultado": None})
                    usados.add(j1)
                    usados.add(j2)
                    i += 2
                else:
                    # Si ya se enfrentaron, intentar intercambiar con el siguiente
                    # Movemos j2 al final y reintentamos
                    grupo.append(grupo.pop(i+1))
                    # No avanzamos i, para volver a intentar con el mismo j1
            else:
                # Jugador sin pareja en este grupo → se arrastra al siguiente grupo
                sin_emparejar.append(grupo[i])
                i += 1

    # Después de todos los grupos, puede quedar un arrastre (normalmente 0 o 1 jugador)
    if sin_emparejar:
        # Si hay más de uno, emparejarlos entre sí (caso raro)
        while len(sin_emparejar) >= 2:
            j1 = sin_emparejar.pop(0)
            j2 = sin_emparejar.pop(0)
            # Si ya jugaron, igual los emparejamos (mejor que BYE)
            emparejamientos.append({"j1": j1, "j2": j2, "resultado": None})
            usados.add(j1)
            usados.add(j2)
        # Si queda uno, es el BYE
        if sin_emparejar:
            bye_player = sin_emparejar[0]
            emparejamientos.append({"j1": bye_player, "j2": None, "resultado": "BYE"})
            usados.add(bye_player)

    # Por si algún jugador quedó sin usar (por error), asignar BYE
    for pid in participantes:
        if pid not in usados:
            emparejamientos.append({"j1": pid, "j2": None, "resultado": "BYE"})
            usados.add(pid)

    # Guardar la ronda
    nueva_ronda = torneo.get("ronda_actual", 0) + 1
    ronda_data = {
        "numero": nueva_ronda,
        "emparejamientos": emparejamientos,
        "completa": False
    }
    rondas.append(ronda_data)
    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": rondas})
    await actualizar_torneo_estado(bot, codigo, {"ronda_actual": nueva_ronda})

    return True, f"Ronda {nueva_ronda} generada con {len(emparejamientos)} emparejamientos."
# ============================================================
# FUNCIONES AUXILIARES PARA CÁLCULO DE ESTADÍSTICAS
# ============================================================

async def _calcular_stats_completos(bot, codigo: str, participantes: List[str], rondas: List[dict]) -> dict:
    """
    Calcula puntos, OMW y diferencia de juegos para cada participante.
    """
    stats = {pid: {"mp": 0.0, "omw": 0.0, "opponents": [], "games_won": 0, "games_played": 0} for pid in participantes}

    for ronda in rondas:
        for emp in ronda.get("emparejamientos", []):
            if emp.get("resultado") == "BYE":
                stats[emp["j1"]]["mp"] += 3.0
                continue
            if emp.get("resultado") is None:
                continue
            j1 = emp["j1"]
            j2 = emp["j2"]
            res = emp["resultado"]
            try:
                s1, s2 = map(int, res.split("-"))
            except:
                continue
            stats[j1]["opponents"].append(j2)
            stats[j2]["opponents"].append(j1)
            stats[j1]["games_won"] += s1
            stats[j1]["games_played"] += s1 + s2
            stats[j2]["games_won"] += s2
            stats[j2]["games_played"] += s1 + s2
            if s1 > s2:
                stats[j1]["mp"] += 3.0
            elif s2 > s1:
                stats[j2]["mp"] += 3.0
            else:
                stats[j1]["mp"] += 1.0
                stats[j2]["mp"] += 1.0

    # Calcular OMW y añadir "dif"
    for pid, data in stats.items():
        if not data["opponents"]:
            data["omw"] = 0.0
        else:
            total_omw = 0.0
            for opp in data["opponents"]:
                opp_data = stats.get(opp)
                if opp_data:
                    opp_matches = len(opp_data["opponents"])
                    if opp_matches > 0:
                        total_omw += opp_data["mp"] / (opp_matches * 3)
            data["omw"] = total_omw / len(data["opponents"])
        data["dif"] = data["games_won"] - (data["games_played"] - data["games_won"])
    return stats
def _cargar_historial_emparejamientos(rondas: List[dict]) -> Dict[str, Dict[str, int]]:
    historial = defaultdict(lambda: defaultdict(int))
    for ronda in rondas:
        for emp in ronda.get("emparejamientos", []):
            j1 = emp["j1"]
            j2 = emp["j2"]
            if j2 is not None:
                historial[j1][j2] += 1
                historial[j2][j1] += 1
    return historial

# ============================================================
# REPORTE DE RESULTADOS
# ============================================================

async def reportar_resultado(bot, codigo: str, jugador1_id: int, resultado: str, jugador2_id: int, guild: discord.Guild = None) -> Tuple[bool, str, dict, int]:
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
    for i, emp in enumerate(ronda_actual["emparejamientos"]):
        if (emp["j1"] == str(jugador1_id) and emp["j2"] == str(jugador2_id)) or \
           (emp["j1"] == str(jugador2_id) and emp["j2"] == str(jugador1_id)):
            emp_index = i
            emp_encontrado = emp
            break

    if not emp_encontrado:
        return False, "Ese partido no existe en la ronda actual.", None, -1

    if emp_encontrado.get("resultado") is not None:
        return False, "Este partido ya tiene un resultado reportado.", None, -1

    emp_encontrado["resultado"] = resultado

    todos_reportados = all(e.get("resultado") is not None for e in ronda_actual["emparejamientos"])
    if todos_reportados:
        ronda_actual["completa"] = True

    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": rondas})

    if todos_reportados:
        await _siguiente_ronda_automatica(bot, codigo, guild)
        return True, "Resultado reportado y ronda completada. Siguiente ronda generada.", emp_encontrado, emp_index
    else:
        return True, "Resultado reportado.", emp_encontrado, emp_index

async def _siguiente_ronda_automatica(bot, codigo: str, guild: discord.Guild = None):
    """
    Genera la siguiente ronda automáticamente si el torneo no ha terminado.
    Si ya se jugaron todas las rondas posibles (participantes - 1), finaliza el torneo.
    """
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return
    ronda_actual = torneo.get("ronda_actual", 0)
    participantes = torneo.get("inscritos_ids", [])
    # Si ya se jugaron todas las rondas posibles (participantes - 1 en suizo ideal)
    # o si el número de rondas es >= participantes - 1, no generamos más
    if ronda_actual >= len(participantes) - 1:
        # Marcar torneo como finalizado automáticamente
        await actualizar_torneo_estado(bot, codigo, {"estado": "finalizado"})
        if guild:
            canal_anuncios = discord.utils.get(guild.text_channels, name="📰-cartelera‐torneos")
            if canal_anuncios:
                await canal_anuncios.send(f"🏁 El torneo `{codigo}` ha finalizado automáticamente (todas las rondas jugadas).")
        return

    ok, msg = await generar_ronda(bot, codigo)
    if not ok:
        print(f"Error generando ronda: {msg}")
        return

    if guild:
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            rondas_data = await leer_rondas(bot, codigo)
            if rondas_data:
                rondas = rondas_data.get("rondas", [])
                if rondas:
                    ultima_ronda = rondas[-1]
                    mensaje_citas = f"📢 **Emparejamientos Ronda {ultima_ronda['numero']} - Torneo {codigo}**\n"
                    for emp in ultima_ronda.get("emparejamientos", []):
                        j1 = emp["j1"]
                        j2 = emp["j2"]
                        if j2 is None:
                            mensaje_citas += f"<@{j1}> → BYE\n"
                        else:
                            mensaje_citas += f"<@{j1}> vs <@{j2}>\n"
                    await canal_citas.send(mensaje_citas)
# ============================================================
# ELIMINAR RONDA
# ============================================================

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

    rondas.pop(idx)

    if ronda_num == torneo.get("ronda_actual", 0):
        if rondas:
            nueva_ronda_actual = rondas[-1]["numero"]
        else:
            nueva_ronda_actual = 0
        await actualizar_torneo_estado(bot, codigo, {"ronda_actual": nueva_ronda_actual})

    await guardar_rondas(bot, codigo, {"codigo": codigo, "rondas": rondas})
    await calcular_clasificacion(bot, codigo)

    if guild:
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            async for msg in canal_citas.history(limit=200):
                if msg.author == bot.user and f"Emparejamientos Ronda {ronda_num} - Torneo {codigo}" in msg.content:
                    await msg.delete()
                    break

    return True, f"Ronda {ronda_num} eliminada correctamente."

# ============================================================
# CLASIFICACIÓN
# ============================================================

async def calcular_clasificacion(bot, codigo: str) -> List[Dict]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return []

    inscritos_ids = torneo.get("inscritos_ids", [])
    stats = defaultdict(lambda: {
        "mp": 0.0,
        "w": 0,
        "l": 0,
        "dw": 0,
        "opponents": [],
        "games_won": 0,
        "games_played": 0,
        "omw": 0.0,
        "bch": 0.0,
        "dif": 0
    })

    for pid in inscritos_ids:
        stats[pid]

    rondas_data = await leer_rondas(bot, codigo)
    rondas = rondas_data.get("rondas", []) if rondas_data else []

    for ronda in rondas:
        for emp in ronda.get("emparejamientos", []):
            if emp.get("resultado") == "BYE":
                j1 = emp["j1"]
                stats[j1]["mp"] += 3.0
                stats[j1]["w"] += 1
                continue
            if emp.get("resultado") is None:
                continue
            j1 = emp["j1"]
            j2 = emp["j2"]
            res = emp["resultado"]
            try:
                s1, s2 = map(int, res.split("-"))
            except:
                continue
            stats[j1]["opponents"].append(j2)
            stats[j2]["opponents"].append(j1)
            stats[j1]["games_won"] += s1
            stats[j1]["games_played"] += s1 + s2
            stats[j2]["games_won"] += s2
            stats[j2]["games_played"] += s1 + s2
            if s1 > s2:
                stats[j1]["mp"] += 3.0
                stats[j1]["w"] += 1
                stats[j2]["l"] += 1
            elif s2 > s1:
                stats[j2]["mp"] += 3.0
                stats[j2]["w"] += 1
                stats[j1]["l"] += 1
            else:
                stats[j1]["mp"] += 1.0
                stats[j2]["mp"] += 1.0
                stats[j1]["dw"] += 1
                stats[j2]["dw"] += 1

    for pid, data in stats.items():
        omw = 0.0
        buch = []
        for opp in data["opponents"]:
            opp_data = stats.get(opp)
            if opp_data:
                total_matches = opp_data["w"] + opp_data["l"] + opp_data["dw"]
                if total_matches > 0:
                    omw += opp_data["mp"] / (total_matches * 3)
                    buch.append(opp_data["mp"] / (total_matches * 3))
        data["omw"] = omw / len(data["opponents"]) if data["opponents"] else 0.0
        if buch:
            buch.sort()
            buch = buch[1:-1] if len(buch) > 2 else buch
            data["bch"] = sum(buch) / len(buch) if buch else 0.0
        else:
            data["bch"] = 0.0
        data["dif"] = data["games_won"] - (data["games_played"] - data["games_won"])

    ranking = sorted(stats.items(), key=lambda x: (-x[1]["mp"], -x[1]["omw"], -x[1]["dif"], -x[1]["bch"]))

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