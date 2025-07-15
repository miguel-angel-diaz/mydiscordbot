import discord
from datetime import datetime
import re
from collections import defaultdict

async def guardar_resultado(ctx, canal_resultados, jugador1, resultado, jugador2, codigo):
    mensaje = (
        f"🎯 Resultado registrado:\n"
        f"🆚 {jugador1.mention} {resultado} {jugador2.mention}\n"
        f"🏆 Código del torneo: `{codigo}`\n"
        f"🕒 Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    await canal_resultados.send(mensaje)

async def extraer_partidas(canal_resultados, codigo):
    patron = re.compile(
        r"🆚 <@!?(\d+)> (\d+)-(\d+) <@!?(\d+)>\n🏆 Código del torneo: `(" + re.escape(codigo) + r")`",
        re.IGNORECASE
    )
    partidas = []

    async for mensaje in canal_resultados.history(limit=200):
        match = patron.search(mensaje.content)
        if match:
            p1_id, g1, g2, p2_id, _ = match.groups()
            partidas.append({
                "jugador1": int(p1_id),
                "jugador2": int(p2_id),
                "g1": int(g1),
                "g2": int(g2)
            })
    return partidas

def calcular_clasificacion(partidas, guild):
    puntos = defaultdict(int)
    game_wins = defaultdict(int)
    game_losses = defaultdict(int)
    opponents = defaultdict(set)
    game_total = defaultdict(int)
    match_wins = defaultdict(int)
    match_total = defaultdict(int)

    for p in partidas:
        j1, j2 = p["jugador1"], p["jugador2"]
        g1, g2 = p["g1"], p["g2"]

        # Actualizar partidas jugadas y oponentes
        opponents[j1].add(j2)
        opponents[j2].add(j1)
        match_total[j1] += 1
        match_total[j2] += 1

        game_total[j1] += g1 + g2
        game_total[j2] += g1 + g2
        game_wins[j1] += g1
        game_wins[j2] += g2
        game_losses[j1] += g2
        game_losses[j2] += g1

        if g1 > g2:
            puntos[j1] += 3
            match_wins[j1] += 1
        elif g2 > g1:
            puntos[j2] += 3
            match_wins[j2] += 1
        else:
            puntos[j1] += 1
            puntos[j2] += 1

    clasificacion = []

    for jugador_id in puntos:
        mwp = match_wins[jugador_id] / match_total[jugador_id] if match_total[jugador_id] else 0
        gwp = game_wins[jugador_id] / game_total[jugador_id] if game_total[jugador_id] else 0

        # Opponent Match Win Percentage
        omwp_sum = 0
        for op_id in opponents[jugador_id]:
            op_mwp = match_wins[op_id] / match_total[op_id] if match_total[op_id] else 0
            omwp_sum += op_mwp
        omwp = omwp_sum / len(opponents[jugador_id]) if opponents[jugador_id] else 0

        nombre = f"<@{jugador_id}>"
        clasificacion.append({
            "jugador": nombre,
            "puntos": puntos[jugador_id],
            "MWP": mwp,
            "OMWP": omwp,
            "GWP": gwp
        })

    # Ordenar por puntos, MWP, OMWP, GWP
    clasificacion.sort(key=lambda x: (x["puntos"], x["MWP"], x["OMWP"], x["GWP"]), reverse=True)
    return clasificacion

def generar_embed_clasificacion(clasificacion, codigo):
    embed = discord.Embed(
        title=f"🏆 Clasificación actual — Código: `{codigo}`",
        color=discord.Color.blue()
    )
    for i, jugador in enumerate(clasificacion, start=1):
        embed.add_field(
            name=f"#{i} {jugador['jugador']}",
            value=(
                f"Puntos: `{jugador['puntos']}`\n"
                f"MWP: `{jugador['MWP']:.2%}`\n"
                f"OMWP: `{jugador['OMWP']:.2%}`\n"
                f"GWP: `{jugador['GWP']:.2%}`"
            ),
            inline=False
        )
    return embed
