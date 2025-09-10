# import aiohttp
# import discord
# import asyncio
# import plotly.express as px
# import pandas as pd
# import io
# import config
# from utils.commons import borrar_mensaje_seguro, validar_canal_correcto, buscar_usuario_en_servidor, obtener_torneo_usuario

# # 🔎 Obtener participantes de Challonge
# async def get_participants(torneo_id: str):
#     url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/participants.json"
#     async with aiohttp.ClientSession() as session:
#         async with session.get(
#             url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)
#         ) as resp:
#             if resp.status != 200:
#                 return []
#             data = await resp.json()
#             return [p["participant"] for p in data]

# # 🔎 Obtener matches de Challonge
# async def get_matches(torneo_id: str):
#     url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/matches.json"
#     async with aiohttp.ClientSession() as session:
#         async with session.get(
#             url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)
#         ) as resp:
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


# # 📊 Calcular estadísticas por jugador usando nombres de Discord
# def calcular_stats_jugadores(participants, matches, guild=None):
#     stats = {}

#     # Construir stats inicial
#     for p in participants:
#         pid = p["id"]
#         member = guild.get_member(int(p["name"]))
#         nombre =   member.display_name# por defecto el nombre de Challonge
#         stats[pid] = {"jugador": nombre, "matches": 0, "wins": 0, "losses": 0, "draws": 0}

#     # Contar matches
#     for m in matches:
#         p1, p2 = m["player1_id"], m["player2_id"]
#         winner, loser = m.get("winner_id"), m.get("loser_id")

#         for pid in [p1, p2]:
#             if pid in stats:
#                 stats[pid]["matches"] += 1

#         if winner in stats:
#             stats[winner]["wins"] += 1
#         if loser in stats:
#             stats[loser]["losses"] += 1

#     # Calcular winrate
#     for s in stats.values():
#         if s["matches"] > 0:
#             s["winrate"] = round(s["wins"] / s["matches"] * 100, 2)
#         else:
#             s["winrate"] = 0.0

#     # Convertir a lista de diccionarios y ordenar por winrate descendente
#     lista_stats = list(stats.values())
#     lista_stats.sort(key=lambda x: x["winrate"], reverse=True)
#     return lista_stats

# # stats_jugadores es lista de dicts
# def calcular_stats_arquetipos(stats_jugadores, mapping_arquetipos):
#     stats_arq = {}

#     for s in stats_jugadores:
#         nombre = s["jugador"]
#         archetype = mapping_arquetipos.get(nombre, "Rogue")  # Default Rogue
#         if archetype not in stats_arq:
#             stats_arq[archetype] = {"matches": 0, "wins": 0, "losses": 0}

#         stats_arq[archetype]["matches"] += s["matches"]
#         stats_arq[archetype]["wins"] += s["wins"]
#         stats_arq[archetype]["losses"] += s["losses"]

#     # calcular winrate
#     for s in stats_arq.values():
#         if s["matches"] > 0:
#             s["winrate"] = round(s["wins"] / s["matches"] * 100, 2)
#         else:
#             s["winrate"] = 0.0
#     return stats_arq

# # 🎨 Generar gráfico Plotly y devolver buffer PNG
# def generar_grafico(df: pd.DataFrame, x: str, y: str, color: str, titulo: str):
#     fig = px.bar(df, x=x, y=y, color=color, text=y, title=titulo)
#     fig.update_traces(textposition="outside")
#     buf = io.BytesIO()
#     fig.write_image(buf, format="png")
#     buf.seek(0)
#     return buf

# # 🏗 Handler principal
# async def stats_handle(ctx):
#     await borrar_mensaje_seguro(ctx)

#     torneo_id = await obtener_torneo_usuario(ctx, mensaje_inicial="Elige el torneo para ver estadísticas:")
#     if not torneo_id:
#         await ctx.author.send("❌ No se seleccionó un torneo.")
#         return

#     await ctx.author.send(
#         "**¿Qué estadísticas quieres ver?**\n"
#         "1️⃣ Jugadores\n"
#         "2️⃣ Arquetipos\n"
#         "✍️ Responde con 1 o 2:"
#     )

#     def check(m): return m.author == ctx.author and m.content.strip() in ["1", "2"]

#     try:
#         resp = await ctx.bot.wait_for("message", check=check, timeout=60)
#         opcion = resp.content.strip()

#         participants = await get_participants(torneo_id)
#         matches = await get_matches(torneo_id)
#         mapping_arquetipos = await get_arquetipos(ctx.guild)

#         stats_jugadores = calcular_stats_jugadores(participants, matches, ctx.guild)
#         if opcion == "1":  # 📊 Jugadores
#             df = pd.DataFrame(stats_jugadores)

#             # Ordenar por winrate de mayor a menor
#             df = df.sort_values(by="winrate", ascending=False)

#             # Generar gráfico usando 'jugador' para eje X y color
#             buf = generar_grafico(df, x="jugador", y="winrate", color="jugador", titulo="Winrate por jugador")
#             file = discord.File(buf, filename="stats_jugadores.png")

#             embed = discord.Embed(title="📊 Estadísticas por jugador", color=discord.Color.green())
#             embed.set_image(url="attachment://stats_jugadores.png")
#             await ctx.author.send(embed=embed, file=file)
          
          

       
#         elif opcion == "2":  # 📊 Arquetipos
#             stats_arq = calcular_stats_arquetipos(stats_jugadores, mapping_arquetipos)
#             buf = generar_grafico_pie(stats_arq, titulo="Distribución de partidas por arquetipo")
#             file = discord.File(buf, filename="stats_arquetipos.png")

#             embed = discord.Embed(title="📊 Estadísticas por arquetipo", color=discord.Color.blue())
#             embed.set_image(url="attachment://stats_arquetipos.png")
#             await ctx.author.send(embed=embed, file=file)

#     except asyncio.TimeoutError:
#         await ctx.author.send("⌛ Tiempo agotado. Vuelve a usar `!stats`.")

# def generar_grafico_pie(stats_arq: dict, titulo: str):
#     labels = []
#     values = []

#     for archetype, s in stats_arq.items():
#         labels.append(archetype)
#         values.append(s["matches"])  # puedes usar 'matches' o 'wins'

#     fig = px.pie(names=labels, values=values, title=titulo)
#     fig.update_traces(textposition='inside', textinfo='percent+label')
    
#     buf = io.BytesIO()
#     fig.write_image(buf, format="png")
#     buf.seek(0)
#     return buf
