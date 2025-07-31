
import discord
from datetime import datetime
import aiohttp
import random
import config

from utils.commons import borrar_mensaje_seguro, validar_canal_correcto 

async def aplicar_strike(ctx, miembro: discord.Member):
     # Intentar eliminar el mensaje del canal público
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!strike"):
        return
   
    servidor = ctx.guild

    # Verificar permisos
    if not await moderador_permisos_handle(ctx):
      return
    
    if miembro is None:
        await ctx.author.send("❌ Debes mencionar a un usuario. Ejemplo: `!strike @Usuario`")
        return

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
    
    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios")
    await canal_anuncios.send(f"⚠️ Hemos decidido que {miembro.mention} Permanezca una semana en el Hielo, la proxima vez le invitaremos a que abandone The Klub")

async def aplicar_out(ctx, miembro: discord.Member):
     # Intentar eliminar el mensaje del canal público
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!out"):
        return
        
    servidor = ctx.guild
    
    # Verificar permisos
    if not await moderador_permisos_handle(ctx):
      return

    if miembro is None:
        await ctx.author.send("❌ Debes mencionar a un usuario. Ejemplo: `!out @Usuario`")
        return
    
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
    
    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios")
    await canal_anuncios.send(f"⚠️ Hemos invitado a abandonar el servidor a {miembro.mention}, ya no podra volver a entrar a The Klub.")

async def eliminar_mensajes(ctx, canal: discord.TextChannel, cantidad: int):
    
    # Verificar permisos
    
    if not await moderador_permisos_handle(ctx):
      return
    
   
    # Validar argumentos
    if canal is None or cantidad is None:
        await ctx.author.send(
            "❌ Uso incorrecto del comando.\n"
            "✅ Formato: `!eliminar-mensajes #canal cantidad`\n"
            "_Ejemplo:_ `!eliminar-mensajes #general 50`"
        )
        return

   
    # Validar cantidad
    if cantidad <= 0 or cantidad > 1000:
        await ctx.author.send("⚠️ La cantidad debe ser entre 1 y 1000 mensajes.")
        return

    # Intentar borrar mensajes
    try:
        mensajes_borrados = await canal.purge(limit=cantidad)
        await ctx.send(f"✅ Se han eliminado {len(mensajes_borrados)} mensajes de {canal.mention}.", delete_after=5)
    except discord.Forbidden:
        await ctx.author.send("❌ No tengo permisos para borrar mensajes en ese canal.")
    except discord.HTTPException as e:
        await ctx.author.send(f"⚠️ Hubo un error al intentar borrar mensajes: {e}")


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
    
    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios")
    await canal_anuncios.send(f"⚠️ Hemos decidido que {autor.mention} Permanezca una semana en el Hielo, la proxima vez le invitaremos a que abandone The Klub")

def get_mensaje_strike():
    return (
        "Oye... te lo voy a decir solo una vez.\n\n"
        "Lo que hiciste, no va con las reglas de The Klub. Aquí se viene a respetar la energía, la gente y el espacio. "
        "No te echamos hoy... pero la próxima, estás fuera sin saludo ni explicación.\n\n"
        "Este sitio no es un “vale todo”. Es un “vale lo que yo diga”.\n"
        "Y tú ya estás en tu última vida.\n\n"
        "Decide bien cuál va a ser tu siguiente movimiento."
    )

async def cerrar_peticion_handle(ctx, codigo, respuesta):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "peticiones-de-usuarios", "!cerrar-peticion"):
        return
    if not await moderador_permisos_handle(ctx):
      return
    
    if codigo is None:
        await ctx.author.send("❌ Debes mencionar a un codigo de peticion y una respuesta . Ejemplo: `!cerrar-peticion codigo respuesta`")
        return
    
    canal_peticiones = discord.utils.get(ctx.guild.text_channels, name="peticiones-de-usuarios")
    canal_resolucion = discord.utils.get(ctx.guild.text_channels, name="resolucion-de-peticiones")

    if not canal_peticiones or not canal_resolucion:
        await ctx.author.send("❌ No se encontraron los canales necesarios (`#peticiones-de-usuarios` o `#resolucion-de-peticiones`).")
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
        await ctx.author.send("❌ Debes mencionar a un codigo de sorteo. Ejemplo: `!sorteo-torneo codigo`")
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

async def moderador_permisos_handle(ctx):
    autor = ctx.author
    servidor = ctx.guild
    es_dueno = autor == servidor.owner
    rol_moderador = discord.utils.get(servidor.roles, name="admin")
    tiene_permiso = es_dueno | (rol_moderador and rol_moderador in autor.roles)

    if not tiene_permiso:
        await asignar_strike_automatico(ctx)
        return False

    return True

async def nuevo_sorteo_handle(ctx, args: str):
    await borrar_mensaje_seguro(ctx)

    if not await moderador_permisos_handle(ctx):
      return

    # Validar canal correcto
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!nuevo_sorteo"):
        return
    
    if args is None:
        await ctx.author.send("❌ Formato incorrecto. Usa:\n`!nuevo_sorteo nuevo-sorteo | codigo | fecha | regalo`")
        return

    # Separar argumentos
    partes = [p.strip() for p in args.split("|")]
    _, codigo, fecha, regalo = partes

    # Crear el embed para el canal de anuncios
    embed = discord.Embed(
        title="🎁 ¡Nuevo Sorteo Activo!",
        description=f"**Código:** `{codigo}`\n**Fecha límite:** {fecha}\n**Regalo:** {regalo}",
        color=discord.Color.gold()
    )
    embed.set_footer(text="¡Participa antes de que finalice el sorteo!")

    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios")
    if canal_anuncios:
        await canal_anuncios.send(embed=embed)
    else:
        await ctx.author.send("⚠️ No encontré el canal `#anuncios`.")

    # Agregar al canal de sorteos activos
    canal_sorteos_activos = discord.utils.get(ctx.guild.text_channels, name="sorteos-activos")
    if canal_sorteos_activos:
        await canal_sorteos_activos.send(f"🎉 **Sorteo activo:** `{codigo}`\n📅 **Fecha:** {fecha}\n🎁 **Regalo:** {regalo}")
    else:
        await ctx.author.send("⚠️ No encontré el canal `#sorteos-activos`.")

async def realizar_sorteo_handle(ctx, codigo: str):
    await borrar_mensaje_seguro(ctx)

    if not await moderador_permisos_handle(ctx):
        return

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!realizar-sorteo"):
        return
    
    if codigo is None:
        await ctx.author.send("❌ Debes mencionar a un codigo de sorteo. Ejemplo: `!realizar-sorteo codigo`")
        return

    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-sorteos")
    canal_sorteos_activos = discord.utils.get(ctx.guild.text_channels, name="sorteos-activos")

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
                    inscritos.append((msg, user))
                except (discord.NotFound, ValueError):
                    continue

    if not inscritos:
        await ctx.send(f"❌ No hay inscritos para el sorteo `{codigo}`.")
        return

    
    usuario_ganador = random.choice(inscritos)

    # Enviar mensajes privados
    try:
        await usuario_ganador.send(f"🎉 ¡Has ganado el sorteo `{codigo}`! Felicidades.")
        await ctx.author.send(f"✅ El ganador del sorteo `{codigo}` es {usuario_ganador.mention}. Se le ha notificado por privado.")
    except discord.Forbidden:
        await ctx.send(f"⚠️ No pude enviar mensaje al ganador ({usuario_ganador.mention}), tiene los DMs cerrados.")

    # Eliminar todos los inscritos de ese sorteo
    eliminados = 0
    for msg, _ in inscritos:
        try:
            await msg.delete()
            eliminados += 1
        except discord.HTTPException:
            continue

    # Eliminar el sorteo del canal de sorteos activos (más flexible)
    mensajes_sorteos = [msg async for msg in canal_sorteos_activos.history(limit=100)]
    for msg in mensajes_sorteos:
        if msg.content.startswith("🎉") and codigo in msg.content:
            try:
                await msg.delete()
                break
            except discord.HTTPException:
                continue

    await ctx.send(f"✅ Sorteo `{codigo}` finalizado. {eliminados} inscritos eliminados y sorteo activo eliminado.")