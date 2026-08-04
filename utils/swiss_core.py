import discord
import asyncio
import math
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import config

from utils.torneos_estado import (
    actualizar_torneo_estado,
    eliminar_torneo_estado,
    obtener_torneo_estado,
    leer_rondas,
    guardar_rondas,
    leer_clasificacion,
    guardar_clasificacion,
    leer_estado,
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
    estado = await leer_estado(bot)
    torneos = estado.get("torneos", []) if isinstance(estado, dict) else []
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

async def desinscribir_jugador(bot, codigo: str, usuario_id: int, guild: discord.Guild = None) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    inscritos = torneo.get("inscritos_ids", [])
    if str(usuario_id) not in inscritos:
        return False, "No estás inscrito en este torneo."

    inscritos.remove(str(usuario_id))
    await actualizar_torneo_estado(bot, codigo, {"inscritos_ids": inscritos})

    # 🔹 Eliminar deck del usuario en submitted-decks
    if guild is None:
        # Intentar obtener el guild a partir del bot y el GUILD_ID_ADMISION
        guild = bot.get_guild(config.GUILD_ID_ADMISION)
        if not guild:
            return True, "Desinscripción completada, pero no se pudo eliminar el deck (guild no encontrado)."

    canal_submitted = discord.utils.get(guild.text_channels, name="submitted-decks")
    if canal_submitted:
        codigo_deck = f"{codigo}_{usuario_id}"
        async for mensaje in canal_submitted.history(limit=200):
            if not mensaje.embeds:
                continue
            eliminado = False
            for embed in mensaje.embeds:
                # Buscar en título, descripción y campos
                titulo = embed.title or ""
                descripcion = embed.description or ""
                if codigo_deck in titulo or codigo_deck in descripcion:
                    try:
                        await mensaje.delete()
                        eliminado = True
                        break
                    except discord.Forbidden:
                        print(f"⚠️ No tengo permisos para eliminar el deck `{codigo_deck}`.")
                    except discord.HTTPException as e:
                        print(f"⚠️ Error al eliminar el deck `{codigo_deck}`: {e}")
                # Buscar en campos
                for field in embed.fields:
                    if codigo_deck in field.value or codigo_deck in field.name:
                        try:
                            await mensaje.delete()
                            eliminado = True
                            break
                        except discord.Forbidden:
                            print(f"⚠️ No tengo permisos para eliminar el deck `{codigo_deck}`.")
                        except discord.HTTPException as e:
                            print(f"⚠️ Error al eliminar el deck `{codigo_deck}`: {e}")
                if eliminado:
                    break
            if eliminado:
                break

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

async def generar_ronda(bot, codigo: str) -> Tuple[bool, str]:
    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return False, "El torneo no existe."

    participantes = torneo.get("inscritos_ids", [])
    if len(participantes) < 2:
        return False, "Se necesitan al menos 2 jugadores."

    rondas_data = await leer_rondas(bot, codigo)
    rondas = rondas_data.get("rondas", []) if rondas_data else []

    stats = await _calcular_stats_completos(bot, codigo, participantes, rondas)

    ordenados = sorted(
        participantes,
        key=lambda pid: (-stats[pid]["mp"], -stats[pid]["omw"])
    )

    historial = _cargar_historial_emparejamientos(rondas)
    usados = set()
    emparejamientos = []

    # Agrupar por puntos
    grupos = {}
    for pid in ordenados:
        mp = stats[pid]["mp"]
        grupos.setdefault(mp, []).append(pid)

    sin_emparejar = []

    for mp in sorted(grupos.keys(), reverse=True):
        grupo = grupos[mp]
        if sin_emparejar:
            grupo = sin_emparejar + grupo
            sin_emparejar = []

        grupo.sort(key=lambda pid: (-stats[pid]["omw"], -stats[pid].get("dif", 0)))

        i = 0
        max_intentos = len(grupo) * 3
        intentos = 0
        while i < len(grupo) and intentos < max_intentos:
            intentos += 1
            if i + 1 < len(grupo):
                j1 = grupo[i]
                j2 = grupo[i+1]
                if historial.get(j1, {}).get(j2, 0) == 0:
                    emparejamientos.append({"j1": j1, "j2": j2, "resultado": None})
                    usados.add(j1)
                    usados.add(j2)
                    i += 2
                    intentos = 0
                else:
                    grupo.append(grupo.pop(i+1))
            else:
                sin_emparejar.append(grupo[i])
                i += 1
                intentos = 0

        if i < len(grupo):
            sin_emparejar.extend(grupo[i:])

    # Emparejar los que quedaron sin pareja
    if sin_emparejar:
        while len(sin_emparejar) >= 2:
            j1 = sin_emparejar.pop(0)
            j2 = sin_emparejar.pop(0)
            emparejamientos.append({"j1": j1, "j2": j2, "resultado": None})
            usados.add(j1)
            usados.add(j2)
        if sin_emparejar:
            bye_player = sin_emparejar[0]
            emparejamientos.append({"j1": bye_player, "j2": None, "resultado": "BYE"})
            usados.add(bye_player)

    for pid in participantes:
        if pid not in usados:
            emparejamientos.append({"j1": pid, "j2": None, "resultado": "BYE"})
            usados.add(pid)

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
# CALCULAR ESTADÍSTICAS
# ============================================================

async def _calcular_stats_completos(bot, codigo: str, participantes: List[str], rondas: List[dict]) -> dict:
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
# REPORTAR RESULTADO
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
        return True, "Resultado reportado y ronda completada. Siguiente ronda generada o torneo finalizado.", emp_encontrado, emp_index
    else:
        return True, "Resultado reportado.", emp_encontrado, emp_index

# ============================================================
# SIGUIENTE RONDA AUTOMÁTICA (CON CÁLCULO DE RONDAS NECESARIAS)
# ============================================================

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
                if msg.author == bot.user and f"Torneo {codigo}" in msg.content and "Emparejamientos Ronda" in msg.content:
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
                    mensaje_citas = f"📢 **Emparejamientos Ronda {ultima_ronda['numero']} - Torneo {codigo}**\n"
                    for emp in ultima_ronda.get("emparejamientos", []):
                        j1 = emp["j1"]
                        j2 = emp["j2"]
                        if j2 is None:
                            mensaje_citas += f"<@{j1}> → BYE\n"
                        else:
                            mensaje_citas += f"<@{j1}> vs <@{j2}>\n"
                    await canal_citas.send(mensaje_citas)

    # Actualizar clasificación
    await calcular_clasificacion(bot, codigo)
    if guild:
        await publicar_clasificacion_swiss(bot, guild, codigo)
# ============================================================
# CALCULAR CLASIFICACIÓN
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
# PUBLICAR CLASIFICACIÓN (sin dependencia de ctx)
# ============================================================

async def publicar_clasificacion_swiss(bot, guild, codigo: str):
    canal_ranking = discord.utils.get(guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return

    torneo = await obtener_torneo(bot, codigo)
    if not torneo:
        return

    clasificacion_data = await leer_clasificacion(bot, codigo)
    if not clasificacion_data:
        await calcular_clasificacion(bot, codigo)
        clasificacion_data = await leer_clasificacion(bot, codigo)

    clasificacion = clasificacion_data.get("clasificacion", []) if clasificacion_data else []

    if not clasificacion:
        inscritos = torneo.get("inscritos_ids", [])
        for uid in inscritos:
            try:
                member = await guild.fetch_member(int(uid))
                nombre = member.display_name
            except:
                nombre = f"<@{uid}>"
            clasificacion.append({
                "id": uid,
                "rk": len(clasificacion) + 1,
                "mp": 0,
                "w": 0,
                "l": 0,
                "dw": 0,
                "omw": 0.0,
                "bch": 0.0,
                "dif": 0
            })

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

    async for msg in canal_ranking.history(limit=50):
        if msg.author == bot.user and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del torneo `{codigo}`:**"):
                await msg.delete()
                break

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