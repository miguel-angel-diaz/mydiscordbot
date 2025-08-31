from discord.ext import tasks, commands
from datetime import datetime, timedelta
import discord
import re
import asyncio

ultima_ejecucion_eventos = None
ultima_ejecucion_partidos = None
ultima_ejecucion_torneos_vencidos = None

# 🔹 Función auxiliar para esperar hasta las 10:00
async def esperar_hasta_las_10():
    ahora = datetime.now()
    proxima = ahora.replace(hour=10, minute=0, second=0, microsecond=0)

    if ahora >= proxima:
        proxima += timedelta(days=1)

    espera = (proxima - ahora).total_seconds()
    await asyncio.sleep(espera)

# ==============================
# 🔹 TAREAS INDIVIDUALES
# ==============================

async def limpiar_canal_diario(bot):
    guild = discord.utils.get(bot.guilds, name="Nombre de tu servidor")  # cambia el nombre del server
    if not guild:
        return

    canal = discord.utils.get(guild.text_channels, name="preguntale-a-el-barbas")
    if not canal:
        return

    try:
        async for mensaje in canal.history(limit=None):
            if not mensaje.pinned:
                await mensaje.delete()
                await asyncio.sleep(0.3)  # evitar rate limits
    except Exception as e:
        print(f"Error al limpiar el canal: {e}")


async def publicar_eventos_semanales(bot):
    global ultima_ejecucion_eventos
    hoy = datetime.now().date()

    if ultima_ejecucion_eventos == hoy:
        return
    ultima_ejecucion_eventos = hoy

    for guild in bot.guilds:
        canal_origen = discord.utils.get(guild.text_channels, name="partidos-agendados")
        canal_proximas = discord.utils.get(guild.text_channels, name="🎭-cartelera‐")
        if not canal_origen or not canal_proximas:
            continue

        inicio_semana = hoy - timedelta(days=hoy.weekday())
        fin_semana = inicio_semana + timedelta(days=6)

        eventos_semana = []
        patron = re.compile(
            r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
        )

        async for mensaje in canal_origen.history(limit=200):
            if not mensaje.content.startswith("📅 [EVENTO]"):
                continue
            match = patron.search(mensaje.content)
            if not match:
                continue
            fecha_str, hora_str, jugador1, jugador2 = match.groups()
            try:
                fecha_obj = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                if inicio_semana <= fecha_obj <= fin_semana:
                    eventos_semana.append((fecha_obj, hora_str, jugador1.strip(), jugador2.strip()))
            except Exception:
                continue

        if not eventos_semana:
            continue

        embed = discord.Embed(
            title="📅 Partidas programadas esta semana",
            color=discord.Color.blue()
        )
        for fecha_ev, hora_ev, j1, j2 in sorted(eventos_semana):
            embed.add_field(name=f"{fecha_ev.strftime('%d/%m/%Y')} {hora_ev}", value=f"{j1} vs {j2}", inline=False)

        mensaje_existente = None
        async for msg in canal_proximas.history(limit=50):
            if msg.author == guild.me and msg.embeds:
                if msg.embeds[0].title == "📅 Partidas programadas esta semana":
                    mensaje_existente = msg
                    break

        if mensaje_existente:
            await mensaje_existente.edit(embed=embed)
        else:
            await canal_proximas.send(embed=embed)


async def limpiar_partidos_pasados(bot):
    global ultima_ejecucion_partidos
    hoy = datetime.now().date()

    if ultima_ejecucion_partidos == hoy:
        return
    ultima_ejecucion_partidos = hoy

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

            if fecha_mensaje < hoy:
                try:
                    await mensaje.delete()
                except discord.Forbidden:
                    print(f"No tengo permisos para borrar mensaje en {canal_partidos.name} del servidor {guild.name}")
                except discord.NotFound:
                    pass
                except Exception as e:
                    print(f"Error borrando mensaje: {e}")


async def limpiar_torneos_vencidos(bot):
    global ultima_ejecucion_torneos_vencidos
    hoy = datetime.now().date()

    if ultima_ejecucion_torneos_vencidos == hoy:
        return
    ultima_ejecucion_torneos_vencidos = hoy

    for guild in bot.guilds:
        canal = discord.utils.get(guild.text_channels, name="torneos-activos")
        if not canal:
            continue

        async for mensaje in canal.history(limit=200):
            if mensaje.pinned:
                continue

            for linea in mensaje.content.splitlines():
                if "Inicio" in linea:
                    match = re.search(r"\d{2}/\d{2}/\d{4}", linea)
                    if not match:
                        continue

                    fecha_str = match.group()

                    try:
                        fecha_torneo = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                    except ValueError as e:
                        print(f"⚠️ Error parseando '{fecha_str}' ({e})")
                        continue

                    limite = hoy - timedelta(days=2)

                    if fecha_torneo <= limite:
                        try:
                            await mensaje.delete()
                            await asyncio.sleep(0.3)
                        except discord.Forbidden:
                            print(f"🚫 No tengo permisos para borrar en {canal.name} ({guild.name})")
                        except discord.NotFound:
                            print("⚠️ Mensaje ya borrado")
                        except Exception as e:
                            print(f"🔥 Error borrando mensaje: {e}")


# ==============================
# 🔹 LOOP PRINCIPAL A LAS 10:00
# ==============================
@tasks.loop(hours=24)
async def ejecutar_tareas(bot):
    await bot.wait_until_ready()

    # Esperar hasta las 10:00 cada día
    await esperar_hasta_las_10()

    # Ejecutar todas las tareas
    await limpiar_canal_diario(bot)
    await publicar_eventos_semanales(bot)
    await limpiar_partidos_pasados(bot)
    await limpiar_torneos_vencidos(bot)

# 🔹 Arrancar el loop
def cargar_tareas(bot):
    ejecutar_tareas.start(bot)
