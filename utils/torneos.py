######## torneos.py #######

import discord

from utils.commons import (
    borrar_mensaje_seguro,
    obtener_torneo_usuario,
    cartas_mas_jugadas,
    best_decks_handle,
    analizar_torneo_con_ia
)
from utils.admin import moderador_permisos_handle


# utils/torneos.py

async def actualizar_clasificacion_battle_handle(ctx, codigo_battle: str):
    await borrar_mensaje_seguro(ctx)

    if not codigo_battle:
        await ctx.author.send("❌ Necesitas enviar el código del battle.")
        return

    canal_resultados = discord.utils.get(ctx.guild.text_channels, name="resultados-battle")
    if not canal_resultados:
        await ctx.author.send("❌ No se encontró el canal `#resultados-battle`.")
        return

    # 🔹 Inicializar jugadores
    jugadores = {}

    async for msg in canal_resultados.history(limit=500):
        contenido = msg.content.strip()
        if not contenido.startswith(f"[{codigo_battle.lower()}]"):
            continue

        try:
            parte_jugadores, parte_resultado = contenido.split("->")
            ids = parte_jugadores.split("]")[1].split("vs")
            id1 = ids[0].strip()
            id2 = ids[1].strip()
            s1, s2 = map(int, parte_resultado.strip().split("-"))
        except:
            continue

        for pid in [id1, id2]:
            if pid not in jugadores:
                jugadores[pid] = {
                    "mp": 0,
                    "games_won": 0,
                    "games_played": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "opponents": []
                }

        jugadores[id1]["opponents"].append(id2)
        jugadores[id2]["opponents"].append(id1)

        jugadores[id1]["games_won"] += s1
        jugadores[id1]["games_played"] += s1 + s2
        jugadores[id2]["games_won"] += s2
        jugadores[id2]["games_played"] += s1 + s2

        if s1 > s2:
            jugadores[id1]["mp"] += 3
            jugadores[id1]["wins"] += 1
            jugadores[id2]["losses"] += 1
        elif s2 > s1:
            jugadores[id2]["mp"] += 3
            jugadores[id2]["wins"] += 1
            jugadores[id1]["losses"] += 1
        else:
            jugadores[id1]["mp"] += 1
            jugadores[id2]["mp"] += 1
            jugadores[id1]["draws"] += 1
            jugadores[id2]["draws"] += 1

    # 🔹 Calcular desempates y construir clasificación
    clasificacion = []
    for pid, datos in jugadores.items():
        # Tie Break #1: OMW%
        omw = 0.0
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            omw += opp["mp"] / (total_matches * 3)
        omw = omw / len(datos["opponents"]) if datos["opponents"] else 0.0

        # Tie Break #2: Median-Buchholz
        buchholz_scores = []
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            buchholz_scores.append(opp["mp"] / (total_matches * 3))
        if buchholz_scores:
            if len(buchholz_scores) > 2:
                buchholz_scores_sorted = sorted(buchholz_scores)[1:-1]
            else:
                buchholz_scores_sorted = buchholz_scores
            buchholz = sum(buchholz_scores_sorted) / len(buchholz_scores_sorted)
        else:
            buchholz = 0.0

        diff = datos["games_won"] - (datos["games_played"] - datos["games_won"])

        try:
            miembro = await ctx.guild.fetch_member(int(pid))
            nombre = f"@{miembro.display_name}"
        except (ValueError, discord.NotFound):
            nombre = pid

        clasificacion.append({
            "nombre": nombre,
            "mp": datos["mp"],
            "omw": omw,
            "buchholz": buchholz,
            "diff": diff,
            "wins": datos["wins"],
            "losses": datos["losses"],
            "draws": datos["draws"]
        })

    # 🔹 Ordenar
    clasificacion.sort(key=lambda x: (-x["mp"], -x["omw"], -x["diff"], -x["buchholz"]))

    # 🔹 Construir tabla
    mensaje = f"📊 **Clasificación del battle `{codigo_battle}`:**\n"
    mensaje += "```markdown\n"
    mensaje += "Rango | Participante           | G-P-E | Pts  | OMW%   | Buchholz | Dif\n"
    mensaje += "------|------------------------|-------|------|--------|----------|-----\n"
    for i, p in enumerate(clasificacion, 1):
        gpe = f"{p['wins']}-{p['losses']}-{p['draws']}"
        linea = f"{i:<5} | {p['nombre'][:22]:<22} | {gpe:<5} | {p['mp']:<4} | {p['omw']:.3f}  | {p['buchholz']:.5f}  | {p['diff']:+}"
        mensaje += linea + "\n"
    mensaje += "```"

    # 🔹 Canal de destino
    canal = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal:
        return await ctx.send("⚠️ No se encontró el canal de clasificaciones.")

    mensaje_existente = None
    async for msg in canal.history(limit=50):
        if msg.author == ctx.guild.me and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del battle `{codigo_battle}`:**"):
                mensaje_existente = msg
                break

    if mensaje_existente:
        await mensaje_existente.edit(content=mensaje)
    else:
        await canal.send(mensaje)

async def tournament_report_handle(ctx, codigo_torneo: str = None):
    # Solo moderadores
    if not await moderador_permisos_handle(ctx):
        return
    # 🔹 Obtener código de torneo
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 No escribiste el código del torneo.\n"
                            "Elige uno de los torneos en los que estás inscrito:",
            complete=True
        )
        if not codigo_torneo:
            return

    # 🔹 Obtener datos
    cartas_data = await cartas_mas_jugadas(ctx, codigo_torneo, '🧠📈analisis-torneos')
    decks_data = await best_decks_handle(ctx, codigo_torneo, '🧠📈analisis-torneos')

    if not cartas_data or not decks_data:
        return await ctx.send("❌ No se pudo generar el informe del torneo.")

    # 🔹 Analizar con IA
    await analizar_torneo_con_ia(ctx, cartas_data, decks_data)


