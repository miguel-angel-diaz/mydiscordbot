from discord.ext import tasks, commands
from datetime import datetime, timedelta
import discord
import re
import asyncio

from utils.torneos import iniciar_torneo_handle



ultima_ejecucion_eventos = None
ultima_ejecucion_torneos = None
ultima_ejecucion = None

def cargar_tareas(bot):
    publicar_eventos_semanales.start(bot)
    limpiar_partidos_pasados.start(bot)


@tasks.loop(minutes=1)
async def publicar_eventos_semanales(bot):
    global ultima_ejecucion_eventos

    ahora = datetime.now()

    # Solo ejecutar una vez al día, por ejemplo a las 10:00-10:25
    if not (ahora.hour == 12 and ahora.minute <= 35):
        return

    hoy = ahora.date()

    if ultima_ejecucion_eventos == hoy:
        return
    ultima_ejecucion_eventos = hoy

    for guild in bot.guilds:
        canal_origen = discord.utils.get(guild.text_channels, name="partidos-agendados")
        canal_proximas = discord.utils.get(guild.text_channels, name="proximas-partidas")

        if not canal_origen or not canal_proximas:
            continue

        # Calcular rango de semana
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
            continue  # No hay eventos esta semana

        # Crear embed
        embed = discord.Embed(
            title="📅 Partidas programadas esta semana",
            color=discord.Color.blue()
        )
        for fecha_ev, hora_ev, j1, j2 in sorted(eventos_semana):
            embed.add_field(name=f"{fecha_ev.strftime('%d/%m/%Y')} {hora_ev}", value=f"{j1} vs {j2}", inline=False)

        # Revisar si ya existe un mensaje de esta semana
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
            
@tasks.loop(minutes=1)
async def gestionar_torneos_futuros(bot):
    global ultima_ejecucion_torneos
    now = datetime.now()

    # Ejecutar solo entre las 10:00 y 10:25 una vez al día
    if not (now.hour == 10 and now.minute <= 25):
        return

    hoy = now.date()

    if ultima_ejecucion_torneos == hoy:
        return  # Ya se ejecutó hoy

    ultima_ejecucion_torneos = hoy

    for guild in bot.guilds:
        canal_anuncios = discord.utils.get(guild.text_channels, name="anuncios-torneos")
        if not canal_anuncios:
            continue

        patron_fecha = re.compile(r"📅 Inicio:\s*(\d{2}/\d{2}/\d{4})")
        patron_codigo = re.compile(r"\*\*Código:\*\*\s*`?(\S+)`?")  # Extrae el código del torneo

        async for mensaje in canal_anuncios.history(limit=200):
            lineas = mensaje.content.splitlines()

            fecha_inicio = None
            codigo_torneo = None

            for linea in lineas:
                if fecha_inicio is None:
                    match_fecha = patron_fecha.search(linea)
                    if match_fecha:
                        try:
                            fecha_inicio = datetime.strptime(match_fecha.group(1), "%d/%m/%Y").date()
                        except ValueError:
                            fecha_inicio = None
                if codigo_torneo is None:
                    match_codigo = patron_codigo.search(linea)
                    if match_codigo:
                        codigo_torneo = match_codigo.group(1)

            if fecha_inicio and fecha_inicio > hoy and codigo_torneo:
                owner = guild.owner
                try:
                    pregunta = (
                        f"📅 El torneo **{codigo_torneo}** con inicio el **{fecha_inicio.strftime('%d/%m/%Y')}** "
                        f"en el servidor **{guild.name}** está programado para eliminarse hoy.\n"
                        f"¿Quieres iniciar el torneo manualmente y evitar que se elimine?\n"
                        f"Responde con `sí` para iniciar o `no` para borrar."
                    )
                    await owner.send(pregunta)

                    def dm_check(m):
                        return (
                            m.author == owner
                            and m.guild is None
                            and m.content.lower() in ["sí", "si", "no"]
                        )

                    respuesta = await bot.wait_for("message", timeout=60.0, check=dm_check)

                    if respuesta.content.lower() in ["sí", "si"]:
                        await owner.send(f"✅ Iniciando torneo `{codigo_torneo}`...")
                        # Aquí llamamos a tu función, pasando un contexto simulado o adaptado
                        # Nota: 'ctx' no está definido, debes crear un contexto válido o modificar iniciar_torneo_handle para recibir guild y código.
                        # Por ejemplo, si tienes un contexto, úsalo, si no, tendrás que adaptar la función.
                        # Si quieres puedo ayudarte a adaptarla.
                        await iniciar_torneo_handle(guild, codigo_torneo)
                        break  # No borramos el mensaje

                    else:
                        await mensaje.delete()
                        await owner.send("🗑️ El torneo ha sido eliminado.")
                        break

                except asyncio.TimeoutError:
                    try:
                        await mensaje.delete()
                        await owner.send("⌛ No respondiste a tiempo. El torneo ha sido eliminado.")
                    except Exception as e:
                        print(f"Error eliminando tras timeout: {e}")

                except discord.Forbidden:
                    print(f"No puedo enviar DMs o borrar mensaje en {guild.name}")

                except Exception as e:
                    print(f"Error en watcher: {e}")

            # Solo procesar un torneo por mensaje