import discord
from discord.ext import commands
from discord.ext import tasks
from discord.ext.commands import CommandNotFound, MemberNotFound, CommandInvokeError
from datetime import datetime, timedelta

import asyncio
import requests
import re
import os
import webserver
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

intentos_fallidos = {}
MAX_ERRORES = 4
TIEMPO_LIMITE_MINUTOS = 10

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.command(name="agendar-partida")
async def agendar_partida(ctx, fecha: str = None, hora: str = None, jugador1: discord.Member = None, _vs: str = None, jugador2: discord.Member = None):
    # ✅ Verificar canal
    if ctx.channel.name != "agenda":
        await ctx.send("❌ Este comando solo se puede usar en el canal `#agenda`.")
        return

    errores = []

    # Validar fecha
    if not fecha:
        errores.append("• Falta la **fecha**. Formato esperado: `dd/mm/yyyy`")
    else:
        try:
            datetime.strptime(fecha, "%d/%m/%Y")
        except ValueError:
            errores.append(f"• Fecha inválida (`{fecha}`). Usa el formato `dd/mm/yyyy`")

    # Validar hora
    if not hora:
        errores.append("• Falta la **hora**. Formato esperado: `hh:mm`")
    else:
        try:
            datetime.strptime(hora, "%H:%M")
        except ValueError:
            errores.append(f"• Hora inválida (`{hora}`). Usa el formato `hh:mm`")

    # Validar jugadores
    if not jugador1:
        errores.append("• Falta el **jugador 1** (`@mención`)")
    if not jugador2:
        errores.append("• Falta el **jugador 2** (`@mención`)")

    # Validar palabra "vs"
    if _vs is None or _vs.lower() != "vs":
        errores.append("• Falta la palabra clave **vs** entre los jugadores")

    # Si hay errores, mostrar todos de forma clara
    if errores:
        mensaje = "❌ Comando incorrecto. Revisa los siguientes errores:\n\n"
        mensaje += "\n".join(errores)
        mensaje += "\n\n✅ **Ejemplo correcto:** `!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`"
        await ctx.send(mensaje)

        # Registrar intento fallido
        await manejar_error_de_agendamiento(ctx)
        return

    # ✅ Canal destino
    canal_destino = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal_destino:
        await ctx.send("❌ No se encontró el canal `#partidos-agendados`.")
        return

    # Crear mensaje
    mensaje = (
        f"📅 [EVENTO] {fecha} {hora} | {jugador1.mention} vs {jugador2.mention} | "
        f"Agendado por {ctx.author.mention}"
    )

    await canal_destino.send(mensaje)
    await ctx.send("✅ La partida ha sido agendada correctamente en `#partidos-agendados`.")

    # Limpiar errores si acierta
    if ctx.author.id in intentos_fallidos:
        del intentos_fallidos[ctx.author.id]

async def manejar_error_de_agendamiento(ctx):
    ahora = datetime.now()
    usuario_id = ctx.author.id

    # Inicializar lista si es la primera vez
    intentos = intentos_fallidos.get(usuario_id, [])

    # Filtrar solo intentos dentro de los últimos 10 minutos
    intentos = [t for t in intentos if ahora - t < timedelta(minutes=TIEMPO_LIMITE_MINUTOS)]
    intentos.append(ahora)
    intentos_fallidos[usuario_id] = intentos

    intentos_restantes = MAX_ERRORES - len(intentos)

    mensaje = (
        f"❌ **Comando incorrecto.** Asegúrate de usar este formato:\n"
        "`!agendar-partida dd/mm/yyyy hh:mm @Jugador1 vs @Jugador2`\n"
        f"🔄 Ejemplo: `!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`\n\n"
        f"⚠️ Tienes {intentos_restantes} intento(s) antes de recibir el rol **Strike**."
    )

    await ctx.send(mensaje)

    if len(intentos) >= MAX_ERRORES:
        # Asignar el rol "strike" si no lo tiene ya
        rol_strike = discord.utils.get(ctx.guild.roles, name="Strike")
        if rol_strike and rol_strike not in ctx.author.roles:
            await ctx.author.add_roles(rol_strike)
            await ctx.send(f"🚫 {ctx.author.mention}, has cometido demasiados errores. Se te ha asignado el rol **Strike**.")

@bot.command(name="eventos-hoy")
async def eventos_hoy(ctx):
    canal = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal:
        await ctx.send("❌ No se encontró el canal `#partidos-agendados`.")
        return

    hoy = datetime.now().date()
    eventos_hoy = []

    # Expresión regular para extraer la información del mensaje
    patron = re.compile(
        r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
    )

    async for mensaje in canal.history(limit=100):
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
        await ctx.send("📭 No hay eventos agendados para hoy.")
        return

    # Crear embed resumen
    embed = discord.Embed(title="📅 Partidas de hoy", color=discord.Color.green())
    for hora, jugador1, jugador2 in sorted(eventos_hoy):
        embed.add_field(name=hora, value=f"{jugador1} vs {jugador2}", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="strike")
@commands.has_permissions(manage_roles=True)  # Asegura permisos básicos
async def asignar_strike(ctx, miembro: discord.Member = None):
    autor = ctx.author
    servidor = ctx.guild

    # Validación básica
    if miembro is None:
        await ctx.send("❌ Debes mencionar a un usuario. Ejemplo: `!strike @Usuario`")
        return

    # Comprobar si autor es el dueño o tiene rol "moderador"
    autor = ctx.author
    servidor = ctx.guild

    # Chequeo de permisos
    es_dueno = autor == servidor.owner
    rol_moderador = discord.utils.get(servidor.roles, name="moderador")
    tiene_permiso = es_dueno or (rol_moderador and rol_moderador in autor.roles)

    if not tiene_permiso:
        await asignar_strike(ctx)
        return


    # Buscar el rol strike
    rol_strike = discord.utils.get(servidor.roles, name="Strike")
    if not rol_strike:
        await ctx.send("⚠️ El rol `Strike` no existe en el servidor.")
        return

    # Evitar que se repita
    if rol_strike in miembro.roles:
        await ctx.send(f"ℹ️ {miembro.mention} ya tiene el rol `Strike`.")
        return

    try:
        await miembro.add_roles(rol_strike, reason="Strike manual asignado por moderador.")
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para asignar el rol. Revisa la jerarquía de roles.")
        return

    # ✅ Enviar mensaje privado al usuario
    mensaje_strike = (
        "Oye... te lo voy a decir solo una vez.\n\n"
        "Lo que hiciste, no va con las reglas de The Klub. Aquí se viene a respetar la energía, la gente y el espacio. "
        "No te echamos hoy... pero la próxima, estás fuera sin saludo ni explicación.\n\n"
        "Este sitio no es un “vale todo”. Es un “vale lo que yo diga”.\n"
        "Y tú ya estás en tu última vida.\n\n"
        "Decide bien cuál va a ser tu siguiente movimiento."
    )

    try:
        await miembro.send(mensaje_strike)
    except discord.Forbidden:
        await ctx.send(f"⚠️ {miembro.mention} no tiene los mensajes privados habilitados.")

    # ✅ Confirmación en canal
    await ctx.send(f"✅ {miembro.mention} ha recibido un **Strike**.")

@bot.command(name="out")
@commands.has_permissions(manage_roles=True)  # Asegura permisos básicos
async def asignar_strike(ctx, miembro: discord.Member = None):
    autor = ctx.author
    servidor = ctx.guild

    # Chequeo de permisos
    es_dueno = autor == servidor.owner
    rol_moderador = discord.utils.get(servidor.roles, name="moderador")
    tiene_permiso = es_dueno or (rol_moderador and rol_moderador in autor.roles)

    if not tiene_permiso:
        await asignar_strike(ctx)
        return


    # Validación básica
    if miembro is None:
        await ctx.send("❌ Debes mencionar a un usuario. Ejemplo: `!out @Usuario`")
        return

    # Comprobar si autor es el dueño o tiene rol "moderador"
    es_dueno = autor == servidor.owner
    rol_moderador = discord.utils.get(servidor.roles, name="Moderador")
    tiene_permiso = es_dueno or (rol_moderador in autor.roles)

    if not tiene_permiso:
        await ctx.send("🚫 No tienes permisos para usar este comando.")
        return

    # Buscar el rol strike
    rol_out = discord.utils.get(servidor.roles, name="Out")
    if not rol_out:
        await ctx.send("⚠️ El rol `Out` no existe en el servidor.")
        return

    # Evitar que se repita
    if rol_out in miembro.roles:
        await ctx.send(f"ℹ️ {miembro.mention} ya tiene el rol `Out`.")
        return

    try:
        await miembro.add_roles(rol_out, reason="Out manual asignado por moderador.")
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para asignar el rol. Revisa la jerarquía de roles.")
        return

    # ✅ Enviar mensaje privado al usuario
    mensaje_strike = (
        "Escúchame bien, campeón. No fue solo la pinta, ni que vinieras en grupo, ni que te colaras en la fila. Fue todo. La energía, la actitud, el rollo. Este sitio tiene su código, su vibra... y tú no venías ni en la misma frecuencia.\n\n"
        "Así que no, no vas a entrar. No hoy, no mañana, no el próximo eclipse lunar. Puedes venir disfrazado de unicornio o vestido en látex con lentejuelas bendecidas por los dioses del techno… pero ya cruzaste la línea.\n\n"
        "Este club no es para todos. Es para los que son. Y tú... tú simplemente no eres.\n"
    )

    try:
        await miembro.send(mensaje_strike)
    except discord.Forbidden:
        await ctx.send(f"⚠️ {miembro.mention} no tiene los mensajes privados habilitados.")

    # ✅ Confirmación en canal
    await ctx.send(f"✅ {miembro.mention} ha sido expulsado de la comunidad.")

@tasks.loop(minutes=1)
async def publicar_eventos_diarios():
    now = datetime.now()
    if now.hour != 10 or now.minute != 00:
        return  # Solo ejecuta exactamente a las 13:10

    for guild in bot.guilds:
        canal_origen = discord.utils.get(guild.text_channels, name="partidos-agendados")
        canal_destino = discord.utils.get(guild.text_channels, name="proximas-partidas")

        if not canal_origen or not canal_destino:
            continue  # Saltar si faltan los canales

        hoy = now.date()
        eventos_hoy = []

        # Regex para detectar línea de evento
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

        # Crear embed
        embed = discord.Embed(
            title="📅 Partidas programadas para hoy",
            color=discord.Color.blue()
        )
        for hora, jugador1, jugador2 in sorted(eventos_hoy):
            embed.add_field(name=hora, value=f"{jugador1} vs {jugador2}", inline=False)

        await canal_destino.send(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        mensaje = (
            "❌ **Comando no reconocido.**\n\n"
            "**Comandos disponibles:**\n"
            "• `!agendar-partida dd/mm/yyyy hh:mm @Jugador1 vs @Jugador2`\n"
            "   → Agenda una nueva partida en el canal `#partidos-agendados`\n\n"
            "• `!eventos-hoy`\n"
            "   → Muestra las partidas agendadas para hoy\n\n"
            "_Ejemplo:_\n"
            "`!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`"
        )
        await ctx.send(mensaje)

    else:
        # Para otros errores (opcional: muestra o loguea el error real)
        raise error  # Puedes quitar esto si no quieres que lo muestre en consola

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, CommandNotFound):
        await ctx.send(
            "❌ **Comando no reconocido.**\n"
            "Usa por ejemplo:\n"
            "`!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`\n"
            "`!eventos-hoy`"
        )
        return

    if isinstance(error, MemberNotFound):
        await ctx.send(
            "❌ Uno de los jugadores no se encuentra en el servidor o no fue mencionado correctamente.\n\n"
            "✅ **Asegúrate de usar el formato correcto:**\n"
            "`!agendar-partida dd/mm/yyyy hh:mm @Jugador1 vs @Jugador2`\n"
            "_Ejemplo:_ `!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`"
        )
        # Registrar intento fallido si quieres penalizar
        await manejar_error_de_agendamiento(ctx)
        return

    # Otros errores (ej. errores en el código)
    if isinstance(error, CommandInvokeError):
        original = error.original
        if isinstance(original, MemberNotFound):
            await ctx.send(
                "❌ No se pudo encontrar a uno de los jugadores mencionados. Usa `@mención` correctamente."
            )
            return

    # Imprime el error para debug y opcionalmente lo relanza
    print(f"[ERROR] {error.__class__.__name__}: {error}")
    # raise error  # Puedes comentar esto si no quieres que aparezca en consola

@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user} (ID: {bot.user.id})')
    publicar_eventos_diarios.start()  # Inicia el task loop

webserver.keep_alive()  
bot.run(DISCORD_TOKEN)
