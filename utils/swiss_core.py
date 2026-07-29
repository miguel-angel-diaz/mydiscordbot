# utils/swiss_core.py
import discord
import random
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from utils.torneos_estado import (
    leer_estado,
    guardar_estado,
    actualizar_torneo_estado,
    slugify_challonge,
    generar_codigo_unico
)

# ============================================================
# GESTIÓN DE TORNEOS
# ============================================================

async def crear_torneo(bot, nombre: str, max_jugadores: int, nivel: str, fecha_inicio: str) -> str:
    nivel_slug = slugify_challonge(nivel)
    codigo = f"premodern{nivel_slug}{generar_codigo_unico(6)}"

    torneo = {
        "codigo": codigo,
        "nombre": nombre,
        "nivel": nivel,
        "total_maximo": max_jugadores,
        "tipo": "swiss",
        "fecha_inicio": fecha_inicio,
        "ronda_actual": 0,
        "inscritos_ids": [],
        "rondas": [],
        "clasificacion": []
    }

    await actualizar_torneo_estado(bot, codigo, torneo)
    return codigo

async def eliminar_torneo_swiss(bot, codigo: str) -> bool:
    estado = await leer_estado(bot)
    original_len = len(estado.get("torneos", []))
    estado["torneos"] = [t for t in estado.get("torneos", []) if t.get("codigo") != codigo]
    if len(estado["torneos"]) < original_len:
        await guardar_estado(bot, estado)
        return True
    return False

async def obtener_torneos_activos(bot) -> List[Dict]:
    estado = await leer_estado(bot)
    return [t for t in estado.get("torneos", []) if t.get("tipo") == "swiss"]

async def obtener_torneo(bot, codigo: str) -> Optional[Dict]:
    estado = await leer_estado(bot)
    for t in estado.get("torneos", []):
        if t.get("codigo") == codigo:
            return t
    return None

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
    torneo["inscritos_ids"] = inscritos
    await actualizar_torneo_estado(bot, codigo, torneo)
    return True, "Inscripción completada."

async def desinscribir_jugador(bot, codigo: str, usuario_id: int) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    inscritos = torneo.get("inscritos_ids", [])
    if str(usuario_id) not in inscritos:
        return False, "No estás inscrito en este torneo."

    inscritos.remove(str(usuario_id))
    torneo["inscritos_ids"] = inscritos
    await actualizar_torneo_estado(bot, codigo, torneo)
    return True, "Desinscripción completada."

# ============================================================
# RONDAS Y EMPAREJAMIENTOS
# ============================================================

# utils/swiss_core.py - generar_ronda (versión corregida)

async def generar_ronda(bot, codigo: str) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."
    if torneo.get("tipo") != "swiss":
        return False, "Este torneo no es suizo."

    participantes = torneo.get("inscritos_ids", [])
    if len(participantes) < 2:
        return False, "Se necesitan al menos 2 jugadores."

    ronda_actual = torneo.get("ronda_actual", 0)
    nueva_ronda = ronda_actual + 1

    # Calcular puntuaciones (si no hay rondas previas, todos a 0)
    puntuaciones = _calcular_puntuaciones(torneo)
    # Si no hay puntuaciones, asignar 0 a todos los participantes
    if not puntuaciones:
        for pid in participantes:
            puntuaciones[pid] = 0.0

    historial = _cargar_historial_emparejamientos(torneo)

    # Ordenar participantes por puntuación descendente (y aleatorio para desempate)
    ordenados = sorted(puntuaciones.items(), key=lambda x: (-x[1], random.random()))

    # Depuración: imprimir participantes y puntuaciones
    print(f"🔍 Participantes: {participantes}")
    print(f"🔍 Puntuaciones: {puntuaciones}")
    print(f"🔍 Ordenados: {ordenados}")

    emparejamientos = []
    usados = set()
    for jugador, pts in ordenados:
        if jugador in usados:
            continue
        oponente = _buscar_oponente(jugador, ordenados, usados, historial, pts)
        if oponente:
            emparejamientos.append({"j1": jugador, "j2": oponente, "resultado": None})
            usados.add(jugador)
            usados.add(oponente)
        else:
            emparejamientos.append({"j1": jugador, "j2": None, "resultado": "BYE"})
            usados.add(jugador)

    # Si después de todo no hay emparejamientos, es un error
    if not emparejamientos:
        return False, "No se pudieron generar emparejamientos. Revisa los participantes."

    ronda_data = {
        "numero": nueva_ronda,
        "emparejamientos": emparejamientos
    }
    torneo.setdefault("rondas", []).append(ronda_data)
    torneo["ronda_actual"] = nueva_ronda
    await actualizar_torneo_estado(bot, codigo, torneo)
    return True, f"Ronda {nueva_ronda} generada con {len(emparejamientos)} emparejamientos."
# ============================================================
# REPORTE DE RESULTADOS
# ============================================================

async def reportar_resultado(bot, codigo: str, jugador1_id: int, resultado: str, jugador2_id: int) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    rondas = torneo.get("rondas", [])
    if not rondas:
        return False, "El torneo no tiene rondas generadas."

    ronda_actual = rondas[-1]
    if ronda_actual.get("completa", False):
        return False, "La ronda actual ya está completa."

    encontrado = False
    for emp in ronda_actual["emparejamientos"]:
        if (emp["j1"] == str(jugador1_id) and emp["j2"] == str(jugador2_id)) or \
           (emp["j1"] == str(jugador2_id) and emp["j2"] == str(jugador1_id)):
            emp["resultado"] = resultado
            encontrado = True
            break
    if not encontrado:
        return False, "Ese partido no existe en la ronda actual."

    todos_reportados = all(e.get("resultado") is not None for e in ronda_actual["emparejamientos"])
    if todos_reportados:
        ronda_actual["completa"] = True

    await actualizar_torneo_estado(bot, codigo, torneo)
    return True, "Resultado reportado."

# ============================================================
# CLASIFICACIÓN
# ============================================================

async def calcular_clasificacion(bot, codigo: str) -> List[Dict]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return []

    stats = defaultdict(lambda: {
        "mp": 0.0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "opponents": [],
        "games_won": 0,
        "games_played": 0
    })

    for ronda in torneo.get("rondas", []):
        for emp in ronda.get("emparejamientos", []):
            if emp.get("resultado") == "BYE":
                j1 = emp["j1"]
                stats[j1]["mp"] += 3.0
                stats[j1]["wins"] += 1
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
                stats[j1]["wins"] += 1
                stats[j2]["losses"] += 1
            elif s2 > s1:
                stats[j2]["mp"] += 3.0
                stats[j2]["wins"] += 1
                stats[j1]["losses"] += 1
            else:
                stats[j1]["mp"] += 1.0
                stats[j2]["mp"] += 1.0
                stats[j1]["draws"] += 1
                stats[j2]["draws"] += 1

    for pid, data in stats.items():
        omw = 0.0
        buch = []
        for opp in data["opponents"]:
            opp_data = stats.get(opp)
            if opp_data:
                total_matches = opp_data["wins"] + opp_data["losses"] + opp_data["draws"]
                if total_matches > 0:
                    omw += opp_data["mp"] / (total_matches * 3)
                    buch.append(opp_data["mp"] / (total_matches * 3))
        data["omw"] = omw / len(data["opponents"]) if data["opponents"] else 0.0
        if buch:
            buch.sort()
            buch = buch[1:-1] if len(buch) > 2 else buch
            data["buchholz"] = sum(buch) / len(buch) if buch else 0.0
        else:
            data["buchholz"] = 0.0
        data["diff"] = data["games_won"] - (data["games_played"] - data["games_won"])

    ranking = sorted(stats.items(), key=lambda x: (-x[1]["mp"], -x[1]["omw"], -x[1]["diff"], -x[1]["buchholz"]))

    clasificacion = []
    for i, (pid, data) in enumerate(ranking, 1):
        clasificacion.append({
            "discord_id": pid,
            "rank": i,
            "mp": data["mp"],
            "wins": data["wins"],
            "losses": data["losses"],
            "draws": data["draws"],
            "omw": data["omw"],
            "buchholz": data["buchholz"],
            "diff": data["diff"]
        })
    torneo["clasificacion"] = clasificacion
    await actualizar_torneo_estado(bot, codigo, torneo)
    return clasificacion

# ============================================================
# FUNCIONES AUXILIARES (privadas)
# ============================================================

def _calcular_puntuaciones(torneo: Dict) -> Dict[str, float]:
    stats = defaultdict(float)
    for ronda in torneo.get("rondas", []):
        for emp in ronda.get("emparejamientos", []):
            if emp.get("resultado") == "BYE":
                stats[emp["j1"]] += 3.0
            elif emp.get("resultado") is not None:
                j1 = emp["j1"]
                j2 = emp["j2"]
                try:
                    s1, s2 = map(int, emp["resultado"].split("-"))
                except:
                    continue
                if s1 > s2:
                    stats[j1] += 3.0
                elif s2 > s1:
                    stats[j2] += 3.0
                else:
                    stats[j1] += 1.0
                    stats[j2] += 1.0
    return stats

def _cargar_historial_emparejamientos(torneo: Dict) -> Dict[str, Dict[str, int]]:
    historial = defaultdict(lambda: defaultdict(int))
    for ronda in torneo.get("rondas", []):
        for emp in ronda.get("emparejamientos", []):
            j1 = emp["j1"]
            j2 = emp["j2"]
            if j2 is not None:
                historial[j1][j2] += 1
                historial[j2][j1] += 1
    return historial

def _buscar_oponente(jugador: str, ordenados: List[Tuple[str, float]], usados: set, historial: Dict, pts: float) -> Optional[str]:
    candidatos = [j for j, p in ordenados if j not in usados and j != jugador and abs(p - pts) <= 0.5]
    def prioridad(j):
        return historial.get(jugador, {}).get(j, 0)
    candidatos.sort(key=prioridad)
    if candidatos:
        return candidatos[0]
    candidatos = [j for j, p in ordenados if j not in usados and j != jugador]
    if candidatos:
        return min(candidatos, key=lambda j: (historial.get(jugador, {}).get(j, 0), -_puntuacion_de(j, ordenados)))
    return None

def _puntuacion_de(jugador: str, ordenados: List[Tuple[str, float]]) -> float:
    for j, pts in ordenados:
        if j == jugador:
            return pts
    return 0.0

# utils/swiss_core.py

async def _siguiente_ronda_automatica(bot, codigo: str, guild: discord.Guild = None):
    """Genera la siguiente ronda y publica los nuevos emparejamientos en el canal de citas."""
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return
    ronda_anterior = torneo.get("ronda_actual", 0)
    nueva_ronda = ronda_anterior + 1

    ok, msg = await generar_ronda(bot, codigo)
    if not ok:
        print(f"Error generando ronda: {msg}")
        return

    if guild:
        # Publicar nuevos emparejamientos en el canal de citas
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            # Obtener el torneo actualizado
            torneo_actual = await obtener_torneo(bot, codigo)
            if torneo_actual:
                rondas = torneo_actual.get("rondas", [])
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



async def _siguiente_ronda_automatica(bot, codigo: str, guild: discord.Guild = None):
    """Genera la siguiente ronda y publica los nuevos emparejamientos en el canal de citas."""
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return
    ronda_anterior = torneo.get("ronda_actual", 0)
    nueva_ronda = ronda_anterior + 1

    ok, msg = await generar_ronda(bot, codigo)
    if not ok:
        print(f"Error generando ronda: {msg}")
        return

    if guild:
        # Publicar nuevos emparejamientos en el canal de citas
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            # Obtener el torneo actualizado
            torneo_actual = await obtener_torneo(bot, codigo)
            if torneo_actual:
                rondas = torneo_actual.get("rondas", [])
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



async def eliminar_ronda_swiss(bot, codigo: str, ronda_num: int, guild: discord.Guild = None) -> Tuple[bool, str]:
    """
    Elimina una ronda específica de un torneo suizo.
    Retorna: (ok, mensaje)
    """
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    if torneo.get("tipo") != "swiss":
        return False, "Este torneo no es suizo."

    rondas = torneo.get("rondas", [])
    if not rondas:
        return False, "El torneo no tiene rondas."

    # Buscar la ronda por número
    idx = -1
    for i, r in enumerate(rondas):
        if r.get("numero") == ronda_num:
            idx = i
            break

    if idx == -1:
        return False, f"La ronda {ronda_num} no existe."

    # Eliminar la ronda
    rondas.pop(idx)

    # Actualizar ronda_actual si es necesario
    if ronda_num == torneo.get("ronda_actual", 0):
        if rondas:
            # Si quedan rondas, la actual es la última
            torneo["ronda_actual"] = rondas[-1]["numero"]
        else:
            torneo["ronda_actual"] = 0

    # Guardar el torneo sin la ronda
    await actualizar_torneo_estado(bot, codigo, torneo)

    # Recalcular clasificación desde las rondas restantes
    await calcular_clasificacion(bot, codigo)

    # Eliminar el mensaje de citas de esa ronda
    if guild:
        canal_citas = discord.utils.get(guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            async for msg in canal_citas.history(limit=200):
                if msg.author == bot.user and f"Emparejamientos Ronda {ronda_num} - Torneo {codigo}" in msg.content:
                    await msg.delete()
                    break

    return True, f"Ronda {ronda_num} eliminada correctamente."