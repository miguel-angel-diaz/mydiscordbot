import discord
from discord.ext import commands
import config

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
        historial = []
        async for msg in message.channel.history(limit=20, before=message.created_at, oldest_first=False):
            if msg.id != message.id:
                historial.append(msg)
            if len(historial) == 5:
                break

        historial.reverse()

        embed = discord.Embed(
            title="🗑️ Mensaje borrado",
            description=f"**Autor:** {message.author.mention}\n**Canal:** {message.channel.mention}\n**Fecha:** <t:{int(message.created_at.timestamp())}:F>",
            color=discord.Color.red(),
        )

        if message.content:
            embed.add_field(name="Contenido borrado", value=discord.utils.escape_markdown(message.content), inline=False)

        if message.attachments:
            urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Adjuntos", value=urls, inline=False)

        await canal_log.send(embed=embed)

        if historial:
            await canal_log.send("🧾 **5 mensajes anteriores:**")
            for msg in historial:
                contenido = msg.content if msg.content else "*[Sin texto]*"
                autor = f"{msg.author.display_name} ({msg.author})"
                fecha = f"<t:{int(msg.created_at.timestamp())}:F>"
                texto = f"**{autor}** ({fecha}):\n{discord.utils.escape_markdown(contenido)}"
                await canal_log.send(texto[:1900])

    except Exception as e:
        print(f"[ERROR] registrando mensaje borrado: {e}")

async def bienvenida_y_comandos_handle(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # Asegúrate de que es el canal #presentaciones
    canal_presentaciones = discord.utils.get(message.guild.text_channels, name="presentation")
    if not canal_presentaciones or message.channel.id != canal_presentaciones.id:
        return

    # Asegúrate de que tiene ambos roles de bienvenida
    roles_usuario = {role.name for role in message.author.roles}
    if not config.ROLES_BIENVENIDA.issubset(roles_usuario):
        return

    # Simula que tiene el rol definitivo
    roles_simulados = roles_usuario | {"miembro"}

    # Comandos a los que tendrá acceso como miembro
    comandos_disponibles = []
    for comando in config.COMANDOS_INFO:
        roles_permitidos = comando["roles_permitidos"]
        if any(rol in roles_simulados for rol in roles_permitidos):
            comandos_disponibles.append(f"!{comando['comando']} - {comando['descripcion']}")

    # Mensaje de bienvenida
    try:
        await message.author.send(f"👋 ¡Bienvenido/a al servidor, {message.author.display_name}! 🎉")
    except discord.Forbidden:
        print(f"[INFO] No pude enviar bienvenida a {message.author}")
        return

    # Enviar comandos disponibles
    if comandos_disponibles:
        embed = discord.Embed(
            title="📋 Tus comandos disponibles",
            description="\n".join(comandos_disponibles),
            color=discord.Color.green()
        )
        try:
            await message.author.send(embed=embed)
        except discord.Forbidden:
            print(f"[INFO] No pude enviar comandos a {message.author}")
    else:
        try:
            await message.author.send("❌ No tienes acceso a ningún comando.")
        except discord.Forbidden:
            pass
     # 🔹 Registrar en canal #registro-de-usuarios
    canal_registro = discord.utils.get(message.guild.text_channels, name="registro-de-usuarios")
    if canal_registro:
        embed_registro = discord.Embed(
            title="📥 Nuevo miembro registrado",
            color=discord.Color.blue()
        )
        embed_registro.set_thumbnail(url=message.author.display_avatar.url)
        embed_registro.add_field(name="Usuario", value=f"{message.author} (ID: {message.author.id})", inline=False)
        embed_registro.add_field(name="Apodo en servidor", value=message.author.display_name, inline=False)
        embed_registro.add_field(name="Roles asignados", value=", ".join(roles_usuario) or "Sin roles", inline=False)
        embed_registro.add_field(name="Cuenta creada", value=message.author.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed_registro.add_field(name="Se unió al servidor", value=message.author.joined_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed_registro.add_field(name="Mensaje de presentación", value=message.content[:1000], inline=False)

        await canal_registro.send(embed=embed_registro)

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
    canal_anuncios = discord.utils.get(member.guild.text_channels, name="anuncios")
    if canal_anuncios:
        await canal_anuncios.send(f"📢 El usuario **{member.display_name}** ha abandonado **The Klub**.")

    # Mensaje privado al usuario
    try:
        await member.send("En The Klub no creemos en segundas oportunidades, espero que haya reflexionado muy bien tu decisión.")
    except discord.Forbidden:
        # No se pudo enviar mensaje privado
        pass
     async def on_member_join_handle(member: discord.Member):
    guild = member.guild

    # 1️⃣ Comprobar si está en la blacklist
     if member.id in config.BLACKLIST_USERS:
        await castigar_usuario(member)
        return

    # 2️⃣ Comprobar si aparece en el canal "usuarios-que-nos-dejaron"
    canal_logs = discord.utils.get(guild.text_channels, name="usuarios-que-nos-dejaron")
    if canal_logs:
        async for mensaje in canal_logs.history(limit=200):  # Busca últimos 200 mensajes
            if str(member.id) in mensaje.content or member.mention in mensaje.content:
                await castigar_usuario(member)
                return

async def castigar_usuario(member: discord.Member):
    try:
        # Mensaje privado
        await member.send(
            "En The Klub no necesitamos gente como tú. "
            "Y no queremos que la gente como tú entre en nuestro garito, "
            "así que no te molestes."
        )
    except discord.Forbidden:
        print(f"No se pudo enviar DM a {member.name}")

    # Asignar rol Out
    rol_out = discord.utils.get(member.guild.roles, name="Out")
    if rol_out:
        await member.add_roles(rol_out, reason="Usuario en blacklist o expulsado previamente")
