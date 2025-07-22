from discord.ext import tasks, commands
from datetime import datetime
import discord
import re



ultima_ejecucion_eventos = None
ultima_ejecucion_torneos = None
ultima_ejecucion = None

def cargar_tareas(bot):
    publicar_eventos_diarios.start(bot)
    limpiar_partidos_pasados.start(bot)


@tasks.loop(minutes=1)
async def publicar_eventos_diarios(bot):
    global ultima_ejecucion_eventos

    ahora = datetime.now()

    # Solo entre las 10:00 y 10:15
    if not (ahora.hour == 10 and ahora.minute <= 25):
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
async def limpiar_partidos_pasados(bot):
    global ultima_ejecucion
    now = datetime.now()

    # Ejecutar solo entre las 10:00 y 10:15 una vez al día
    if not (now.hour == 10 and now.minute <= 25):
        return

    hoy = now.date()

    if ultima_ejecucion == hoy:
        return  # Ya se ejecutó hoy
    
    ultima_ejecucion = hoy
    
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
            

           