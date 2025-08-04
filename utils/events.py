import discord
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