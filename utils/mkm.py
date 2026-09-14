# utils/mkm.py
import discord
import asyncio
from typing import Optional, List, Dict
from .mkm_json_loader import mkm_loader
from .commons import borrar_mensaje_seguro

# Lista de expansiones para autocompletar (obtenida del loader)
EXPANSION_NAMES = mkm_loader.expansion_names if hasattr(mkm_loader, 'expansion_names') else []

async def _send_dm_or_channel(ctx, content=None, embed=None):
    """Envía por DM si es posible, si no, al canal."""
    try:
        if embed:
            await ctx.author.send(embed=embed)
        elif content:
            await ctx.author.send(content)
    except discord.Forbidden:
        if embed:
            await ctx.send(embed=embed)
        elif content:
            await ctx.send(content)

async def _ask_for_choice(ctx, versions: List[Dict], card_name: str) -> Optional[Dict]:
    """Muestra lista numerada y espera elección del usuario."""
    author = ctx.author
    mensaje = f"📋 **{len(versions)} versiones encontradas para '{card_name}':**\n"
    for idx, v in enumerate(versions, 1):
        precio = v.get('avg') or 0
        expansion = v.get('expansion_name', 'Unknown')
        mensaje += f"{idx}. **{expansion}** → {precio:.2f}€\n"
    mensaje += "\n✏️ Escribe el **número** de la versión que quieres ver (o 'cancelar' para salir):"

    await author.send(mensaje)

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        contenido = respuesta.content.strip().lower()

        if contenido in ("cancelar", "cancela", "cancel", "exit", "salir"):
            await author.send("❌ Operación cancelada.")
            return None

        if not contenido.isdigit():
            await author.send("❌ Debes escribir un número válido.")
            return None

        idx = int(contenido) - 1
        if idx < 0 or idx >= len(versions):
            await author.send(f"❌ Número no válido. Elige entre 1 y {len(versions)}.")
            return None

        return versions[idx]

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentarlo.")
        return None

async def mkm_precio_handle(ctx, card_name: Optional[str] = None):
    """Consulta el precio de una carta con wizard y selección de versión."""
    await borrar_mensaje_seguro(ctx)
    author = ctx.author

    # Cargar datos si no están listos
    if not mkm_loader._loaded:
        await author.send("⏳ Cargando datos de Cardmarket... (puede tardar unos segundos)")
        await mkm_loader.load_data()
        if not mkm_loader._loaded:
            await author.send("❌ No se pudieron cargar los datos. Intenta de nuevo en unos minutos.")
            return

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    # --- Wizard si no hay argumentos ---
    expansion = None
    if not card_name:
        try:
            await author.send("🔍 **¿Qué carta quieres consultar?**\nEscribe el nombre exacto o parcial (ej: 'Stifle').")
            msg_nombre = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            card_name = msg_nombre.content.strip()
            if not card_name:
                await author.send("❌ Nombre no válido. Cancelando.")
                return

            await author.send(f"📦 ¿Quieres limitar la búsqueda a una expansión?\nEscribe el nombre o 'no' para buscar en todas.")
            msg_exp = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            exp_input = msg_exp.content.strip()
            if exp_input.lower() not in ("no", "n", ""):
                exp_lower = exp_input.lower().strip()
                # Buscar coincidencia exacta en el diccionario
                if exp_lower in mkm_loader.premodern_expansions:
                    expansion = exp_input  # Usamos el nombre original del usuario
                else:
                    # Coincidencia parcial
                    matches = [name for name in mkm_loader.premodern_expansions.keys() if exp_lower in name]
                    if len(matches) == 1:
                        expansion = matches[0].title()  # Capitalizar
                        await author.send(f"✅ Usando expansión: **{expansion}**")
                    elif len(matches) > 1:
                        # Mostrar las opciones y pedir que elija
                        opciones = "\n".join([f"{i+1}. {name.title()}" for i, name in enumerate(matches[:5])])
                        await author.send(f"🔍 Varias expansiones coinciden:\n{opciones}\nEscribe el número:")
                        try:
                            resp_num = await ctx.bot.wait_for("message", check=dm_check, timeout=30.0)
                            if resp_num.content.isdigit():
                                idx = int(resp_num.content) - 1
                                if 0 <= idx < len(matches):
                                    expansion = matches[idx].title()
                                else:
                                    await author.send("❌ Número no válido. Buscaré en todas.")
                                    expansion = None
                            else:
                                await author.send("❌ No es un número. Buscaré en todas.")
                                expansion = None
                        except asyncio.TimeoutError:
                            await author.send("⏰ Tiempo agotado. Buscaré en todas.")
                            expansion = None
                    else:
                        await author.send(f"⚠️ No reconozco '{exp_input}'. Buscaré en todas.")
                        expansion = None
            else:
                expansion = None
        except asyncio.TimeoutError:
            await author.send("⏰ Tiempo agotado. Vuelve a intentarlo con `!mkm-precio <nombre>`.")
            return
    else:
        # Si se pasó nombre, intentar extraer expansión del final
        parts = card_name.rsplit(" ", 1)
        if len(parts) == 2:
            exp_key = parts[1].lower()
            if exp_key in mkm_loader.premodern_expansions or exp_key in mkm_loader.expansion_names:
                card_name = parts[0]
                expansion = parts[1]

    # --- Obtener todas las versiones ---
    versions = mkm_loader.get_all_versions(card_name, expansion)
    if not versions:
        await author.send(f"❌ No se encontró la carta '{card_name}'" + (f" en '{expansion}'" if expansion else ""))
        return

    # Si solo hay una versión, usarla directamente
    if len(versions) == 1:
        selected = versions[0]
    else:
        selected = await _ask_for_choice(ctx, versions, card_name)
        if selected is None:
            return

    # --- Obtener imagen de Scryfall ---
    image_url = await mkm_loader.get_card_image_url(selected['name'], selected.get('expansion_name'))

    # --- Construir embed ---
    embed = discord.Embed(
        title=f"💶 {selected['name']}",
        color=discord.Color.gold()
    )
    if image_url:
        embed.set_thumbnail(url=image_url)

    embed.add_field(name="Versión (Edición)", value=selected.get('expansion_name', 'Unknown'), inline=False)

    # Campos con manejo de None
    avg = selected.get('avg') or 0
    embed.add_field(name="Precio medio", value=f"{avg:.2f}€", inline=True)

    low = selected.get('low') or 0
    embed.add_field(name="Precio bajo", value=f"{low:.2f}€", inline=True)

    trend = selected.get('trend') or 0
    embed.add_field(name="Tendencia", value=f"{trend:.2f}€", inline=True)

    if selected.get('avg1') is not None:
        val = selected.get('avg1') or 0
        embed.add_field(name="Precio (1 día)", value=f"{val:.2f}€", inline=True)

    if selected.get('avg7') is not None:
        val = selected.get('avg7') or 0
        embed.add_field(name="Precio (7 días)", value=f"{val:.2f}€", inline=True)

    if selected.get('avg30') is not None:
        val = selected.get('avg30') or 0
        embed.add_field(name="Precio (30 días)", value=f"{val:.2f}€", inline=True)

    if selected.get('avg_foil') is not None:
        val = selected.get('avg_foil') or 0
        embed.add_field(name="Precio medio (Foil)", value=f"{val:.2f}€", inline=True)

    if selected.get('low_foil') is not None:
        val = selected.get('low_foil') or 0
        embed.add_field(name="Precio bajo (Foil)", value=f"{val:.2f}€", inline=True)

    embed.set_footer(text=f"ID Producto: {selected['idProduct']}")

    await _send_dm_or_channel(ctx, embed=embed)

async def mkm_subida_handle(ctx, old_exp: str, new_exp: str):
    """Compara precios entre dos expansiones."""
    await borrar_mensaje_seguro(ctx)

    if not mkm_loader._loaded:
        await ctx.author.send("⏳ Cargando datos de Cardmarket...")
        await mkm_loader.load_data()
        if not mkm_loader._loaded:
            await ctx.author.send("❌ No se pudieron cargar los datos.")
            return

    results, error = mkm_loader.compare_expansions(old_exp, new_exp)
    if error:
        await ctx.author.send(f"❌ {error}")
        return
    if not results:
        await ctx.author.send("⚠️ No se encontraron cartas en común.")
        return

    mensaje = "📈 **Top 10 cartas que más han subido:**\n"
    for idx, row in enumerate(results[:10], 1):
        mensaje += f"{idx}. **{row['name']}**: {row['old_price']:.2f}€ → {row['new_price']:.2f}€ (+{row['pct_change']:.1f}%)\n"

    if len(mensaje) > 1900:
        chunks = [mensaje[i:i+1900] for i in range(0, len(mensaje), 1900)]
        for chunk in chunks:
            await ctx.author.send(chunk)
    else:
        await ctx.author.send(mensaje)

async def mkm_actualizar_handle(ctx):
    """Forzar recarga de datos (solo admin)."""
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    await ctx.author.send("🔄 Recargando datos de Cardmarket...")
    await mkm_loader.load_data(force=True)
    if mkm_loader._loaded:
        await ctx.author.send("✅ Datos recargados correctamente.")
    else:
        await ctx.author.send("❌ Error al recargar.")