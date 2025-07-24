
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
        await ctx.send("❌ Debes mencionar a un usuario. Ejemplo: `!strike @Usuario`")
        return

    rol_strike = discord.utils.get(servidor.roles, name="Strike")
    if not rol_strike:
        await ctx.send("⚠️ El rol `Strike` no existe en el servidor.")
        return

    if rol_strike in miembro.roles:
        await ctx.send(f"ℹ️ {miembro.mention} ya tiene el rol `Strike`.")
        return

    try:
        await miembro.add_roles(rol_strike, reason="Strike manual asignado por Moderador.")
        await miembro.send(get_mensaje_strike())
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para asignar el rol o enviar mensaje privado.")
        return

    await ctx.send(f"✅ {miembro.mention} ha recibido un **Strike**.")

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
        await ctx.send("❌ Debes mencionar a un usuario. Ejemplo: `!out @Usuario`")
        return
    
    rol_out = discord.utils.get(servidor.roles, name="Out")
    if not rol_out:
        await ctx.send("⚠️ El rol `Out` no existe en el servidor.")
        return

    if rol_out in miembro.roles:
        await ctx.send(f"ℹ️ {miembro.mention} ya tiene el rol `Out`.")
        return

    try:
        await miembro.add_roles(rol_out, reason="Out manual asignado por moderador.")
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para asignar el rol. Revisa la jerarquía de roles.")
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
        await ctx.send(f"⚠️ {miembro.mention} no tiene los mensajes privados habilitados.")

    await ctx.send(f"✅ {miembro.mention} ha sido expulsado de la comunidad.")

async def eliminar_mensajes(ctx, canal: discord.TextChannel, cantidad: int):
    
    # Verificar permisos
    
    if not await moderador_permisos_handle(ctx):
      return

    # Validar argumentos
    if canal is None or cantidad is None:
        await ctx.send(
            "❌ Uso incorrecto del comando.\n"
            "✅ Formato: `!eliminar-mensajes #canal cantidad`\n"
            "_Ejemplo:_ `!eliminar-mensajes #general 50`"
        )
        return

   
    # Validar cantidad
    if cantidad <= 0 or cantidad > 1000:
        await ctx.send("⚠️ La cantidad debe ser entre 1 y 1000 mensajes.")
        return

    # Intentar borrar mensajes
    try:
        mensajes_borrados = await canal.purge(limit=cantidad)
        await ctx.send(f"✅ Se han eliminado {len(mensajes_borrados)} mensajes de {canal.mention}.", delete_after=5)
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para borrar mensajes en ese canal.")
    except discord.HTTPException as e:
        await ctx.send(f"⚠️ Hubo un error al intentar borrar mensajes: {e}")


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

async def cerrar_peticion_handle(ctx, codigo, respuesta):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "peticiones-de-usuarios", "!cerrar-peticion"):
        return
    if not await moderador_permisos_handle(ctx):
      return
    canal_peticiones = discord.utils.get(ctx.guild.text_channels, name="peticiones-de-usuarios")
    canal_resolucion = discord.utils.get(ctx.guild.text_channels, name="resolucion-de-peticiones")

    if not canal_peticiones or not canal_resolucion:
        await ctx.send("❌ No se encontraron los canales necesarios (`#peticiones-de-usuarios` o `#resolucion-de-peticiones`).")
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