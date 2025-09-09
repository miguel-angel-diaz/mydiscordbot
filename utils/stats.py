import aiohttp
import discord
import asyncio
import matplotlib.pyplot as plt
import io
import config
from utils.commons import borrar_mensaje_seguro, validar_canal_correcto, buscar_usuario_en_servidor, obtener_torneo_usuario

# Función para generar gráfico de winrate
async def generar_grafico_winrate(stats: dict, titulo: str = "Winrate"):
    valores = [stats.get("wins", 0), stats.get("losses", 0), stats.get("draws", 0)]
    total = sum(valores)

    fig, ax = plt.subplots()
    if total > 0:
        ax.pie(valores, labels=["Victorias", "Derrotas", "Empates"], autopct="%1.1f%%", startangle=90)
    else:
        ax.text(0.5, 0.5, "Sin partidas", ha="center", va="center", fontsize=14)
    ax.set_title(titulo)

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close(fig)
    return buf

# Función para obtener participant_id en un torneo
async def get_participant_id(torneo_id: str, jugador: discord.Member):
    url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/participants.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            for p in data:
                nombre = (p["participant"].get("name") or "").lower()
                if str(jugador.id) in nombre or jugador.display_name.lower() in nombre:
                    return p["participant"]["id"]
    return None

# Función para obtener matches de un torneo
async def challonge_get_matches(torneo_id: str, participant_id: int = None):
    url = f"https://api.challonge.com/v1/tournaments/{torneo_id}/matches.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            matches = []
            for m in data:
                match = m.get("match", {})
                if participant_id is None or participant_id in (match.get("player1_id"), match.get("player2_id")):
                    matches.append(match)
            return matches

# Estadísticas por jugador en torneo
async def stats_por_jugador(guild, torneo_id: str, jugador: discord.Member):
    participant_id = await get_participant_id(torneo_id, jugador)
    if not participant_id:
        return None

    matches = await challonge_get_matches(torneo_id, participant_id)
    stats = {"jugador": jugador.display_name, "matches": 0, "wins": 0, "losses": 0, "draws": 0, "winrate": 0.0}

    for m in matches:
        stats["matches"] += 1
        if m.get("winner_id") == participant_id:
            stats["wins"] += 1
        elif m.get("loser_id") == participant_id:
            stats["losses"] += 1
        else:
            stats["draws"] += 1

    if stats["matches"] > 0:
        stats["winrate"] = round(stats["wins"] / stats["matches"] * 100, 2)

    return stats

# Estadísticas por arquetipo en torneo
async def stats_por_arquetipo(guild, torneo_id: str):
    canal_submitted = discord.utils.get(guild.text_channels, name="submitted-decks")
    if not canal_submitted:
        return {}

    arquetipos = {}
    async for mensaje in canal_submitted.history(limit=500):
        for embed in mensaje.embeds:
            campos = {field.name.lower(): field.value for field in embed.fields}
            archetype = campos.get("archetype", "Desconocido")
            jugador_id = campos.get("jugador_id")
            if jugador_id not in arquetipos:
                arquetipos[jugador_id] = {}
            arquetipos[jugador_id][archetype] = arquetipos[jugador_id].get(archetype, 0) + 1

    return arquetipos

# Handler principal
async def stats_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    torneo_id = await obtener_torneo_usuario(ctx, mensaje_inicial="Elige el torneo para ver las estadísticas:")
    if not torneo_id:
        await ctx.author.send("❌ No se seleccionó un torneo.")
        return

    await ctx.author.send(
        "**¿Qué estadísticas quieres ver?**\n"
        "1️⃣ Por jugador\n"
        "2️⃣ Por arquetipo\n"
        "✍️ Responde con 1 o 2:"
    )

    def check_numero(m):
        return m.author == ctx.author and m.content.strip() in ["1", "2"]

    try:
        respuesta = await ctx.bot.wait_for("message", check=check_numero, timeout=60)
        opcion = respuesta.content.strip()

        if opcion == "1":
            await ctx.author.send("✍️ Escribe el nombre o apodo del jugador:")
            def check_jugador(m):
                return m.author == ctx.author
            respuesta_j = await ctx.bot.wait_for("message", check=check_jugador, timeout=90)
            jugador = buscar_usuario_en_servidor(ctx.guild, respuesta_j.content.strip())
            if not jugador:
                await ctx.author.send("⚠️ No se encontró el jugador.")
                return

            stats = await stats_por_jugador(ctx.guild, torneo_id, jugador)
            grafico_buf = await generar_grafico_winrate(stats, f"Winrate de {jugador.display_name}")
            file = discord.File(fp=grafico_buf, filename="winrate.png")
            embed = discord.Embed(title=f"📊 Stats de {jugador.display_name}", color=discord.Color.green())
            for k, v in stats.items():
                if k != "jugador":
                    embed.add_field(name=k.capitalize(), value=str(v))
            embed.set_image(url="attachment://winrate.png")
            await ctx.author.send(embed=embed, file=file)

        elif opcion == "2":
            arquetipos = await stats_por_arquetipo(ctx.guild, torneo_id)
            texto = "**Estadísticas por arquetipo:**\n"
            for jugador_id, archetypes in arquetipos.items():
                texto += f"\n<@{jugador_id}>:\n"
                for archetype, cantidad in archetypes.items():
                    texto += f"- {archetype}: {cantidad} partidas\n"
            await ctx.author.send(texto)

    except asyncio.TimeoutError:
        await ctx.author.send("⌛ Tiempo agotado. Vuelve a usar `!stats`.")
