
import discord
from datetime import datetime
import asyncio
import aiohttp
import random
import config

from utils.commons import borrar_mensaje_seguro, validar_canal_correcto, buscar_usuario_en_servidor, obtener_torneo_usuario

async def aplicar_strike(ctx, miembro: discord.Member):
     # Intentar eliminar el mensaje del canal público
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!strike"):
        return

    servidor = ctx.guild
    author = ctx.author

    # Verificar permisos
    if not await moderador_permisos_handle(ctx):
      return

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        # Si falta algún dato, inicia conversación por DM
        if miembro is None:
            await author.send("⚠️ Vamos a emitir un strike. Responde a las siguientes preguntas:")

            if miembro is None:
                await author.send("¿A quién quieres aplicar el strike? Escribe su nombre o apodo exacto tal como aparece en el servidor:")
                respuesta_miembro = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                miembro = buscar_usuario_en_servidor(ctx.guild, respuesta_miembro.content.strip())
                if not miembro:
                    await author.send("❌ No encontré a ese usuario en el servidor.")
                    return

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentar con `!strike`.")
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes privados. Activa los mensajes en tu configuración de privacidad.")
    except Exception as e:
        await author.send("❌ Ocurrió un error inesperado durante el proceso.")
        raise e

    rol_strike = discord.utils.get(servidor.roles, name="Strike")
    if not rol_strike:
        await ctx.send("⚠️ El rol `Strike` no existe en el servidor.")
        return

    if rol_strike in miembro.roles:
        await ctx.author.send(f"ℹ️ {miembro.mention} ya tiene el rol `Strike`.")
        return

    try:
        await miembro.add_roles(rol_strike, reason="Strike manual asignado por Moderador.")
        await miembro.send(get_mensaje_strike())
    except discord.Forbidden:
        await ctx.author.send("❌ No tengo permisos para asignar el rol o enviar mensaje privado.")
        return

    await ctx.author.send(f"✅ {miembro.mention} ha recibido un **Strike**.")
    
    
    # canal_anuncios = ctx.guild.get_channel(1387389356464934993)
    # await canal_anuncios.send(f"⚠️ Hemos decidido que {miembro.mention} Permanezca una semana en el Hielo, la proxima vez le invitaremos a que abandone The Klub")

async def aplicar_out(ctx, miembro: discord.Member):
     # Intentar eliminar el mensaje del canal público
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!out"):
        return
        
    servidor = ctx.guild
    author = ctx.author
    
    # Verificar permisos
    if not await moderador_permisos_handle(ctx):
      return

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        # Si falta algún dato, inicia conversación por DM
        if miembro is None:
            await author.send("⚠️ Vamos a emitir un strike. Responde a las siguientes preguntas:")

            if miembro is None:
                await author.send("¿A quién quieres aplicar el out? Escribe su nombre o apodo exacto tal como aparece en el servidor:")
                respuesta_miembro = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                miembro = buscar_usuario_en_servidor(ctx.guild, respuesta_miembro.content.strip())
                if not miembro:
                    await author.send("❌ No encontré a ese usuario en el servidor.")
                    return

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentar con `!strike`.")
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes privados. Activa los mensajes en tu configuración de privacidad.")
    except Exception as e:
        await author.send("❌ Ocurrió un error inesperado durante el proceso.")
        raise e
    
    rol_out = discord.utils.get(servidor.roles, name="Out")
    if not rol_out:
        await ctx.author.send("⚠️ El rol `Out` no existe en el servidor.")
        return

    if rol_out in miembro.roles:
        await ctx.author.send(f"ℹ️ {miembro.mention} ya tiene el rol `Out`.")
        return

    try:
        await miembro.add_roles(rol_out, reason="Out manual asignado por moderador.")
    except discord.Forbidden:
        await ctx.author.send("❌ No tengo permisos para asignar el rol. Revisa la jerarquía de roles.")
        return

    mensaje_out = (
        "Escúchame bien, campeón. No fue solo la pinta, ni que vinieras en grupo, ni que te colaras en la fila. Fue todo. "
        "La energía, la actitud, el rollo. Este sitio tiene su código, su vibra... y tú no venías ni en la misma frecuencia.\n\n"
        "Así que no, no vas a entrar. No hoy, no mañana, no el próximo eclipse lunar. "
        "Puedes venir disfrazado de unicornio o vestido en látex con lentejuelas bendecidas por los dioses del techno… "
        "pero ya cruzaste la línea.\n\n"
        "Este club no es para todos. Es para los que son. Y tú... tú simplemente no eres."
    )

    try:
        await miembro.send(mensaje_out)
    except discord.Forbidden:
        await ctx.author.send(f"⚠️ {miembro.mention} no tiene los mensajes privados habilitados.")

    await ctx.author.send(f"✅ {miembro.mention} ha sido expulsado de la comunidad.")

    canal_info = discord.utils.get(ctx.guild.text_channels, name="blacklist")
    if canal_info:
        embed = discord.Embed(
            title="👋 Usuario expulsado del servidor",
            color=discord.Color.red()
        )
        embed.add_field(name="Nombre", value=f"{miembro.name}#{miembro.discriminator}", inline=True)
        embed.add_field(name="ID", value=miembro.id, inline=True)
        embed.add_field(name="Fecha de creación", value=miembro.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed.add_field(name="Fecha de unión", value=miembro.joined_at.strftime("%d/%m/%Y %H:%M:%S") if miembro.joined_at else "Desconocida", inline=False)
        embed.set_thumbnail(url=miembro.display_avatar.url)
        await canal_info.send(embed=embed)
    
    
    # canal_anuncios = ctx.guild.get_channel(1387389356464934993)
    # await canal_anuncios.send(f"⚠️ Hemos invitado a abandonar el servidor a {miembro.mention}, ya no podra volver a entrar a The Klub.")

async def eliminar_mensajes(ctx, canal: discord.TextChannel = None, cantidad: int = None, orden: str = None, incluir_fijados: bool = None):
    if not await moderador_permisos_handle(ctx):
        return

    author = ctx.author

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        # Preguntas por DM si faltan datos
        if canal is None or cantidad is None or orden is None or incluir_fijados is None:
            await author.send("🧹 Vamos a eliminar mensajes. Responde a las siguientes preguntas:")

            if canal is None:
                await author.send("1️⃣ ¿En qué canal quieres borrar mensajes? Escribe el nombre exacto del canal (sin `#`):")
                respuesta_canal = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                canal_nombre = respuesta_canal.content.strip().lower()
                canal = discord.utils.get(ctx.guild.text_channels, name=canal_nombre)
                if not canal:
                    await author.send("❌ No encontré ese canal. Asegúrate de escribir el nombre exacto.")
                    return

            if cantidad is None:
                await author.send("2️⃣ ¿Cuántos mensajes quieres eliminar? (entre 1 y 1000):")
                respuesta_cantidad = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                try:
                    cantidad = int(respuesta_cantidad.content.strip())
                except ValueError:
                    await author.send("❌ La cantidad debe ser un número entero.")
                    return

            if orden is None:
                await author.send("3️⃣ ¿Cómo quieres borrar los mensajes? Escribe `recientes` o `antiguos`:")
                respuesta_orden = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                orden = respuesta_orden.content.strip().lower()
                if orden not in ("recientes", "antiguos"):
                    await author.send("❌ Opción no válida. Usa `recientes` o `antiguos`.")
                    return

            if incluir_fijados is None:
                await author.send("4️⃣ ¿Quieres borrar también los mensajes fijados? Responde `sí` o `no`:")
                respuesta_fijados = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                incluir_fijados = respuesta_fijados.content.strip().lower() in ("sí", "si", "yes", "y")

        if cantidad <= 0 or cantidad > 1000:
            await author.send("⚠️ La cantidad debe estar entre 1 y 1000.")
            return

        mensajes_borrados = []

        if orden == "recientes":
            mensajes_borrados = await canal.purge(
                limit=cantidad,
                check=lambda m: incluir_fijados or not m.pinned
            )

        elif orden == "antiguos":
            mensajes = [msg async for msg in canal.history(limit=cantidad, oldest_first=True)]
            for msg in mensajes:
                if not incluir_fijados and msg.pinned:
                    continue
                try:
                    await msg.delete()
                    mensajes_borrados.append(msg)
                    await asyncio.sleep(0.5)
                except discord.HTTPException:
                    continue

        # ✅ Confirmación en el canal donde se lanzó el comando
        await ctx.send(
            f"✅ Se han eliminado {len(mensajes_borrados)} mensajes de {canal.mention}.",
            delete_after=5
        )

        # 🔔 Logs en #mensajes-borrados
        log_channel = discord.utils.get(ctx.guild.text_channels, name="mensajes-borrados")
        if log_channel:
            embed = discord.Embed(
                title="🧹 Mensajes eliminados",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderador", value=f"{author.mention}", inline=True)
            embed.add_field(name="Canal", value=f"{canal.mention}", inline=True)
            embed.add_field(name="Cantidad", value=f"{len(mensajes_borrados)}", inline=True)
            embed.add_field(name="Orden", value="Recientes primero" if orden=="recientes" else "Antiguos primero", inline=True)
            embed.add_field(name="Incluye fijados", value="✅ Sí" if incluir_fijados else "❌ No", inline=True)

            # Mostrar una vista previa (máx 5 para no saturar)
            if mensajes_borrados:
                preview = "\n".join(
                    f"**{m.author}**: {m.content[:40]}{'...' if len(m.content) > 40 else ''}"
                    for m in mensajes_borrados[:5]
                )
                embed.add_field(name="Ejemplo de mensajes borrados", value=preview, inline=False)

            await log_channel.send(embed=embed)

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentar con `!eliminar-mensajes`.")
    except discord.Forbidden:
        await author.send("❌ No tengo permisos para borrar mensajes en ese canal.")
    except discord.HTTPException as e:
        await author.send(f"⚠️ Ocurrió un error al intentar borrar mensajes: {e}")
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes por privado. Activa los DMs o vuelve a intentarlo en el canal.")

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
        await ctx.author.send(f"🚫 {autor.mention}, no puedes usar este comando. Has recibido un **Strike**.")
        await autor.send(get_mensaje_strike())
    except discord.Forbidden:
        await ctx.send("⚠️ No tengo permisos para asignar el rol.")
    
    
    # canal_anuncios = ctx.guild.get_channel(1387389356464934993)
    # await canal_anuncios.send(f"⚠️ Hemos decidido que {autor.mention} Permanezca una semana en el Hielo, la proxima vez le invitaremos a que abandone The Klub")

def get_mensaje_strike():
    return (
        "Oye... te lo voy a decir solo una vez.\n\n"
        "Lo que hiciste, no va con las reglas de The Klub. Aquí se viene a respetar la energía, la gente y el espacio. "
        "No te echamos hoy... pero la próxima, estás fuera sin saludo ni explicación.\n\n"
        "Este sitio no es un “vale todo”. Es un “vale lo que yo diga”.\n"
        "Y tú ya estás en tu última vida.\n\n"
        "Decide bien cuál va a ser tu siguiente movimiento."
    )

async def cerrar_peticion_handle(ctx, codigo: str = None, respuesta: str = None):
    await borrar_mensaje_seguro(ctx)
    
    if not await validar_canal_correcto(ctx, "peticiones-de-usuarios", "!cerrar-peticion"):
        return

    if not await moderador_permisos_handle(ctx):
        return

    author = ctx.author

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        if codigo is None or respuesta is None:
            await author.send("📩 Vamos a cerrar una petición. Responde a las siguientes preguntas:")

            if codigo is None:
                await author.send("1️⃣ ¿Cuál es el **código** de la petición que quieres cerrar?")
                respuesta_codigo = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
                codigo = respuesta_codigo.content.strip()

            if respuesta is None:
                await author.send("2️⃣ ¿Cuál es la **respuesta** que quieres enviar al usuario?")
                respuesta_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=180)
                respuesta = respuesta_msg.content.strip()

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentar con `!cerrar-peticion`.")
        return
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes por privado. Activa los DMs o vuelve a intentarlo desde el canal.")
        return

    # Buscar mensaje original en #peticiones-de-usuarios
    canal_peticiones = discord.utils.get(ctx.guild.text_channels, name="peticiones-de-usuarios")
    canal_resolucion = discord.utils.get(ctx.guild.text_channels, name="resolucion-de-peticiones")

    if not canal_peticiones or not canal_resolucion:
        await author.send("❌ No se encontraron los canales `#peticiones-de-usuarios` o `#resolucion-de-peticiones`.")
        return

    mensaje_objetivo = None
    autor_id = None
    contenido_peticion = "Sin descripción disponible"

    async for mensaje in canal_peticiones.history(limit=100):
        if mensaje.embeds:
            embed = mensaje.embeds[0]
            if f"`{codigo}`" in embed.description or any(f"`{codigo}`" in field.value for field in embed.fields):
                mensaje_objetivo = mensaje
                if embed.footer and embed.footer.text.isdigit():
                    autor_id = int(embed.footer.text)
                contenido_peticion = embed.description
                break

    if not mensaje_objetivo or not autor_id:
        await ctx.send("⚠️ No se pudo identificar al autor de la petición.")
        return

    miembro = ctx.guild.get_member(autor_id)
    if not miembro:
        await ctx.send("⚠️ No se encontró al miembro en el servidor.")
        return

    try:
        await miembro.send(
            f"📬 Tu petición con código `{codigo}` ha sido **cerrada**.\n"
            f"💬 Respuesta del equipo:\n>>> {respuesta}"
        )
    except discord.Forbidden:
        await ctx.send("⚠️ No se pudo enviar mensaje privado al autor (DMs desactivados).")
        return

    try:
        await mensaje_objetivo.delete()
    except discord.Forbidden:
        await ctx.send("⚠️ No tengo permisos para eliminar mensajes en `#peticiones-de-usuarios`.")
        return

    await ctx.send(f"✅ Petición `{codigo}` cerrada y respuesta enviada al usuario.")

    # 📦 Publicar resumen en #resolucion-de-peticiones
    embed_resolucion = discord.Embed(
        title="📌 Petición Resuelta",
        color=discord.Color.green()
    )
    embed_resolucion.add_field(name="🔢 Código de solicitud", value=f"`{codigo}`", inline=False)
    embed_resolucion.add_field(name="👤 Usuario solicitante", value=miembro.mention, inline=True)
    embed_resolucion.add_field(name="🔧 Cerrada por", value=ctx.author.mention, inline=True)
    embed_resolucion.add_field(name="📝 Contenido original", value=contenido_peticion[:1024], inline=False)
    embed_resolucion.add_field(name="✅ Resolución", value=respuesta[:1024], inline=False)
    embed_resolucion.set_footer(text=f"ID del solicitante: {miembro.id}")

    await canal_resolucion.send(embed=embed_resolucion)

async def sorteo_torneo_handle(ctx, codigo_torneo: str, premio: str = "Premio del sorteo"):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!sorteo-torneo"):
        return
    
    if codigo_torneo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
                "Por favor, respóndeme con el **código del torneo** del que quieres hacer el sorteo. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!sorteo-torneo <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    if not await moderador_permisos_handle(ctx):
      return

    url_get = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"

    async with aiohttp.ClientSession() as session:
        async with session.get(url_get, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                await ctx.send(f"❌ Error al obtener inscritos: {error_text}")
                return
            data = await resp.json()

    # Extraer IDs y resolver miembros
    candidatos = []
    for p in data:
        participante = p.get("participant", {})
        discord_id = participante.get("name")
        try:
            miembro = await ctx.guild.fetch_member(int(discord_id))
            candidatos.append(miembro)
        except (ValueError, discord.NotFound):
            continue  # Saltamos si no es un ID válido o no está en el servidor

    if not candidatos:
        await ctx.send("⚠️ No hay participantes válidos para el sorteo.")
        return

    # Elegir ganador aleatorio
    ganador = random.choice(candidatos)

    # Mensaje al moderador
    try:
        await ctx.author.send(
            f"🎉 Sorteo realizado para el torneo `{codigo_torneo}`\n"
            f"🏆 Ganador: {ganador.display_name} ({ganador.mention})\n"
            f"🎁 Premio: {premio}"
        )
    except discord.Forbidden:
        await ctx.send("⚠️ No pude enviarte mensaje privado con el resultado.")

    # Mensaje al ganador
    try:
        await ganador.send(
            f"🎉 ¡Felicidades! Has sido seleccionado en un sorteo del torneo `{codigo_torneo}`.\n"
            f"🎁 Te ha tocado: {premio}"
        )
    except discord.Forbidden:
        await ctx.send(f"⚠️ No pude enviar mensaje privado a {ganador.display_name}.")

async def moderador_permisos_handle(ctx, only_check: bool = False) -> bool:
    autor = ctx.author
    servidor = ctx.guild
    es_dueno = autor == servidor.owner
    rol_moderador = discord.utils.get(servidor.roles, name="admin")
    tiene_permiso = (
        es_dueno
        or (rol_moderador is not None and rol_moderador in autor.roles)
    )

    if not tiene_permiso:
        if not only_check:
            # await asignar_strike_automatico(ctx)
            await ctx.author.send("❌ No tienes permisos de moderador.")
            pass
        return False

    return True

async def nuevo_sorteo_handle(ctx, *, args: str = None):
    await borrar_mensaje_seguro(ctx)

    if not await moderador_permisos_handle(ctx):
        return

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!nuevo_sorteo"):
        return

    author = ctx.author

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        if not args or len([p.strip() for p in args.split("|")]) < 4:
            await author.send("📩 Vamos a crear un nuevo sorteo. Responde a las siguientes preguntas:")

            await author.send("1️⃣ ¿Cuál es el **código** del sorteo?")
            codigo_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            codigo = codigo_msg.content.strip()

            await author.send("2️⃣ ¿Cuál es la **fecha límite** del sorteo?")
            fecha_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            fecha = fecha_msg.content.strip()

            await author.send("3️⃣ ¿Cuál es el **regalo** del sorteo?")
            regalo_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            regalo = regalo_msg.content.strip()

        else:
            _, codigo, fecha, regalo = [p.strip() for p in args.split("|")]

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentarlo con `!nuevo_sorteo`.")
        return
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes por privado. Activa los DMs o vuelve a intentarlo desde el canal.")
        return

    # Crear el embed para el canal de anuncios
    embed = discord.Embed(
        title="🎁 ¡Nuevo Sorteo Activo!",
        description=f"**Código:** `{codigo}`\n**Fecha límite:** {fecha}\n**Regalo:** {regalo}",
        color=discord.Color.gold()
    )
    embed.set_footer(text="¡Participa antes de que finalice el sorteo!")

    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-tablon-anuncios")
    if canal_anuncios:
        await canal_anuncios.send(embed=embed)
    else:
        await author.send("⚠️ No encontré el canal `#anuncios`.")

    canal_sorteos_activos = discord.utils.get(ctx.guild.text_channels, name="sorteos-activos")
    if canal_sorteos_activos:
        await canal_sorteos_activos.send(f"🎉 **Sorteo activo:** `{codigo}`\n📅 **Fecha:** {fecha}\n🎁 **Regalo:** {regalo}")
        await author.send(f"🎉 **se ha creado un nuevo sorteo con el codigo:** `{codigo}`")
    else:
        await author.send("⚠️ No encontré el canal `#sorteos-activos`.")

async def realizar_sorteo_handle(ctx, codigo: str):
    await borrar_mensaje_seguro(ctx)

    if not await moderador_permisos_handle(ctx):
        return

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!realizar-sorteo"):
        return
    
    if codigo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del Sorteo.\n"
                "Por favor, respóndeme con el **código del sorteo** del que quieres hacer el sorteo. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo = respuesta.content.strip()

            if not codigo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!sorteo-torneo <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-sorteos")
    canal_sorteos_activos = discord.utils.get(ctx.guild.text_channels, name="sorteos-activos")
    canal_publicacion = ctx.guild.get_channel(1387389356464934993)

    if not canal_inscritos or not canal_sorteos_activos:
        await ctx.send("❌ No se encontraron los canales `#inscritos-sorteos` o `#sorteos-activos`.")
        return

    # Buscar inscritos válidos al sorteo
    mensajes = [msg async for msg in canal_inscritos.history(limit=200)]
    inscritos = []

    for msg in mensajes:
        partes = msg.content.split("|")
        if len(partes) >= 3:
            codigo_msg = partes[1].strip()
            user_id_str = partes[2].strip().split()[0]

            if codigo_msg == codigo:
                try:
                    user = await ctx.guild.fetch_member(int(user_id_str))
                    inscritos.append(user)
                except (discord.NotFound, ValueError):
                    continue

    if not inscritos:
        await ctx.send(f"❌ No hay inscritos para el sorteo `{codigo}`.")
        return

    # Escoger ganador
    ganador_user = random.choice(inscritos)

    # Enviar mensajes privados
    try:
        await ganador_user.send(f"🎉 ¡Has ganado el sorteo `{codigo}`! Felicidades.")
        await ctx.author.send(f"✅ El ganador del sorteo `{codigo}` es {ganador_user.mention}. Se le ha notificado por privado.")
    except discord.Forbidden:
        await ctx.send(f"⚠️ No pude enviar mensaje al ganador ({ganador_user.mention}), tiene los DMs cerrados.")

    # Eliminar todos los inscritos de ese sorteo con purge()
    eliminados_msgs = await canal_inscritos.purge(
        limit=200,
        check=lambda m: f"| {codigo} |" in m.content  # asegura que el código esté en el mensaje
    )
    eliminados = len(eliminados_msgs)

    # Eliminar el sorteo del canal de sorteos activos
    await canal_sorteos_activos.purge(
        limit=100,
        check=lambda m: m.content.startswith("🎉") and codigo in m.content
    )

    await canal_publicacion.send(f"✅ Sorteo `{codigo}` finalizado. {eliminados} inscritos eliminados y sorteo activo eliminado.\n🏆 ✅ El ganador del sorteo `{codigo}` es {ganador_user.mention}.")



async def listar_torneos_handle(ctx):
    await borrar_mensaje_seguro(ctx)
   
    if not await moderador_permisos_handle(ctx):
        return

    await ctx.author.send("📋 Obteniendo lista de torneos...")

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.challonge.com/v1/tournaments.json",
            auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)
        ) as resp:
            if resp.status != 200:
                await ctx.author.send("❌ Error al obtener torneos de Challonge.")
                return
            torneos = await resp.json()

    # 🔹 Filtrar torneos válidos
    torneos_validos = []
    for t in torneos:
        torneo = t["tournament"]
        state = torneo.get("state")
        open_matches = torneo.get("open_match_count", 0)

        if state == "pending" or (state == "complete" and open_matches == 0):
            torneos_validos.append(torneo)

    if not torneos_validos:
        await ctx.author.send("❌ No hay torneos válidos para eliminar.")
        return

    mensaje = "📋 **Torneos válidos para eliminar:**\n"

    for i, t in enumerate(torneos_validos):
        mensaje += f"{i+1}. {t['name']} (Estado: {t['state']})\n"  # fallback a números normales

    mensaje += "✏️ Escribe el número del torneo que deseas eliminar:"

    await ctx.author.send(mensaje)

    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        seleccion = respuesta.content.strip()
        if not seleccion.isdigit() or int(seleccion) < 1 or int(seleccion) > len(torneos_validos):
            await ctx.author.send("❌ Selección inválida. Cancelando.")
            return
        torneo_elegido = torneos_validos[int(seleccion)-1]
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Cancelando operación.")
        return

    # 🔹 Confirmar eliminación
    await ctx.author.send(f"⚠️ Estás a punto de eliminar el torneo `{torneo_elegido['name']}`. ¿Confirmas? (sí/no)")
    try:
        confirmacion = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        if confirmacion.content.lower() not in ["sí", "si", "s"]:
            await ctx.author.send("❌ Operación cancelada.")
            return
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Cancelando operación.")
        return

    # 🔹 Eliminar torneo
    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"https://api.challonge.com/v1/tournaments/{torneo_elegido['id']}.json",
            auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)
        ) as resp:
            if resp.status == 200:
                await ctx.author.send(f"✅ Torneo `{torneo_elegido['name']}` eliminado correctamente.")
            else:
                await ctx.author.send(f"❌ Error al eliminar el torneo. Status: {resp.status}")
                
async def nuevo_comunicado_handle(ctx, mensaje: str = None):
    await borrar_mensaje_seguro(ctx)
    
    if not await moderador_permisos_handle(ctx):
        return

    canal = ctx.guild.get_channel(1387389356464934993)

    # Si no hay mensaje, pedimos por DM
    if not mensaje:
        try:
            await ctx.author.send(
                "📩 No escribiste el Mensaje para el canal 📰-tablon‐anuncios.\n"
                "Por favor, respóndeme con el mensaje que quieras transmitir. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            mensaje = respuesta.content.strip()

            if not mensaje:
                await ctx.author.send("❌ El mensaje no puede estar vacío. Cancelado.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!nuevo_comunicado mensaje`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs.")
            return

    # Enviar comunicado al canal con @everyone
    embed = discord.Embed(
        title="📢 Comunicado",
        description=mensaje,
        color=0x00ffcc
    )

    await canal.send("@everyone", embed=embed)
    await ctx.author.send(f"✅ Comunicado enviado a {canal.mention}")

async def eliminar_decks_handle(ctx, codigo_torneo: str = None):
    """
    Permite eliminar decks de un torneo. Si no se proporciona código, pide al usuario seleccionarlo.
    Se puede eliminar decks individuales o todos a la vez.
    """
    await borrar_mensaje_seguro(ctx)
    
    if not await moderador_permisos_handle(ctx):
        return

    # 1️⃣ Obtener código de torneo si no se proporcionó
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(ctx, "📋 Debes seleccionar un torneo para eliminar listas.")
        if not codigo_torneo:
            return await ctx.send("❌ No se seleccionó ningún torneo. Operación cancelada.")

    # 2️⃣ Buscar canal de decks
    channel = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    if not channel:
        return await ctx.send("❌ No encontré el canal `submitted-decks` en este servidor.")

    # 3️⃣ Obtener todos los mensajes del canal y filtrar por torneo
    decks_encontrados = []

    async for message in channel.history(limit=None):
        for embed in message.embeds:
            if not embed.description:
                continue

            # Buscar el código de torneo en el description
            if codigo_torneo not in embed.description:
                continue

            # Extraer campos de los fields
            campos = {field.name.lower(): field.value for field in embed.fields}
            nombre_deck_extraido = embed.title.replace("🃏 Deck Subido: ", "").replace("🃏 Deck Actualizado: ", "")

            # Intentar extraer jugador y su ID
            jugador_field = campos.get("jugador", "Desconocido")
            jugador_id = None
            if "(ID:" in jugador_field:
                try:
                    jugador_id = int(jugador_field.split("(ID:")[1].split(")")[0].strip())
                except ValueError:
                    pass

            decks_encontrados.append({
                "mensaje": message,
                "nombre_deck": nombre_deck_extraido,
                "jugador": jugador_field,
                "jugador_id": jugador_id,
                "archetype": campos.get("archetype", "Desconocido"),
                "decklist": campos.get("decklist", ""),
                "sideboard": campos.get("sideboard", "N/A")
            })

    if not decks_encontrados:
        return await ctx.author.send(f"📭 No se encontraron decks para el torneo `{codigo_torneo}`.")

    # 4️⃣ Mostrar lista de decks para eliminar
    texto = f"📋 Decks encontrados para el torneo `{codigo_torneo}`:\n"
    for idx, deck in enumerate(decks_encontrados, start=1):
        texto += f"{idx}. {deck['nombre_deck']} → {deck['archetype']} (Jugador: {deck['jugador']})\n"

    try:
        await ctx.author.send(texto)
    except discord.Forbidden:
        return await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")

    # 5️⃣ Pedir selección
    await ctx.author.send(
        "✏️ Responde con los **números separados por coma** de los decks a eliminar (ej: 1,3,4) "
        "o escribe `todos` para eliminar todos los decks. Tienes 120 segundos."
    )

    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=120)
        contenido = respuesta.content.strip().lower()

        if contenido in ("todos", "all"):
            # Seleccionar todos los decks
            to_delete = [deck["mensaje"] for deck in decks_encontrados]
        else:
            # Selección por números separados por coma
            indices = [int(x.strip())-1 for x in contenido.split(",")]
            to_delete = [decks_encontrados[i]["mensaje"] for i in indices if 0 <= i < len(decks_encontrados)]

    except ValueError:
        return await ctx.author.send("❌ Entrada inválida. Debes poner números separados por coma o 'todos'.")
    except asyncio.TimeoutError:
        return await ctx.author.send("⏰ Tiempo agotado. Operación cancelada.")

    # 6️⃣ Confirmar borrado
    eliminados = 0
    for msg in to_delete:
        try:
            await msg.delete()
            eliminados += 1
        except discord.Forbidden:
            await ctx.author.send(f"❌ No tengo permisos para eliminar el mensaje de {msg.author}.")
        except discord.HTTPException:
            await ctx.author.send(f"❌ No se pudo eliminar el mensaje de {msg.author}.")

    await ctx.author.send(f"✅ Eliminados {eliminados} decks del torneo `{codigo_torneo}`.")
