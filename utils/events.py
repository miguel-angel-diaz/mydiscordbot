######## events.py #######
import discord
from discord.ext import commands
from datetime import datetime, timezone
import asyncio
import config

tiempos_entrada = {}  # { user_id: datetime }


async def registrar_mensaje_borrado_handle(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    if message.channel.name.lower() in config.CANALES_EXCLUIDOS:
        return

    guild = message.guild
    canal_log = discord.utils.get(guild.text_channels, name="mensajes-borrados")
    if not canal_log:
        return

    try:
        embed = discord.Embed(
            title="🗑️ Mensaje borrado",
            description=f"**Autor:** {message.author.mention}\n"
                        f"**Canal:** {message.channel.mention}\n"
                        f"**Fecha:** <t:{int(message.created_at.timestamp())}:F>",
            color=discord.Color.red(),
        )

        if message.content:
            embed.add_field(
                name="Contenido borrado",
                value=discord.utils.escape_markdown(message.content),
                inline=False
            )

        if message.attachments:
            urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Adjuntos", value=urls, inline=False)

        await canal_log.send(embed=embed)

    except Exception as e:
        print(f"[ERROR] registrando mensaje borrado: {e}")

async def bienvenida_y_comandos_handle(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # Asegúrate de que es el canal #presentation
    canal_presentaciones = discord.utils.get(message.guild.text_channels, name="🪞-vestíbulo‐")
    if not canal_presentaciones or message.channel.id != canal_presentaciones.id:
        return

    member = message.author
    guild = member.guild

    # Roles de bienvenida
    rol_welcome = discord.utils.get(guild.roles, name="Accept Welcome")
    rol_rules = discord.utils.get(guild.roles, name="Accept Rules")
    rol_miembro = discord.utils.get(guild.roles, name="miembro")

    # 0️⃣ Verificar que tiene ambos roles
    roles_usuario = {role.name for role in member.roles}
    if not {"Accept Welcome", "Accept Rules"}.issubset(roles_usuario):
        return  # Si no tiene ambos roles, no sigue

    # 1️⃣ Quitar roles de bienvenida
    roles_a_quitar = [r for r in (rol_welcome, rol_rules) if r in member.roles]
    if roles_a_quitar:
        try:
            await member.remove_roles(*roles_a_quitar, reason="Ya obtuvo el rol 'miembro'")
            print(f"[INFO] Roles de bienvenida quitados a {member.display_name}")
        except discord.Forbidden:
            print(f"[WARN] No tengo permisos para quitar roles a {member.display_name}")
            return

    # 2️⃣ Comprobar si está en la blacklist
    if member.id in config.BLACKLIST_USERS:
        await castigar_usuario(member)
        return

    canal_logs = discord.utils.get(guild.text_channels, name="usuarios-que-nos-dejaron")
    if canal_logs:
        async for mensaje in canal_logs.history(limit=200):
            # Caso 1: mensaje normal con el ID en el contenido
            if str(member.id) in mensaje.content or member.mention in mensaje.content:
                await castigar_usuario(member)
                return

            # Caso 2: mensaje con embed (lo más probable en tu caso)
            for embed in mensaje.embeds:
                if embed.description and str(member.id) in embed.description:
                    await castigar_usuario(member)
                    return
                if embed.fields:
                    for field in embed.fields:
                        if str(member.id) in field.value or str(member.id) in field.name:
                            await castigar_usuario(member)
                            return

    # 4️⃣ Asignar rol definitivo de miembro
    if rol_miembro and rol_miembro not in member.roles:
        try:
            await member.add_roles(rol_miembro, reason="Aceptó reglas y bienvenida")
            print(f"[INFO] Rol 'miembro' asignado a {member.display_name}")
        except discord.Forbidden:
            print(f"[WARN] No tengo permisos para asignar rol 'miembro' a {member.display_name}")
            return
     # Simula que tiene el rol definitivo
    roles_simulados = roles_usuario | {"miembro"}

    # 📌 Comandos disponibles
    comandos_disponibles = []
    for comando in config.COMANDOS_INFO:
        roles_permitidos = comando["roles_permitidos"]
        if any(rol in roles_simulados for rol in roles_permitidos):
            comandos_disponibles.append(f"!{comando['comando']} - {comando['descripcion']}")

    # 📌 Torneos activos
    canal_torneos = discord.utils.get(guild.text_channels, name="torneos-activos")
    torneos_activos = []
    if canal_torneos:
        async for msg in canal_torneos.history(limit=50):  # ajusta el límite si quieres más
            if msg.pinned:  # no contar fijados
                continue
            # opcional: comprobar roles en el mensaje (si los torneos tienen esa info)
            torneos_activos.append(msg.content)

    # 📌 Sorteos activos
    canal_sorteos = discord.utils.get(guild.text_channels, name="sorteos-activos")
    sorteos_activos = []
    if canal_sorteos:
        async for msg in canal_sorteos.history(limit=50):
            if msg.pinned:
                continue
            sorteos_activos.append(msg.content)

    # ✅ Enviar bienvenida
    try:
        await member.send(f"👋 ¡Bienvenido/a al servidor, {member.display_name}! 🎉")
    except discord.Forbidden:
        print(f"[INFO] No pude enviar bienvenida a {member}")
        return

    # ✅ Enviar comandos
    if comandos_disponibles:
        embed_comandos = discord.Embed(
            title="📋 Tus comandos disponibles",
            description="\n".join(comandos_disponibles),
            color=discord.Color.green()
        )
        await member.send(embed=embed_comandos)

    # ✅ Enviar torneos
    if torneos_activos:
        embed_torneos = discord.Embed(
            title="🎮 Torneos activos",
            description="\n\n".join(torneos_activos[:5]),  # los primeros 5
            color=discord.Color.blue()
        )
        await member.send(embed=embed_torneos)

    # ✅ Enviar sorteos
    if sorteos_activos:
        embed_sorteos = discord.Embed(
            title="🎁 Sorteos activos",
            description="\n\n".join(sorteos_activos[:5]),  # los primeros 5
            color=discord.Color.purple()
        )
        await member.send(embed=embed_sorteos)

    # 5️⃣ Registrar en canal #registro-de-usuarios
    canal_registro = discord.utils.get(message.guild.text_channels, name="registro-de-usuarios")
    if canal_registro:
        embed_registro = discord.Embed(
            title="📥 Nuevo miembro registrado",
            color=discord.Color.blue()
        )
        embed_registro.set_thumbnail(url=member.display_avatar.url)
        embed_registro.add_field(name="Usuario", value=f"{member} (ID: {member.id})", inline=False)
        embed_registro.add_field(name="Apodo en servidor", value=member.display_name, inline=False)
        embed_registro.add_field(name="Roles asignados", value=", ".join(roles_usuario) or "Sin roles", inline=False)
        embed_registro.add_field(name="Cuenta creada", value=member.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed_registro.add_field(name="Se unió al servidor", value=member.joined_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed_registro.add_field(name="Mensaje de presentación", value=message.content[:1000], inline=False)

        await canal_registro.send(embed=embed_registro)
        
async def reconocer_comando_handle(bot: commands.Bot, message: discord.Message):
    if not message.content.startswith("!"):
        return False  # No es comando, seguimos

    comandos_alias = {
        "mis comandos": "mis-comandos",
        "cartas mas jugadas": "cartas-mas-jugadas",
        "ver inscritos": "ver-inscritos",
        "reportar resultado": "reportar-resultado",
        "modificar resultado": "modificar-resultado",
        "partidos pendientes": "partidos-pendientes",
        "inscribirse sorteo": "inscribirse-sorteo",
        "subir deck": "subir-deck",
        "editar deck": "editar-deck",
        "agendar partida": "agendar-partida",
        "modificar agenda": "modificar-agenda",
        "eventos hoy": "eventos-hoy",
        "nueva peticion": "nueva-peticion",
        "nuevo comunicado": "nuevo-comunicado"
    }

    comando_texto = message.content[1:].lower().strip()

    # Solo ejecutar wizard si el comando tiene espacio
    if comando_texto not in comandos_alias or " " not in comando_texto:
        return False  # No es un alias con espacio, seguimos

    sugerido = comandos_alias[comando_texto]

    try:
        dm = await message.author.create_dm()
        embed = discord.Embed(
            title="⚡ He detectado tu comando",
            description=f"¿Querías usar `!{sugerido}`? (responde con **sí** o **no**)",
            color=0x00ffcc
        )
        await dm.send(embed=embed)

        def check(m):
            return (
                m.author == message.author
                and m.channel == dm
                and m.content.lower() in ["sí", "si", "no"]
            )

        respuesta = await bot.wait_for("message", timeout=30.0, check=check)

        if respuesta.content.lower() in ["sí", "si"]:
            # Crear contexto y ejecutar comando directamente
            ctx = await bot.get_context(message)
            await ctx.invoke(bot.get_command(sugerido))
        else:
            await dm.send("❌ Comando cancelado.")
    except asyncio.TimeoutError:
        await dm.send("⏰ Tiempo agotado. Comando cancelado automáticamente.")
    except Exception as e:
        print(f"Error en wizard: {e}")

    return True  # Indicamos que el mensaje fue manejado
async def evento_socio_handle(before: discord.Member, after: discord.Member):
    # Nombre del rol que quieres detectar
    ROL_SOCIO = "socio"

    # Buscar si antes no lo tenía y ahora sí
    roles_antes = {r.name for r in before.roles}
    roles_despues = {r.name for r in after.roles}

    if ROL_SOCIO not in roles_antes and ROL_SOCIO in roles_despues:
        mensaje = (
            "📢 **Información importante para socios**\n\n"
            "La dirección se plantea establecer una cuota para los socios. "
            "Dicha cuota será de **6 euros semestrales** o **10 anuales**, según la suscripción que quiera realizar el socio. "
            "Este dinero tiene como único fin la creación de merchandising para los premios y organizar algún tipo de evento, "
            "a criterio de la dirección.\n\n"
            "Si algún socio desea ver las cuentas, éstas le serán mostradas para que pueda ver exactamente dónde se ha destinado el dinero, "
            "ya que apostamos por la total transparencia y bienestar de nuestros socios.\n\n"
            "Por último, remarcar que el acatamiento de dichas normas es obligatorio y que si no se han leído, no es problema de la dirección. "
            "Estar en The Klub es un privilegio y no un derecho; este servidor pertenece exclusivamente a la dirección. "
            "Cualquier intento de apropiación será sancionado.\n\n"
            "Si estás conforme con todo esto, puedes pasar; si no, ten dignidad y vete tú antes de que te echemos nosotros, "
            "sin problemas ni malos rollos ya que no todo el mundo vale para estar aquí.\n\n"
            "🎉 **Y ahora sí que sí, sean bienvenidos a The Klub.**"
        )

        try:
            await after.send(mensaje)
            print(f"[INFO] Mensaje de socio enviado a {after}")
        except discord.Forbidden:
            print(f"[WARN] No pude enviar mensaje privado a {after}")
         
async def usuario_salio_handle(bot: commands.Bot, member: discord.Member):
    # Canal donde se detallará la info del usuario que se fue
    canal_info = discord.utils.get(member.guild.text_channels, name="usuarios-que-nos-dejaron")
    if canal_info:
        embed = discord.Embed(
            title="👋 Usuario ha abandonado el servidor",
            color=discord.Color.red()
        )
        embed.add_field(name="Nombre", value=f"{member.name}#{member.discriminator}", inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Fecha de creación", value=member.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed.add_field(name="Fecha de unión", value=member.joined_at.strftime("%d/%m/%Y %H:%M:%S") if member.joined_at else "Desconocida", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await canal_info.send(embed=embed)

    # Canal de anuncios
    # canal_anuncios = ctx.guild.get_channel(1387389356464934993)
    # canal_anuncios = discord.utils.get(member.guild.text_channels, name="📰-tablon‐anuncios")
    # if canal_anuncios:
    #     await canal_anuncios.send(f"📢 El usuario **{member.display_name}** ha abandonado **The Klub**.")

async def castigar_usuario(member: discord.Member):
    try:
        # Mensaje privado
        await member.send(
            "Lo siento pero no eres el perfil que buscamos, agradecemos tú interés pero no todo el mundo vale para The Klub,"
            "estar aquí no es un derecho, es un privilegio."
            "Buena suerte en tu camino y que vaya bien."
        )
    except discord.Forbidden:
        print(f"No se pudo enviar DM a {member.name}")

    # Asignar rol Out
    rol_out = discord.utils.get(member.guild.roles, name="Out")
    if rol_out:
        await member.add_roles(rol_out, reason="Usuario en blacklist o expulsado previamente")

async def log_comando_handle(bot, usuario, comando, tipo, error=None, fecha=None):
    canal_log = bot.get_channel(1413079518440198206)
    if not canal_log:
        return

    # Definir título y color según tipo
    if tipo == "correcto":
        titulo = "✅ Comando ejecutado"
        color = discord.Color.green()
    elif tipo == "no_encontrado":
        titulo = "❌ Comando no encontrado"
        color = discord.Color.red()
    elif tipo == "argumento_faltante":
        titulo = "⚠️ Falta argumento"
        color = discord.Color.orange()
    else:  # error genérico
        titulo = "⚠️ Error en comando"
        color = discord.Color.dark_orange()

    embed = discord.Embed(
        title=titulo,
        color=color,
        timestamp=fecha
    )
    embed.add_field(name="Usuario", value=f"{usuario} (ID: {usuario.id})", inline=False)
    embed.add_field(name="Comando", value=f"{comando}", inline=False)
    if error:
        embed.add_field(name="Error", value=str(error), inline=False)

    await canal_log.send(embed=embed)

async def member_join_handle(member, before, after):
    # Usuario entra a un canal de voz
    if before.channel is None and after.channel is not None:
        tiempos_entrada[member.id] = datetime.now(timezone.utc)

    # Usuario sale del canal
    elif before.channel is not None and after.channel is None:
        if member.id in tiempos_entrada:
            inicio = tiempos_entrada.pop(member.id)
            duracion = (datetime.now(timezone.utc) - inicio).total_seconds()

            if duracion >= 60:  # 5 minutos
                canal_registro = discord.utils.get(member.guild.text_channels, name="oyentes-en-canales")
                if canal_registro:
                    minutos = int(duracion // 60)
                    segundos = int(duracion % 60)

                    # Compañeros que estaban en el canal (sin incluir al usuario)
                    companeros = [m.display_name for m in before.channel.members if m.id != member.id]
                    if companeros:
                    
                        companeros_txt = ", ".join(companeros)

                        embed = discord.Embed(
                            title="📋 Registro de voz",
                            description=f"**{member.display_name}** estuvo en un canal de voz.",
                            color=discord.Color.blue(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        embed.add_field(name="Canal", value=before.channel.name, inline=True)
                        embed.add_field(name="Duración", value=f"{minutos}m {segundos}s", inline=True)
                        embed.add_field(name="Con quién estuvo", value=companeros_txt, inline=False)
                        embed.set_footer(text=f"ID Usuario: {member.id}", icon_url=member.display_avatar.url)

                        await canal_registro.send(embed=embed)

    # Usuario cambia de un canal a otro
    elif before.channel != after.channel:
        if member.id in tiempos_entrada:
            inicio = tiempos_entrada.pop(member.id)
            duracion = (datetime.now(timezone.utc) - inicio).total_seconds()

            if duracion >= 300:
                canal_registro = discord.utils.get(member.guild.text_channels, name="registro-canales-voz")
                if canal_registro:
                    minutos = int(duracion // 60)
                    segundos = int(duracion % 60)

                    # Compañeros del canal anterior (sin incluir al usuario)
                    companeros = [m.display_name for m in before.channel.members if m.id != member.id]
                    if not companeros:
                        companeros_txt = "Estuvo solo 🗿"
                    else:
                        companeros_txt = ", ".join(companeros)

                    embed = discord.Embed(
                        title="📋 Registro de voz",
                        description=f"**{member.display_name}** cambió de canal de voz.",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.add_field(name="Canal anterior", value=before.channel.name, inline=True)
                    embed.add_field(name="Tiempo en canal", value=f"{minutos}m {segundos}s", inline=True)
                    embed.add_field(name="Con quién estuvo", value=companeros_txt, inline=False)
                    embed.set_footer(text=f"ID Usuario: {member.id}", icon_url=member.display_avatar.url)

                    await canal_registro.send(embed=embed)

        # Reiniciar el tiempo en el nuevo canal
        tiempos_entrada[member.id] = datetime.now(timezone.utc)

