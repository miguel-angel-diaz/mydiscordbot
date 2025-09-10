# import discord
# import asyncio
# import aiohttp
# import plotly.graph_objects as go
# import pandas as pd
# import io
# import config
# from utils.commons import borrar_mensaje_seguro, buscar_usuario_en_servidor

# # 🔹 Obtener torneos finalizados
# async def get_torneos_finalizados():
#     url = "https://api.challonge.com/v1/tournaments.json?state=complete"
#     async with aiohttp.ClientSession() as session:
#         async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
#             if resp.status != 200:
#                 return []
#             data = await resp.json()
#             return data

# # 🔹 Obtener participantes de un torneo
# async def get_participants(torneo_id: str):
#     url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/participants.json"
#     async with aiohttp.ClientSession() as session:
#         async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
#             if resp.status != 200:
#                 return []
#             data = await resp.json()
#             return [p["participant"] for p in data]

# # 🔹 Obtener matches de un torneo
# async def get_matches(torneo_id: str):
#     url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/matches.json"
#     async with aiohttp.ClientSession() as session:
#         async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
#             if resp.status != 200:
#                 return []
#             data = await resp.json()
#             return [m["match"] for m in data]

# # 📌 Obtener mapping jugador → arquetipo desde #submitted-decks
# async def get_arquetipos(guild: discord.Guild):
#     canal = discord.utils.get(guild.text_channels, name="submitted-decks")
#     mapping = {}
#     if not canal:
#         return mapping

#     async for mensaje in canal.history(limit=500):
#         if not mensaje.embeds:
#             continue
#         for embed in mensaje.embeds:
#             campos = {field.name.lower(): field.value for field in embed.fields}
#             # Extraer jugador_id del campo "Jugador"
#             jugador_field = campos.get("jugador")
#             if not jugador_field:
#                 continue

#             # El valor es algo como "Nombre (ID: 123456789)"
#             try:
#                 jugador_id_str = jugador_field.split("(ID:")[1].replace(")", "").strip()
#                 jugador_id = int(jugador_id_str)
#             except (IndexError, ValueError):
#                 continue

#             archetype = campos.get("archetype", "Rogue")  # Default a Rogue si no hay arquetipo
#             miembro = guild.get_member(jugador_id)
#             nombre_jugador = miembro.display_name if miembro else f"Desconocido ({jugador_id})"
#             mapping[nombre_jugador] = archetype
#     return mapping

# # 🔹 Calcular stats globales de un jugador en todos los torneos
# async def calcular_stats_global(jugador_discord, guild):
#     torneos = await get_torneos_finalizados()
#     resumen_global = {
#         "jugador": jugador_discord.display_name,
#         "matches": 0,
#         "wins": 0,
#         "losses": 0,
#         "draws": 0,
#         "oponentes": {},
#         "arquetipos": {}
#     }
#     mapping_arquetipos = await get_arquetipos(guild)

#     for torneo in torneos:
#         torneo_id = torneo["tournament"]["id"]
#         participants = await get_participants(torneo_id)
#         matches = await get_matches(torneo_id)

#         # Verificar si el jugador está en este torneo
#         participante = next((p for p in participants if str(jugador_discord.id) == p["name"]), None)
#         if not participante:
#             continue
#         pid = participante["id"]

#         # Contar matches
#         for m in matches:
#             p1, p2 = m["player1_id"], m["player2_id"]
#             winner, loser = m.get("winner_id"), m.get("loser_id")
#             opponent_id = p2 if p1 == pid else p1 if p2 == pid else None
#             if opponent_id:
#                 oponente_discord = next((p for p in participants if p["id"] == opponent_id), None)
#                 nombre_oponente = oponente_discord["name"] if oponente_discord else f"Desconocido ({opponent_id})"
#                 if nombre_oponente not in resumen_global["oponentes"]:
#                     resumen_global["oponentes"][nombre_oponente] = {"matches":0,"wins":0,"losses":0,"draws":0}
#                 resumen_global["oponentes"][nombre_oponente]["matches"] += 1
#                 if winner == pid:
#                     resumen_global["wins"] += 1
#                     resumen_global["oponentes"][nombre_oponente]["wins"] +=1
#                 elif loser == pid:
#                     resumen_global["losses"] +=1
#                     resumen_global["oponentes"][nombre_oponente]["losses"] +=1
#                 else:
#                     resumen_global["draws"] +=1
#                     resumen_global["oponentes"][nombre_oponente]["draws"] +=1
#                 # Arquetipo del oponente
#                 archetype = mapping_arquetipos.get(nombre_oponente, "Rogue")
#                 if archetype not in resumen_global["arquetipos"]:
#                     resumen_global["arquetipos"][archetype] = 0
#                 resumen_global["arquetipos"][archetype] += 1
#     return resumen_global

# # 🔹 Gráficos con Plotly
# def generar_grafico_winrate_global(resumen_global: dict):
#     labels = ["Victorias", "Derrotas", "Empates"]
#     values = [resumen_global.get("wins", 0), resumen_global.get("losses", 0), resumen_global.get("draws", 0)]
#     fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.3)])
#     fig.update_traces(textinfo="percent+label")
#     buf = io.BytesIO()
#     fig.write_image(buf, format="png")
#     buf.seek(0)
#     return buf

# def generar_grafico_oponentes(resumen_global: dict,guild: discord.Guild ):
#     data = []
#     oponentes = resumen_global.get("oponentes", {})
#     for opp_name, stats in oponentes.items():
#         miembro = guild.get_member(int(opp_name))
#         data.append({"oponente": miembro.display_name , "victorias": stats["wins"], "derrotas": stats["losses"], "empates": stats["draws"]})
#     if not data:
#         return None
#     df = pd.DataFrame(data)
#     fig = go.Figure()
#     fig.add_trace(go.Bar(x=df["oponente"], y=df["victorias"], name="Victorias", marker_color="green"))
#     fig.add_trace(go.Bar(x=df["oponente"], y=df["derrotas"], name="Derrotas", marker_color="red"))
#     fig.add_trace(go.Bar(x=df["oponente"], y=df["empates"], name="Empates", marker_color="gray"))
#     fig.update_layout(barmode="stack", title="Rendimiento contra oponentes", xaxis_title="Oponente", yaxis_title="Partidas")
#     buf = io.BytesIO()
#     fig.write_image(buf, format="png")
#     buf.seek(0)
#     return buf

# def generar_grafico_arquetipos(resumen_global: dict):
#     arquetipos = resumen_global.get("arquetipos", {})
#     if not arquetipos:
#         return None
#     labels = list(arquetipos.keys())
#     values = list(arquetipos.values())
#     fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.3)])
#     fig.update_traces(textinfo="percent+label")
#     buf = io.BytesIO()
#     fig.write_image(buf, format="png")
#     buf.seek(0)
#     return buf

# # 🔹 Análisis textual con consejos
# def analizar_text(resumen_global: dict, jugador_nombre: str):
#     total = resumen_global.get("wins",0) + resumen_global.get("losses",0) + resumen_global.get("draws",0)
#     if total ==0:
#         return f"Jugador {jugador_nombre} no tiene partidas registradas en torneos finalizados."
#     winrate = round(resumen_global["wins"]/total*100,2)
#     texto = f"📊 **Análisis de {jugador_nombre}**\nTotal de partidas: {total}\nVictorias: {resumen_global['wins']}\nDerrotas: {resumen_global['losses']}\nEmpates: {resumen_global['draws']}\nWinrate: {winrate}%\n\n"
#     texto += "**Consejos:**\n"
#     if winrate < 40:
#         texto += "- Necesitas mejorar la consistencia. Revisa tus partidas contra los oponentes con mayor winrate.\n"
#     elif winrate < 60:
#         texto += "- Buen desempeño, pero hay margen de mejora en partidas críticas.\n"
#     else:
#         texto += "- Excelente rendimiento, sigue explotando tus fortalezas.\n"
#     return texto

# # 🔹 Comando stats-global
# async def stats_global_handle(ctx):
#     await borrar_mensaje_seguro(ctx)
    
#     # Solo admins pueden consultar stats de otros, si no solo su propio usuario
#     jugador = ctx.author
#     if not ctx.author.guild_permissions.administrator:
#         await ctx.author.send("🔒 Mostrando tus estadísticas globales.")
#     else:
#         await ctx.author.send("✍️ Escribe el nombre o ID del jugador a consultar:")
#         def check(m): return m.author == ctx.author
#         try:
#             msg = await ctx.bot.wait_for("message", check=check, timeout=60)
#             jugador = buscar_usuario_en_servidor(ctx.guild, msg.content.strip()) or jugador
#         except asyncio.TimeoutError:
#             await ctx.author.send("⌛ Tiempo agotado. Se mostrarán tus stats.")
    
#     resumen_global = await calcular_stats_global(jugador, ctx.guild)
    

#     analisis_texto = analizar_trayectoria(resumen_global, jugador.display_name, ctx.guild)
#     await ctx.author.send(analisis_texto)
#     # Gráficos
#     buf_winrate = generar_grafico_winrate_global(resumen_global)
#     buf_oponentes = generar_grafico_oponentes(resumen_global, ctx.guild)
#     buf_arquetipos = generar_grafico_arquetipos(resumen_global)
    
#     await ctx.author.send(file=discord.File(buf_winrate, filename="winrate_global.png"))
#     if buf_oponentes:
#         await ctx.author.send(file=discord.File(buf_oponentes, filename="rendimiento_oponentes.png"))
#     if buf_arquetipos:
#         await ctx.author.send(file=discord.File(buf_arquetipos, filename="rendimiento_arquetipos.png"))
    
#     # Texto con análisis
#     analisis_texto = analizar_text(resumen_global, jugador.display_name, ctx.guild)
#     await ctx.author.send

# def analizar_trayectoria(resumen_global: dict, jugador_nombre: str, guild: discord.Guild):
#     analisis = f"📊 Análisis de la trayectoria de **{jugador_nombre}**\n\n"
    
#     matches = resumen_global.get("matches", 0)
#     wins = resumen_global.get("wins", 0)
#     losses = resumen_global.get("losses", 0)
#     draws = resumen_global.get("draws", 0)
#     winrate = round((wins / matches * 100), 2) if matches > 0 else 0.0
    
#     analisis += f"- Partidas jugadas: {matches}\n"
#     analisis += f"- Victorias: {wins}\n"
#     analisis += f"- Derrotas: {losses}\n"
#     analisis += f"- Empates: {draws}\n"
#     analisis += f"- Winrate global: {winrate}%\n\n"

#     # Análisis de arquetipos enfrentados
#     if resumen_global.get("arquetipos"):
#         analisis += "🏹 Desempeño por arquetipo:\n"
#         for arq, count in resumen_global["arquetipos"].items():
#             analisis += f"  • {arq}: {count} partidas\n"

#     # Análisis de oponentes
#     if resumen_global.get("oponentes"):
#         analisis += "\n⚔️ Rendimiento contra oponentes:\n"
#         for opp_nombre, stats in resumen_global["oponentes"].items():
#             total = stats["wins"] + stats["losses"] + stats["draws"]
#             if total == 0:
#                 continue
#             wr = round(stats["wins"] / total * 100, 2)
#             miembro = guild.get_member(int(opp_nombre))
#             analisis += f"  • {miembro.display_name}: {stats['wins']}W / {stats['losses']}L ({wr}%)\n"

#     # Consejos simples
#     analisis += "\n💡 Consejos:\n"
#     if winrate < 50:
#         analisis += "- Considera revisar estrategias o arquetipos donde tienes bajo rendimiento.\n"
#     else:
#         analisis += "- Mantén tus estrategias actuales y analiza oponentes difíciles para mejorar aún más.\n"

#     # Arquetipos más jugados
#     if resumen_global.get("arquetipos"):
#         arquetipos_mas_jugados = sorted(resumen_global["arquetipos"].items(), key=lambda x: x[1], reverse=True)
#         analisis += f"- Has jugado más partidas con: {arquetipos_mas_jugados[0][0]}.\n"

#     return analisis
