from discord.ext import tasks, commands
from datetime import datetime
import discord
import re

from utils.torneos import comenzar_evento_handle

ultima_ejecucion_eventos = None

def cargar_tareas(bot):
    publicar_eventos_diarios.start(bot)
    limpiar_partidos_pasados.start(bot)
    iniciar_torneos_programados.start(bot)
    publicar_torneos_activos_diarios.start(bot)


@tasks.loop(minutes=1)
async def publicar_eventos_diarios(bot):
    global ultima_ejecucion_eventos

    ahora = datetime.now()

    # Solo entre las 10:00 y 10:15
    if not (ahora.hour == 10 and ahora.minute <= 15):
        return

    hoy = ahora.date()

    # Ya se ejecutó hoy
    if ultima_ejecucion_eventos == hoy:
        return

    # Marca que ya se ejecutó
    ultima_ejecucion_eventos = hoy

    for guild in bot.guilds:
        canal_origen = discord.utils.get(guild.text_channels, name="partidos-agendados")
        canal_destino = discord.utils.get(guild.text_channels, name="proximas-partidas")

        if not canal_origen or not canal_destino:
            continue

        eventos_hoy = []
        patron = re.compile(
            r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
        )

        async for mensaje in canal_origen.history(limit=100):
            if not mensaje.content.startswith("📅 [EVENTO]"):
                continue

            match = patron.search(mensaje.content)
            if not match:
                continue

            fecha_str, hora_str, jugador1, jugador2 = match.groups()
            try:
                fecha_completa = datetime.strptime(f"{fecha_str} {hora_str}", "%d/%m/%Y %H:%M")
            except ValueError:
                continue

            if fecha_completa.date() == hoy:
                eventos_hoy.append((fecha_completa.strftime("%H:%M"), jugador1.strip(), jugador2.strip()))

        if not eventos_hoy:
            await canal_destino.send("📭 No hay partidas programadas para hoy.")
            continue

        embed = discord.Embed(
            title="📅 Partidas programadas para hoy",
            color=discord.Color.blue()
        )
        for hora, jugador1, jugador2 in sorted(eventos_hoy):
            embed.add_field(name=hora, value=f"{jugador1} vs {jugador2}", inline=False)

        await canal_destino.send(embed=embed)

@tasks.loop(minutes=1)
async def publicar_torneos_activos_diarios(bot):
    global ultima_ejecucion
    now = datetime.now()

    # Ejecutar solo entre las 10:00 y 10:15 una vez al día
    if not (now.hour == 10 and now.minute <= 15):
        return

    hoy = now.date()

    if ultima_ejecucion == hoy:
        return  # Ya se ejecutó hoy

    for guild in bot.guilds:
        canal_origen = discord.utils.get(guild.text_channels, name="torneos-activos")
        canal_destino = discord.utils.get(guild.text_channels, name="anuncios-torneos")

        if not canal_origen or not canal_destino:
            continue

        mensajes_torneos = []

        async for msg in canal_origen.history(limit=100):
            if (
                msg.author == guild.me and
                "código:" in msg.content.lower() and
                msg.content.count("`") >= 10
            ):
                mensajes_torneos.append(msg.content)

        if not mensajes_torneos:
            await canal_destino.send("📭 No hay torneos activos actualmente.")
            continue

        await canal_destino.send("🎯 **Torneos activos actualmente:**")
        for torneo in mensajes_torneos:
            await canal_destino.send(torneo)

@tasks.loop(minutes=1)
async def limpiar_partidos_pasados(bot):
    global ultima_ejecucion
    now = datetime.now()

    # Ejecutar solo entre las 10:00 y 10:15 una vez al día
    if not (now.hour == 10 and now.minute <= 15):
        return

    hoy = now.date()

    if ultima_ejecucion == hoy:
        return  # Ya se ejecutó hoy
    
    for guild in bot.guilds:
        canal_partidos = discord.utils.get(guild.text_channels, name="partidos-agendados")
        if not canal_partidos:
            continue

        patron_fecha = re.compile(r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})")

        async for mensaje in canal_partidos.history(limit=200):
            match = patron_fecha.search(mensaje.content)
            if not match:
                continue

            fecha_str = match.group(1)
            try:
                fecha_mensaje = datetime.strptime(fecha_str, "%d/%m/%Y").date()
            except ValueError:
                continue

            if fecha_mensaje < now.date():
                try:
                    await mensaje.delete()
                except discord.Forbidden:
                    print(f"No tengo permisos para borrar mensaje en {canal_partidos.name} del servidor {guild.name}")
                except discord.NotFound:
                    pass  # Mensaje ya borrado
                except Exception as e:
                    print(f"Error borrando mensaje: {e}")
            
@tasks.loop(minutes=1)
async def iniciar_torneos_programados(bot):
    global ultima_ejecucion
    now = datetime.now()

    # Ejecutar solo entre las 10:00 y 10:15 una vez al día
    if now.weekday() != 0 or not (now.hour == 10 and now.minute <= 5):
        return

    hoy = now.date()

    if ultima_ejecucion == hoy:
        return  # Ya se ejecutó hoy

    for guild in bot.guilds:
        canal_torneos = discord.utils.get(guild.text_channels, name="torneos-activos")
        canal_iniciados = discord.utils.get(guild.text_channels, name="torneos-iniciados")
        canal_emparejamientos = discord.utils.get(guild.text_channels, name="emparejamientos")

        if not canal_torneos or not canal_iniciados or not canal_emparejamientos:
            continue

        patron = re.compile(r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` \| código: `(\w{6})`")

        async for msg in canal_torneos.history(limit=100):
            match = patron.search(msg.content)
            if not match:
                continue

            nombre = match.group(1)
            fecha_str = match.group(2)
            codigo = match.group(5).upper()

            try:
                fecha_torneo = datetime.strptime(fecha_str, "%d/%m/%Y").date()
            except ValueError:
                continue

            if fecha_torneo != now.date():
                continue  # Solo torneos con fecha de hoy

            # Verificar si ya está iniciado en #torneos-iniciados
            ya_iniciado = False
            async for m_iniciado in canal_iniciados.history(limit=100):
                if f"`{codigo}`" in m_iniciado.content:
                    ya_iniciado = True
                    break

            if ya_iniciado:
                continue  # Ya iniciado previamente

            # Simular contexto con el owner del servidor
            dummy_msg = await canal_emparejamientos.send(f"🤖 Iniciando torneo `{codigo}` automáticamente...")
            ctx = commands.Context(
                bot=bot,
                message=dummy_msg,
                guild=guild,
                author=guild.owner,
                channel=canal_emparejamientos
            )

            # Iniciar el torneo (sin set)
            await comenzar_evento_handle(ctx, codigo)