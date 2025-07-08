import discord
from discord.ext import commands
from discord.ext import tasks
from discord.ext.commands import CommandNotFound, MemberNotFound, CommandInvokeError
from datetime import datetime, timedelta

import random
import string
import asyncio
import requests
import re
import os
# import config
import webserver
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

intentos_fallidos = {}
MAX_ERRORES = 4
TIEMPO_LIMITE_MINUTOS = 10

def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))

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

    autor = ctx.author
    servidor = ctx.guild

    # Chequeo de permisos
    es_dueno = autor == servidor.owner
    rol_moderador = discord.utils.get(servidor.roles, name="Moderador")
    tiene_permiso = es_dueno or (rol_moderador and rol_moderador in autor.roles)

    if not tiene_permiso:
        await asignar_strike_automatico(ctx)
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
        await miembro.add_roles(rol_strike, reason="Strike manual asignado por Moderador.")
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

   
    es_dueno = autor == servidor.owner
    rol_moderador = discord.utils.get(servidor.roles, name="Moderador")
    tiene_permiso = es_dueno or (rol_moderador and rol_moderador in autor.roles)

    if not tiene_permiso:
        await asignar_strike_automatico(ctx)
        return

  
    if miembro is None:
        await ctx.send("❌ Debes mencionar a un usuario. Ejemplo: `!out @Usuario`")
        return

   
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

async def asignar_strike_automatico(ctx):
    autor = ctx.author
    servidor = ctx.guild
    rol_strike = discord.utils.get(servidor.roles, name="Strike")

    if not rol_strike:
        await ctx.send("⚠️ El rol `Strike` no existe.")
        return

    if rol_strike in autor.roles:
        await ctx.send(f"⛔ Ya tienes un strike, {autor.mention}. No puedes usar este comando.")
        return

    try:
        await autor.add_roles(rol_strike, reason="Intentó usar comando sin permiso.")
        await ctx.send(f"🚫 {autor.mention}, no puedes usar este comando. Has recibido un **Strike**.")
        await autor.send(get_mensaje_strike())
    except discord.Forbidden:
        await ctx.send("⚠️ No tengo permisos para asignar el rol.")

def get_mensaje_strike():
    return (
        "Oye... te lo voy a decir solo una vez.\n\n"
        "Lo que hiciste, no va con las reglas de The Klub. Aquí se viene a respetar la energía, la gente y el espacio. "
        "No te echamos hoy... pero la próxima, estás fuera sin saludo ni explicación.\n\n"
        "Este sitio no es un “vale todo”. Es un “vale lo que yo diga”.\n"
        "Y tú ya estás en tu última vida.\n\n"
        "Decide bien cuál va a ser tu siguiente movimiento."
    )

@bot.command(name="new-tournament")
async def new_tournament(ctx, *, datos=None):
    if ctx.channel.name != "anuncios-torneos":
        await ctx.send("❌ Este comando solo se puede usar en el canal #anuncios-torneos.")
        return

    if datos is None:
        await ctx.send(
            "❌ Debes ingresar los datos con el formato:\n"
            "`!new-tournament Evento | tipo | jugadores | dd/mm/yyyy`"
        )
        return

    partes = [parte.strip() for parte in datos.split("|")]

    if len(partes) != 4:
        await ctx.send(
            "❌ Formato incorrecto. Usa:\n"
            "`!new-tournament Evento | tipo | jugadores | dd/mm/yyyy`\n"
            "_Ejemplo:_ `!new-tournament Torneo Final | premodern | 16 | 25/07/2025`"
        )
        return

    evento, tipo, jugadores_str, fecha_limite = partes
    errores = []

    # Validación de tipo
    tipos_validos = ["premodern-suizo", "7pts-suizo", "classic-legacy-suizo", "premodern-bondage-suizo"]
    if tipo not in tipos_validos:
        errores.append(
            f"• Tipo inválido (`{tipo}`). Tipos permitidos: {', '.join(tipos_validos)}"
        )

    # Validar jugadores
    if not jugadores_str.isdigit() or int(jugadores_str) <= 0:
        errores.append("• El campo `jugadores` debe ser un número entero mayor a 0.")

    # Validar fecha
    try:
        fecha_obj = datetime.strptime(fecha_limite, "%d/%m/%Y")
        if fecha_obj.date() <= datetime.now().date():
            errores.append("• La `fecha_límite` debe ser posterior al día de hoy.")
    except ValueError:
        errores.append("• Formato de `fecha_límite` inválido. Usa `dd/mm/yyyy`.")

    if errores:
        mensaje_error = "❌ Hay errores en tu comando:\n\n"
        mensaje_error += "\n".join(errores)
        mensaje_error += (
            "\n\n✅ Formato correcto:\n"
            "`!new-tournament Evento | tipo | jugadores | dd/mm/yyyy`\n"
            "_Ejemplo:_ `!new-tournament Torneo Final | premodern | 16 | 25/07/2025`"
        )
        await ctx.send(mensaje_error)
        return

    # Verificar permisos
    rol_moderador = discord.utils.get(ctx.guild.roles, name="Moderador")
    es_moderador = rol_moderador and rol_moderador in ctx.author.roles

    if not es_moderador:
        await asignar_strike_automatico(ctx)
        return

    # Canal de destino
    canal_destino = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    if not canal_destino:
        await ctx.send("❌ No se encontró el canal #torneos-activos.")
        return

    # Verificar duplicados
    async for mensaje in canal_destino.history(limit=100):
        if mensaje.author.bot and mensaje.content.startswith(""):
            patron = re.compile(r"(.+?) (\d{2}/\d{2}/\d{4})", re.IGNORECASE)
            match = patron.search(mensaje.content)
            if match:
                evento_existente, fecha_existente = match.groups()
                if evento_existente.lower() == evento.lower() and fecha_existente == fecha_limite:
                    await ctx.send(
                        f"⚠️ Ya existe un torneo llamado `{evento}` con fecha `{fecha_limite}` en `#torneos-activos`."
                    )
                    return

    # Generar código único
    codigo = generar_codigo_unico()

    # Crear mensaje final
    mensaje = (
        f"`{evento}` `{fecha_limite}` | `{jugadores_str}` | `{tipo}` | código: `{codigo}` "
        f"creado por {ctx.author.mention}"
    )

    await canal_destino.send(mensaje)
    await ctx.send(f"✅ Torneo creado correctamente en `#torneos-activos` con código `{codigo}`.")

@bot.command(name="torneos-activos")
async def torneos_activos(ctx):
    canal = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    if not canal:
        await ctx.send("❌ No se encontró el canal `#torneos-activos`.")
        return

    hoy = datetime.now().date()
    patron = re.compile(r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` creado por (.+)", re.IGNORECASE)

    torneos = []

    async for mensaje in canal.history(limit=100):
        if not mensaje.content.startswith(""):
            continue

        match = patron.search(mensaje.content)
        if not match:
            continue

        nombre, fecha_str, cantidad, tipo, autor = match.groups()

        try:
            fecha = datetime.strptime(fecha_str, "%d/%m/%Y").date()
        except ValueError:
            continue

        if fecha >= hoy:
            torneos.append((fecha_str, nombre, tipo, cantidad, autor))

    if not torneos:
        await ctx.send("📭 No hay torneos activos para hoy o más adelante.")
        return

    embed = discord.Embed(title="🏆 Torneos activos", color=discord.Color.purple())
    for fecha, nombre, tipo, cantidad, autor in sorted(torneos):
        embed.add_field(
            name=f"{nombre} ({fecha})",
            value=f"• Tipo: `{tipo}`\n• Jugadores: `{cantidad}`\n• Creador: {autor}",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name="inscribirse")
async def inscribirse(ctx, codigo=None):
    if codigo is None:
        await ctx.author.send("❌ Debes proporcionar un código. Ejemplo: `!inscribirse CZI1F6`")
        return

    codigo = codigo.upper()

    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-en-torneos")

    if not canal_torneos or not canal_inscritos:
        await ctx.author.send("❌ No se encontraron los canales requeridos (`#torneos-activos` o `#inscritos-en-torneos`).")
        return

    # Nuevo patrón adaptado a tu formato con backticks
    patron = re.compile(
        r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` \| código: `(\w{6})` creado por .+",
        re.IGNORECASE
    )

    torneo = None

    async for mensaje in canal_torneos.history(limit=100):
        if not mensaje.content:
            continue

        match = patron.search(mensaje.content)
        if match:
            nombre, fecha, cupo, tipo, codigo_mensaje = match.groups()
            if codigo == codigo_mensaje.upper():
                torneo = {
                    "nombre": nombre,
                    "fecha": fecha,
                    "cupo": int(cupo),
                    "tipo": tipo,
                    "codigo": codigo_mensaje,
                }
                break

    if not torneo:
        await ctx.author.send(f"❌ No se encontró ningún torneo con el código `{codigo}`.")
        return

    # Verificar si ya está inscrito
    ya_inscrito = False
    total_inscritos = 0

    async for mensaje in canal_inscritos.history(limit=200):
        if mensaje.content.startswith("🎟️ Inscrito") and f"`{codigo}`" in mensaje.content:
            total_inscritos += 1
            if ctx.author.mention in mensaje.content:
                ya_inscrito = True
                break

    if ya_inscrito:
        await ctx.author.send(f"ℹ️ Ya estás inscrito en el torneo `{torneo['nombre']}`.")
        return

    if total_inscritos >= torneo["cupo"]:
        await ctx.author.send(f"🚫 El torneo `{torneo['nombre']}` ya alcanzó su cupo máximo de `{torneo['cupo']}` jugadores.")
        return

    numero = total_inscritos + 1
    mensaje_inscripcion = (
        f"🎟️ Inscrito #{numero} en `{torneo['nombre']}` (`{torneo['codigo']}`)\n"
        f"👤 {ctx.author.mention}"
    )

    await canal_inscritos.send(mensaje_inscripcion)
    await ctx.author.send(f"✅ Te has inscrito correctamente en el torneo `{torneo['nombre']}` con el código `{codigo}`.")

@bot.command(name="ver-inscritos")
async def ver_inscritos(ctx, codigo=None):
    if not codigo:
        await ctx.send("❌ Debes indicar el código del torneo. Ejemplo: `!ver-inscritos CZI1F6`")
        return

    codigo = codigo.upper()

    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-en-torneos")

    if not canal_torneos or not canal_inscritos:
        await ctx.send("❌ No se encontraron los canales requeridos (`#torneos-activos` o `#inscritos-en-torneos`).")
        return

    patron_torneo = re.compile(
        r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` \| código: `(\w{6})` creado por .+",
        re.IGNORECASE
    )

    torneo = None

    async for mensaje in canal_torneos.history(limit=100):
        match = patron_torneo.search(mensaje.content)
        if match:
            nombre, fecha, cupo, tipo, codigo_mensaje = match.groups()
            if codigo == codigo_mensaje.upper():
                torneo = {
                    "nombre": nombre,
                    "fecha": fecha,
                    "cupo": int(cupo),
                    "tipo": tipo,
                    "codigo": codigo_mensaje,
                }
                break

    if not torneo:
        await ctx.send(f"❌ No se encontró ningún torneo con el código `{codigo}`.")
        return

    inscritos = []

    patron_inscrito = re.compile(
        r"🎟️ Inscrito #\d+ en `(.+?)` \(`(\w{6})`\)\n👤 <@!?(\d+)>",
        re.IGNORECASE
    )

    async for mensaje in canal_inscritos.history(limit=200):
        match = patron_inscrito.search(mensaje.content)
        if match:
            nombre_torneo, codigo_encontrado, user_id = match.groups()
            if codigo_encontrado.upper() == codigo:
                miembro = ctx.guild.get_member(int(user_id))
                inscritos.append(miembro.mention if miembro else f"<@{user_id}>")

    if not inscritos:
        await ctx.send(f"ℹ️ No hay jugadores inscritos aún en el torneo `{torneo['nombre']}`.")
        return

    embed = discord.Embed(
        title=f"🎯 Inscritos en {torneo['nombre']}",
        description=f"🗓️ Fecha límite: `{torneo['fecha']}`\n🎮 Tipo: `{torneo['tipo']}`\n🔢 Cupo: {len(inscritos)}/{torneo['cupo']}",
        color=discord.Color.purple()
    )

    for i, jugador in enumerate(inscritos, start=1):
        embed.add_field(name=f"#{i}", value=jugador, inline=False)

    await ctx.send(embed=embed)

@bot.command(name="eliminar-mensajes")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, canal: discord.TextChannel = None, cantidad: int = None):
    # Verifica que se haya mencionado un canal y una cantidad válida
    if canal is None or cantidad is None:
        await ctx.send(
            "❌ Uso incorrecto del comando.\n"
            "✅ Formato: `!eliminar-mensajes #canal cantidad`\n"
            "_Ejemplo:_ `!eliminar-mensajes #general 50`"
        )
        return

    # Verificar que el usuario tenga el rol Moderador o sea el dueño
    rol_moderador = discord.utils.get(ctx.guild.roles, name="Moderador")
    es_dueno = ctx.author == ctx.guild.owner
    es_moderador = rol_moderador and rol_moderador in ctx.author.roles

    if not (es_dueno or es_moderador):
        await asignar_strike_automatico(ctx)
        return

    # Validar cantidad
    if cantidad <= 0 or cantidad > 1000:
        await ctx.send("⚠️ La cantidad debe ser entre 1 y 1000 mensajes.")
        return

    try:
        mensajes_borrados = await canal.purge(limit=cantidad)
        await ctx.send(f"✅ Se han eliminado {len(mensajes_borrados)} mensajes de {canal.mention}.", delete_after=5)
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para borrar mensajes en ese canal.")
    except discord.HTTPException as e:
        await ctx.send(f"⚠️ Hubo un error al intentar borrar mensajes: {e}")

@tasks.loop(minutes=1)
async def publicar_eventos_diarios():
    now = datetime.now()
    if now.hour != 10 or now.minute != 00:
        return  

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

@tasks.loop(minutes=1)
async def limpiar_partidos_pasados():
    now = datetime.now()

    # Ejecutar exactamente a las 10:00
    if now.hour != 10 or now.minute != 0:
        return

    for guild in bot.guilds:
        canal = discord.utils.get(guild.text_channels, name="partidos-agendados")
        if not canal:
           
            continue

      

        patron = re.compile(r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})")

        async for mensaje in canal.history(limit=200):
            if not mensaje.content.startswith("📅 [EVENTO]"):
                continue

            match = patron.search(mensaje.content)
            if not match:
                continue

            fecha_str, hora_str = match.groups()

            try:
                fecha_completa = datetime.strptime(f"{fecha_str} {hora_str}", "%d/%m/%Y %H:%M")
                if fecha_completa.date() < now.date():
                    await mensaje.delete()
                   
            except ValueError:
               
                continue
            
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
    publicar_eventos_diarios.start()
    limpiar_partidos_pasados.start()

webserver.keep_alive()  
bot.run(DISCORD_TOKEN)
