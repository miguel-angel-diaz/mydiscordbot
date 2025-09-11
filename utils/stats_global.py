import discord
import asyncio
import aiohttp
import matplotlib.pyplot as plt
import seaborn as sns
import io
import config
import re
from utils.commons import borrar_mensaje_seguro, buscar_usuario_en_servidor

sns.set(style="whitegrid")  # Estilo Seaborn para gráficos

# 🔹 Obtener torneos finalizados
async def get_torneos_finalizados():
    url = "https://api.challonge.com/v1/tournaments.json?state=complete"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return []
            return await resp.json()

# 🔹 Obtener participantes
async def get_participants(torneo_id: str):
    url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/participants.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return [p["participant"] for p in data]

# 🔹 Obtener matches
async def get_matches(torneo_id: str):
    url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/matches.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return [m["match"] for m in data]

async def get_arquetipos(guild: discord.Guild):
    print("[DEBUG] Obteniendo arquetipos desde #submitted-decks")
    canal = discord.utils.get(guild.text_channels, name="submitted-decks")
    mapping = []
    if not canal:
        return mapping

    async for msg in canal.history(limit=500):
        for embed in msg.embeds:
            if not embed.fields:
                continue

            # Construir dict de campos
            campos = {field.name.lower(): field.value for field in embed.fields}

            # Extraer jugador e ID
            jugador_field = campos.get("jugador")
            if not jugador_field:
                continue
            try:
                jugador_id_str = jugador_field.split("(ID:")[1].replace(")", "").strip()
                jugador_id = int(jugador_id_str)
            except (IndexError, ValueError):
                continue

            miembro = guild.get_member(jugador_id)
            nombre_jugador = miembro.display_name if miembro else jugador_field.split("(")[0].strip()

            # Extraer otros campos
            deck = campos.get("decklist", "Unknown Deck")
            torneo = campos.get("torneo", "Unknown Torneo")
            archetype = campos.get("archetype", "Rogue")
            codigo_match = re.search(r'`(.+?)`', embed.description or "")
            codigo = codigo_match.group(1) if codigo_match else "Unknown"

        deck_obj = {
            "jugador": nombre_jugador,
            "torneo": torneo,
            "deck": deck,
            "archetype": archetype,
            "codigo": codigo
        }

        # Lo añadimos al array global de decks
        mapping.append(deck_obj)
    return mapping

async def calcular_stats_global(jugador_discord, guild):
    torneos = await get_torneos_finalizados()
    resumen_global = {
        "jugador": jugador_discord.display_name,
        "matches": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "oponentes": {},
        "arquetipos": {}
    }

    mapping_arquetipos = await get_arquetipos(guild)

    for torneo in torneos:
        torneo_name = torneo["tournament"]["url"]
      

        participants = await get_participants(torneo["tournament"]["id"])
        matches = await get_matches(torneo["tournament"]["id"])

        # Buscar participante en este torneo
        participante = next((p for p in participants if str(jugador_discord.id) == p["name"]), None)
        if not participante:
            continue
        pid = participante["id"]
        namejugador = participante["name"]

      

        decks = []
        for d in mapping_arquetipos:
            jugador = d.get("jugador", "Unknown")
            torneo_d = limpiar_torneo(d.get("torneo", ""))
            
            print(f"[TRACE] Revisando deck -> jugador='{jugador}', torneo='{torneo_d}', archetype='{d.get('archetype', 'N/A')}'")

            if jugador == namejugador and torneo_d == torneo_name:
                print(f"[TRACE] ✅ Coincidencia encontrada -> {d}")
                decks.append(d)
            else:
                print(f"[TRACE] ❌ No coincide -> jugador_ok={jugador == namejugador}, torneo_ok={torneo_d == torneo_name}")

        print(f"[TRACE] Resultado final de decks encontrados: {decks}")
        deck_jugador = decks[0]["archetype"] if decks else "Unknown Deck"
        codigo_torneo = decks[0]["codigo"] if decks else "Unknown"

        print(f"[DEBUG] Torneo: {torneo_name}, Jugador: {namejugador}, Deck seleccionado: {deck_jugador}, Código: {codigo_torneo}")

        # Procesar partidas
        for m in matches:
            p1, p2 = m["player1_id"], m["player2_id"]
            winner, loser = m.get("winner_id"), m.get("loser_id")
            opponent_id = p2 if p1 == pid else p1 if p2 == pid else None
            if not opponent_id:
                continue

            oponente = next((p for p in participants if p["id"] == opponent_id), None)
            nombre_oponente = oponente["name"] if oponente else f"Desconocido ({opponent_id})"

            # Inicializar stats de oponente
            resumen_global["oponentes"].setdefault(nombre_oponente, {"matches":0,"wins":0,"losses":0,"draws":0,"vs_decks":{}})

            resumen_global["oponentes"][nombre_oponente]["matches"] += 1

            if winner == pid:
                resumen_global["wins"] += 1
                resumen_global["oponentes"][nombre_oponente]["wins"] += 1
            elif loser == pid:
                resumen_global["losses"] += 1
                resumen_global["oponentes"][nombre_oponente]["losses"] += 1
            else:
                resumen_global["draws"] += 1
                resumen_global["oponentes"][nombre_oponente]["draws"] += 1

            # Obtener arquetipo del oponente en este torneo
            oponente_decks = [d for d in mapping_arquetipos.get(nombre_oponente, []) if d["torneo"] == torneo_name]
            arquetipo_oponente = oponente_decks[0]["archetype"] if oponente_decks else "Rogue"

            # Actualizar stats por arquetipo
            if arquetipo_oponente not in resumen_global["arquetipos"]:
                resumen_global["arquetipos"][arquetipo_oponente] = {"matches":0,"wins":0,"losses":0,"vs":{}}
            resumen_global["arquetipos"][arquetipo_oponente]["matches"] += 1
            if winner == pid:
                resumen_global["arquetipos"][arquetipo_oponente]["wins"] += 1
            elif loser == pid:
                resumen_global["arquetipos"][arquetipo_oponente]["losses"] += 1

            # Stats vs decks
            resumen_global["arquetipos"][arquetipo_oponente]["vs"].setdefault(deck_jugador, {"matches":0,"wins":0,"losses":0})
            resumen_global["arquetipos"][arquetipo_oponente]["vs"][deck_jugador]["matches"] += 1
            if winner == pid:
                resumen_global["arquetipos"][arquetipo_oponente]["vs"][deck_jugador]["wins"] += 1
            elif loser == pid:
                resumen_global["arquetipos"][arquetipo_oponente]["vs"][deck_jugador]["losses"] += 1

    resumen_global["matches"] = resumen_global["wins"] + resumen_global["losses"] + resumen_global["draws"]
    return resumen_global

def limpiar_torneo(nombre):
    # Eliminamos asteriscos, backticks y espacios al inicio/final
    return nombre.replace("*", "").replace("`", "").strip()

# 🔹 Gráficos Matplotlib + Seaborn
def generar_grafico_winrate_global(resumen_global):
    labels = ["Victorias", "Derrotas", "Empates"]
    values = [resumen_global.get("wins",0), resumen_global.get("losses",0), resumen_global.get("draws",0)]
    plt.figure(figsize=(6,6))
    plt.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, colors=sns.color_palette("Set2"))
    plt.title("Winrate Global")
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf

def generar_grafico_oponentes(resumen_global, guild):
    oponentes = resumen_global.get("oponentes", {})
    if not oponentes:
        return None
    labels=[]
    victorias=[]
    derrotas=[]
    empates=[]
    for opp_nombre, stats in oponentes.items():
        miembro = guild.get_member(int(opp_nombre)) if opp_nombre.isdigit() else None
        nombre = miembro.display_name if miembro else opp_nombre
        labels.append(nombre)
        victorias.append(stats["wins"])
        derrotas.append(stats["losses"])
        empates.append(stats["draws"])

    plt.figure(figsize=(10,6))
    plt.bar(labels, victorias, color=sns.color_palette("Greens", n_colors=len(labels)), label="Victorias")
    plt.bar(labels, derrotas, bottom=victorias, color=sns.color_palette("Reds", n_colors=len(labels)), label="Derrotas")
    bottom2 = [v+d for v,d in zip(victorias,derrotas)]
    plt.bar(labels, empates, bottom=bottom2, color=sns.color_palette("Greys", n_colors=len(labels)), label="Empates")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Partidas")
    plt.title("Rendimiento contra oponentes")
    plt.legend()
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf

def generar_grafico_arquetipos(resumen_global):
    arquetipos = resumen_global.get("arquetipos", {})
    if not arquetipos:
        return None
    labels = list(arquetipos.keys())
    values = [v["matches"] for v in arquetipos.values()]
    plt.figure(figsize=(6,6))
    plt.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, colors=sns.color_palette("Set3"))
    plt.title("Partidas por arquetipo")
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf

# 🔹 Analizar stats de arquetipos vs deck propio
def analizar_stats_arquetipos(resumen_global):
    texto = "🏹 Desempeño por arquetipo (vs. tu deck):\n"
    deck_vs_arquetipo = resumen_global.get("deck_vs_arquetipo", {})
    for deck, arq_stats in deck_vs_arquetipo.items():
        for arq, s in arq_stats.items():
            texto += f"  • {arq}: {s['wins']}-{s['losses']} {deck}\n"
    return texto

# 🔹 Análisis textual mejorado
def analizar_trayectoria(resumen_global, jugador_nombre, guild):
    analisis = f"📊 Análisis de {jugador_nombre}\n\n"
    matches = resumen_global.get("matches",0)
    wins = resumen_global.get("wins",0)
    losses = resumen_global.get("losses",0)
    draws = resumen_global.get("draws",0)
    winrate = round(wins/matches*100,2) if matches>0 else 0.0
    analisis += f"- Partidas jugadas: {matches}\n- Victorias: {wins}\n- Derrotas: {losses}\n- Empates: {draws}\n- Winrate: {winrate}%\n\n"

    if resumen_global.get("arquetipos"):
        analisis += "🏹 Desempeño por arquetipo (vs. tu deck):\n"
        for archetype, stats in resumen_global["arquetipos"].items():
            m = stats["matches"]
            w = stats.get("wins",0)
            l = stats.get("losses",0)
            analisis += f"  • {archetype}: {w}-{l}\n"

    if resumen_global.get("oponentes"):
        analisis += "\n⚔️ Rendimiento contra oponentes:\n"
        for opp_nombre, stats in resumen_global["oponentes"].items():
            total = stats["matches"]
            if total==0: continue
            wr = round(stats.get("wins",0)/total*100,2)
            analisis += f"  • {opp_nombre}: {stats.get('wins',0)}W / {stats.get('losses',0)}L ({wr}%)\n"

    analisis += "\n💡 Consejos:\n"
    if winrate < 50:
        analisis += "- Considera revisar estrategias o arquetipos donde tienes bajo rendimiento.\n"
    else:
        analisis += "- Mantén tus estrategias actuales y analiza oponentes difíciles para mejorar aún más.\n"

    return analisis

# 🔹 Handle principal para Discord
async def stats_global_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    jugador = ctx.author

    # Administradores pueden elegir otro jugador
    if ctx.author.guild_permissions.administrator:
        await ctx.author.send("✍️ Escribe el nombre o ID del jugador a consultar:")
        def check(m): return m.author == ctx.author
        try:
            msg = await ctx.bot.wait_for("message", check=check, timeout=60)
            jugador = buscar_usuario_en_servidor(ctx.guild, msg.content.strip()) or jugador
        except asyncio.TimeoutError:
            await ctx.author.send("⌛ Tiempo agotado. Se mostrarán tus stats.")

    resumen_global = await calcular_stats_global(jugador, ctx.guild)

    # Generar gráficos
    buf_winrate = generar_grafico_winrate_global(resumen_global)
    buf_oponentes = generar_grafico_oponentes(resumen_global, ctx.guild)
    buf_arquetipos = generar_grafico_arquetipos(resumen_global)

    # Enviar gráficos
    await ctx.author.send(file=discord.File(buf_winrate, filename="winrate_global.png"))
    if buf_oponentes:
        await ctx.author.send(file=discord.File(buf_oponentes, filename="rendimiento_oponentes.png"))
    if buf_arquetipos:
        await ctx.author.send(file=discord.File(buf_arquetipos, filename="rendimiento_arquetipos.png"))

    # Enviar análisis textual
    analisis_texto = analizar_trayectoria(resumen_global, jugador.display_name, ctx.guild)
    await ctx.author.send(analisis_texto)
