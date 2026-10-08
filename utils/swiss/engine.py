######## swiss/engine.py #######
"""
Lógica pura del sistema suizo: sin Discord, sin estado guardado y sin async (se prueba en tests/test_swiss_engine.py).
Recibe y devuelve las mismas estructuras que se guardan:
  torneo = {"estado", "nivel", "inscritos_ids", "retirados", "total_maximo", "ronda_actual", ...}
  ronda  = {"numero", "completa", "emparejamientos": [{"j1", "j2" (None = BYE), "resultado" ("2-1", "BYE" o None)}]}
Los IDs de jugador son siempre str.

Es la ÚNICA fuente de estadísticas y de orden de clasificación: la usan el suizo, el Battle Royale y la
clasificación de los torneos antiguos de Challonge.
"""
import hashlib
import math
import random
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

MWP_MINIMO = 1 / 3   # MTR (Apéndice C): el % de victorias de cada rival se cuenta como mínimo 33 %
LIMITE_PASOS_EMPAREJAMIENTO = 200_000   # salvaguarda: con torneos normales sobra con creces

# ============================================================
# RONDAS
# ============================================================

def rondas_necesarias(num_jugadores: int) -> int:
    """Devuelve el número mínimo de rondas para un torneo suizo con N jugadores."""
    if num_jugadores <= 1:
        return 0
    return math.ceil(math.log2(num_jugadores))


def participantes_activos(torneo: dict) -> List[str]:
    """Inscritos que se siguen emparejando: los retirados (p. ej. salieron del servidor) conservan sus resultados."""
    retirados = set(torneo.get("retirados", []))
    return [p for p in torneo.get("inscritos_ids", []) if p not in retirados]


def partidas_pendientes(ronda: Optional[dict]) -> List[dict]:
    """Emparejamientos sin resultado de una ronda (los BYE nunca están pendientes)."""
    return [e for e in (ronda or {}).get("emparejamientos", []) if e.get("resultado") is None]

# ============================================================
# ESTADÍSTICAS Y CLASIFICACIÓN
# ============================================================

def calcular_estadisticas(rondas: List[dict], jugadores: Iterable[str]) -> Dict[str, dict]:
    """
    Única fuente de estadísticas (emparejamientos y todas las clasificaciones usan esta función).
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


def desempate_final(codigo: str, pid: str) -> str:
    """Orden pseudoaleatorio fijo por torneo: reproducible y sin favorecer IDs antiguos o nuevos."""
    return hashlib.sha256(f"{codigo}:{pid}".encode()).hexdigest()


def clave_clasificacion(codigo: str, pid: str, s: dict) -> tuple:
    """Puntos, OMW%, diferencia de juegos, Buchholz y, si todo empata, un orden fijo por torneo."""
    return (-s["mp"], -s["omw"], -s["dif"], -s["bch"], desempate_final(codigo, pid))


def clasificacion(codigo: str, rondas: List[dict], jugadores: Iterable[str]) -> List[Dict]:
    """[{id, rk, mp, w, l, dw, omw, bch, dif}] ordenada; es lo que se guarda y se publica."""
    stats = calcular_estadisticas(rondas, jugadores)
    ranking = sorted(stats.items(), key=lambda x: clave_clasificacion(codigo, x[0], x[1]))
    return [{"id": pid, "rk": i, "mp": d["mp"], "w": d["w"], "l": d["l"], "dw": d["dw"],
             "omw": d["omw"], "bch": d["bch"], "dif": d["dif"]} for i, (pid, d) in enumerate(ranking, 1)]

# ============================================================
# INSCRIPCIONES
# ============================================================

def error_inscripcion(torneo: Optional[dict], usuario_id, roles_miembro: Iterable[str], roles_socios: Iterable[str],
                      forzar: bool = False) -> Optional[str]:
    """Motivo por el que no se puede inscribir (None si se puede). `forzar` (un admin) se salta el nivel."""
    if not torneo:
        return "El torneo no existe."
    if torneo.get("tipo") != "swiss":
        return "Este torneo no es suizo."
    if torneo.get("estado", "abierto") != "abierto":
        return "Las inscripciones de este torneo están cerradas."
    if not forzar and str(torneo.get("nivel", "todos")).lower() == "socios":
        if not {r.lower() for r in roles_miembro} & {r.lower() for r in roles_socios}:
            return "Este torneo es solo para socios."
    inscritos = torneo.get("inscritos_ids", [])
    if str(usuario_id) in inscritos:
        return "Ya estás inscrito."
    maximo = torneo.get("total_maximo")
    if maximo and len(inscritos) >= maximo:
        return "No quedan plazas disponibles."
    return None

# ============================================================
# NUEVA RONDA
# ============================================================

def error_nueva_ronda(torneo: dict, rondas: List[dict]) -> Optional[str]:
    """Motivo por el que no se puede generar otra ronda (None si se puede)."""
    if torneo.get("estado") == "finalizado":
        return "El torneo ya ha finalizado."
    if len(participantes_activos(torneo)) < 2:
        return "Se necesitan al menos 2 jugadores."
    # No se genera una ronda nueva dejando partidas sin resultado en la anterior
    if rondas:
        pendientes = len(partidas_pendientes(rondas[-1]))
        if pendientes:
            return f"La ronda {rondas[-1].get('numero')} tiene {pendientes} partida(s) sin resultado."
    total = rondas_necesarias(len(torneo.get("inscritos_ids", [])))
    if torneo.get("ronda_actual", 0) >= total:
        return f"Ya se han jugado las {total} rondas del torneo. Usa `!finalizar-swiss`."
    return None


def nueva_ronda(codigo: str, torneo: dict, rondas: List[dict], azar: random.Random = random) -> dict:
    """
    Ronda siguiente (sin guardarla): en la 1 el orden se sortea; después, el de la clasificación actual.
    Comprobar antes error_nueva_ronda().
    """
    participantes = participantes_activos(torneo)
    if rondas:
        stats = calcular_estadisticas(rondas, torneo.get("inscritos_ids", []))
        orden = sorted(
            participantes,
            key=lambda p: (-stats[p]["mp"], -stats[p]["omw"], -stats[p]["dif"], desempate_final(codigo, p)),
        )
    else:
        orden = list(participantes)
        azar.shuffle(orden)

    parejas, bye = emparejar_ronda(orden, historial_emparejamientos(rondas), jugadores_con_bye(rondas))
    emparejamientos = [{"j1": a, "j2": b, "resultado": None} for a, b in parejas]
    if bye:
        emparejamientos.append({"j1": bye, "j2": None, "resultado": "BYE"})
    return {"numero": torneo.get("ronda_actual", 0) + 1, "emparejamientos": emparejamientos, "completa": False}

# ============================================================
# RESULTADOS
# ============================================================

def buscar_partida(ronda: dict, jugador1_id, jugador2_id) -> Tuple[int, Optional[dict], bool]:
    """(índice, emparejamiento, invertido) de la partida entre los dos jugadores en cualquier orden; (-1, None, False) si no está."""
    a, b = str(jugador1_id), str(jugador2_id)
    for i, emp in enumerate(ronda.get("emparejamientos", [])):
        if emp.get("j1") == a and emp.get("j2") == b:
            return i, emp, False
        if emp.get("j1") == b and emp.get("j2") == a:
            return i, emp, True
    return -1, None, False


def invertir_resultado(resultado: str) -> str:
    """"2-1" -> "1-2" (el resultado se reportó con los jugadores al revés de como se guardan)."""
    s1, s2 = resultado.split("-")
    return f"{s2}-{s1}"


def registrar_resultado(ronda: dict, jugador1_id, resultado: str, jugador2_id) -> Tuple[bool, str, Optional[dict], int]:
    """
    Anota un resultado YA VALIDADO ("2-1") en la ronda (la modifica) y la marca completa si era la última partida.
    Devuelve (ok, mensaje, emparejamiento, índice).
    """
    if ronda.get("completa", False):
        return False, "La ronda actual ya está completa.", None, -1
    idx, emp, invertido = buscar_partida(ronda, jugador1_id, jugador2_id)
    if emp is None:
        return False, "Ese partido no existe en la ronda actual.", None, -1
    if emp.get("resultado") is not None:
        return False, "Este partido ya tiene un resultado reportado.", None, -1
    emp["resultado"] = invertir_resultado(resultado) if invertido else resultado
    if not partidas_pendientes(ronda):
        ronda["completa"] = True
    return True, "Resultado reportado.", emp, idx


def partida_pendiente_de(ronda: Optional[dict], usuario_id) -> Optional[dict]:
    """Partida sin resultado (y con rival) del jugador en la ronda, o None."""
    uid = str(usuario_id)
    return next((e for e in partidas_pendientes(ronda)
                 if uid in (e.get("j1"), e.get("j2")) and e.get("j2") is not None), None)

# ============================================================
# EMPAREJAMIENTOS
# ============================================================

def historial_emparejamientos(rondas: List[dict]) -> Dict[str, Dict[str, int]]:
    """Devuelve un diccionario {j1: {j2: veces}} con todos los enfrentamientos previos."""
    historial = defaultdict(lambda: defaultdict(int))
    for ronda in rondas:
        for emp in ronda.get("emparejamientos", []):
            j1, j2 = emp.get("j1"), emp.get("j2")
            if j1 is not None and j2 is not None:
                historial[j1][j2] += 1
                historial[j2][j1] += 1
    return historial


def jugadores_con_bye(rondas: List[dict]) -> Set[str]:
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


def emparejar_ronda(orden: List[str], historial, con_bye: Set[str]):
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
        sin_bye = [p for p in reversed(orden) if p not in con_bye]
        repetidos = [p for p in reversed(orden) if p in con_bye]
        # No repetir BYE tiene prioridad sobre evitar revanchas (el BYE son 3 puntos gratis)
        grupos_bye = [g for g in (sin_bye, repetidos) if g]

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
