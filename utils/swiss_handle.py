# utils/swiss_handles.py
import discord

from utils.swiss_manager import SwissManager
from utils.commons import borrar_mensaje_seguro

# ------------------------------------------------------------
# HANDLES
# ------------------------------------------------------------

async def swiss_nuevo_handle(ctx, codigo: str, nombre: str, max_jugadores: int, nivel: str = "todos"):
    """Crea un torneo suizo."""
    await borrar_mensaje_seguro(ctx)

    # Solo admins
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador para crear torneos.")
        return

    manager = SwissManager(ctx.bot, ctx.guild)
    try:
        await manager.crear_torneo(codigo, nombre, max_jugadores, nivel)
        await ctx.author.send(f"✅ Torneo **{nombre}** creado con código `{codigo}`.")
        # Anunciar en el canal de anuncios
        canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
        if canal_anuncios:
            await canal_anuncios.send(
                f"📢 **Nuevo torneo suizo creado!**\n"
                f"🏷️ **Nombre:** {nombre}\n"
                f"👥 **Máximo jugadores:** {max_jugadores}\n"
                f"🔒 **Nivel:** {nivel}\n"
                f"🏷️ **Código:** `{codigo}`\n"
                f"📌 Usa `!inscribir-swiss {codigo}` para apuntarte."
            )
    except Exception as e:
        await ctx.author.send(f"❌ Error al crear el torneo: {e}")

async def swiss_inscribir_handle(ctx, codigo: str):
    """Inscribe al usuario en un torneo suizo."""
    await borrar_mensaje_seguro(ctx)

    manager = SwissManager(ctx.bot, ctx.guild)

    # Verificar que el torneo existe y el usuario tiene rol permitido
    # (podríamos obtener el nivel del torneo del estado, pero por simplicidad lo dejamos)
    ok = await manager.inscribir_jugador(codigo, ctx.author.id)
    if ok:
        await ctx.author.send(f"✅ Te has inscrito en el torneo `{codigo}`.")
        # Anunciar en cartelera
        canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
        if canal_anuncios:
            await canal_anuncios.send(f"📥 {ctx.author.mention} se ha inscrito en el torneo `{codigo}`.")
    else:
        await ctx.author.send("❌ No se pudo inscribir. Puede que ya estés inscrito o el torneo no existe.")

async def swiss_desinscribir_handle(ctx, codigo: str):
    """Desinscribe al usuario de un torneo suizo."""
    await borrar_mensaje_seguro(ctx)

    manager = SwissManager(ctx.bot, ctx.guild)
    ok = await manager.desinscribir_jugador(codigo, ctx.author.id)
    if ok:
        await ctx.author.send(f"✅ Te has desinscrito del torneo `{codigo}`.")
        canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
        if canal_anuncios:
            await canal_anuncios.send(f"📤 {ctx.author.mention} se ha desinscrito del torneo `{codigo}`.")
    else:
        await ctx.author.send("❌ No estabas inscrito o el torneo no existe.")

async def swiss_iniciar_handle(ctx, codigo: str):
    """Inicia un torneo suizo (genera ronda 1). Solo admin."""
    await borrar_mensaje_seguro(ctx)

    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    manager = SwissManager(ctx.bot, ctx.guild)
    participantes = await manager.get_participantes(codigo)
    if len(participantes) < 2:
        await ctx.author.send("❌ Se necesitan al menos 2 jugadores para iniciar el torneo.")
        return

    await manager.generar_ronda(codigo, 1)

    # Publicar emparejamientos en el canal de citas
    canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
    if canal_citas:
        # Leer la ronda del canal de rondas
        channel = await manager._get_channel(f"torneo-{codigo}-rondas")
        if channel:
            async for msg in channel.history(limit=1, oldest_first=False):
                if msg.author == ctx.bot.user and "Ronda 1" in msg.content:
                    await canal_citas.send(f"📢 **Emparejamientos Ronda 1 - Torneo {codigo}**\n{msg.content}")
                    break

    await ctx.author.send(f"✅ Torneo `{codigo}` iniciado. Ronda 1 publicada.")

async def swiss_reportar_handle(ctx, codigo: str, jugador1: discord.Member, resultado: str, jugador2: discord.Member):
    """Reporta un resultado en formato X-Y."""
    await borrar_mensaje_seguro(ctx)

    # Verificar que el usuario es uno de los jugadores o admin
    if ctx.author.id not in (jugador1.id, jugador2.id) and not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Solo los jugadores o un administrador pueden reportar.")
        return

    manager = SwissManager(ctx.bot, ctx.guild)
    ok, msg = await manager.reportar_resultado(codigo, jugador1.id, resultado, jugador2.id)
    if ok:
        await ctx.author.send(f"✅ {msg}")
        # Publicar en canal de resultados
        canal_resultados = discord.utils.get(ctx.guild.text_channels, name="🍺-quién‐se‐lleva‐la‐ronda")
        if canal_resultados:
            await canal_resultados.send(
                f"🏆 Resultado en `{codigo}`:\n"
                f"**{jugador1.display_name}** {resultado} **{jugador2.display_name}**"
            )
    else:
        await ctx.author.send(f"❌ {msg}")

async def swiss_clasificacion_handle(ctx, codigo: str):
    """Muestra la clasificación actual del torneo."""
    await borrar_mensaje_seguro(ctx)

    manager = SwissManager(ctx.bot, ctx.guild)
    ranking = await manager.calcular_clasificacion(codigo)
    if not ranking:
        await ctx.author.send("❌ No se pudo calcular la clasificación.")
        return

    # Enviar por DM un resumen
    lines = ["📊 **Clasificación actual**", "Rk | Jugador | Pts | W-L-D | Dif"]
    for i, (pid, data) in enumerate(ranking[:10], 1):
        nombre = (ctx.guild.get_member(pid) or discord.Object(id=pid)).display_name if hasattr(ctx.guild.get_member(pid), 'display_name') else f"<@{pid}>"
        lines.append(f"{i:2} | {nombre:12} | {data['mp']:3.0f} | {data['wins']}-{data['losses']}-{data['draws']} | {data['diff']:+}")
    await ctx.author.send("\n".join(lines))

async def swiss_siguiente_ronda_handle(ctx, codigo: str):
    """Fuerza la siguiente ronda (si no se ha hecho automáticamente)."""
    await borrar_mensaje_seguro(ctx)

    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    manager = SwissManager(ctx.bot, ctx.guild)
    # Leer ronda actual del estado
    estado = await manager._read_lines(f"torneo-{codigo}-estado")
    if not estado:
        await ctx.author.send("❌ No se encontró el estado del torneo.")
        return
    ronda_actual = int(estado[0].split("|")[1]) if "|" in estado[0] else 0
    nueva_ronda = ronda_actual + 1
    await manager.generar_ronda(codigo, nueva_ronda)
    await ctx.author.send(f"✅ Ronda {nueva_ronda} generada.")

async def swiss_eliminar_handle(ctx, codigo: str):
    """Elimina un torneo suizo (borra todos los canales asociados)."""
    await borrar_mensaje_seguro(ctx)

    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    manager = SwissManager(ctx.bot, ctx.guild)
    # Eliminar canales del torneo
    for sufijo in ["participantes", "rondas", "clasificacion", "estado"]:
        channel = await manager._get_channel(f"torneo-{codigo}-{sufijo}")
        if channel:
            await channel.delete()
    # Eliminar de torneos-activos (línea que contenga el código)
    canal_activos = await manager._get_channel("torneos-activos")
    if canal_activos:
        async for msg in canal_activos.history(limit=100):
            if msg.author == ctx.bot.user and codigo in msg.content:
                await msg.delete()
                break
    await ctx.author.send(f"✅ Torneo `{codigo}` eliminado.")