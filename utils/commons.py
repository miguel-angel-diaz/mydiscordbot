import asyncio
import aiohttp
import config
import discord
from functools import wraps
from discord.ext import commands


async def borrar_mensaje_seguro(ctx):
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")

async def validar_canal_correcto(ctx, canal_valido: str, comando: str):
    """
    Verifica si el comando fue usado en el canal correcto. Si no lo fue:
    - Manda un mensaje privado al autor.
    - Elimina el mensaje del canal si es posible.
    - Retorna False para indicar que no se debe continuar.
    """
    if ctx.channel.name != canal_valido:
        try:
            await ctx.author.send(
                f"❌ El comando `{comando}` solo se puede usar en el canal `#{canal_valido}`.\n"
                f"Usa el comando allí para que funcione correctamente. primer aviso."
            )
        except discord.Forbidden:
            pass  # Usuario con DMs cerrados

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass  # Bot sin permisos para borrar mensajes

        return False
    
    return True

def enviar_ayuda_handle():
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx, *args, **kwargs):
            # Si no se pasó ningún argumento posicional y no hay kwargs, consideramos que se ejecutó mal
            if not args and not kwargs:
                try:
                    await ctx.author.send(
                        f"🔔 Parece que usaste el comando `!{ctx.command.name}` sin los argumentos necesarios.\n\n"
                        f"📘 Uso correcto:\n{ctx.command.help or 'No hay ayuda disponible para este comando.'}"
                    )
                except Exception:
                    pass  # Por si tiene los DMs cerrados

            # Ejecutar el comando normalmente
            return await func(ctx, *args, **kwargs)
        return wrapper
    return decorator

def buscar_usuario_en_servidor(guild, nombre_busqueda: str):
    nombre_busqueda = nombre_busqueda.lower()
    for miembro in guild.members:
        if nombre_busqueda in miembro.display_name.lower() or nombre_busqueda in miembro.name.lower():
            return miembro
    return None

async def obtener_torneo_usuario(ctx, mensaje_inicial: str = None, timeout: int = 90):
    """
    Devuelve el código (tournament url/slug) del torneo elegido por el usuario.
    Muestra todos los torneos si el comando es 'ver-inscritos' o 'iniciar-torneo',
    y solo los torneos en los que el usuario está inscrito en otros casos.
    Retorna None en caso de error / cancelación.
    """
    # 1) Mensaje inicial opcional
    if mensaje_inicial:
        try:
            await ctx.author.send(mensaje_inicial)
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return None

    # 2) Determinar si filtramos solo torneos inscritos
    comando_actual = getattr(ctx.command, "name", "").lower()
    solo_inscritos = comando_actual not in ("ver-inscritos", "iniciar-torneo")

    # 3) Obtener lista de torneos (state=all)
    url_torneos = "https://api.challonge.com/v1/tournaments.json?state=all"
    async with aiohttp.ClientSession() as session:
        async with session.get(url_torneos, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await ctx.author.send("❌ Error al obtener la lista de torneos.")
                return None
            torneos_raw = await resp.json()

        # 4) Filtrar y construir lista
        torneos = []
        for entry in torneos_raw:
            t = entry.get("tournament", {})
            tid = t.get("url") or str(t.get("id"))
            nombre = t.get("name") or "(sin nombre)"

            if solo_inscritos:
                # Obtener participantes de este torneo
                url_participantes = f"https://api.challonge.com/v1/tournaments/{tid}/participants.json"
                async with session.get(url_participantes, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as p_resp:
                    if p_resp.status != 200:
                        continue
                    participantes_data = await p_resp.json()
                    # Comprobar si ctx.author está inscrito
                    # Obtener lista de participantes
                    inscritos = [p["participant"].get("name") for p in participantes_data]

                    # Usar el ID del usuario como string
                    usuario_id_str = str(ctx.author.id)

                    if usuario_id_str not in inscritos:
                        continue  # No está inscrito → saltar
            torneos.append((tid, nombre))

    if not torneos:
        if solo_inscritos:
            await ctx.author.send("📭 No estás inscrito en ningún torneo disponible.")
        else:
            await ctx.author.send("📭 No hay torneos disponibles en Challonge.")
        return None

    # 5) Mostrar torneos por DM en trozos de 20
    numeros_emoji = [
        "1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟",
        "1️⃣1️⃣","1️⃣2️⃣","1️⃣3️⃣","1️⃣4️⃣","1️⃣5️⃣","1️⃣6️⃣","1️⃣7️⃣","1️⃣8️⃣","1️⃣9️⃣","2️⃣0️⃣"
    ]
    chunk_size = 20
    total = len(torneos)
    header_base = f"📋 Se han encontrado **{total}** torneos disponibles.\n"
    for start in range(0, total, chunk_size):
        chunk = torneos[start:start + chunk_size]
        texto = header_base if start == 0 else ""
        for idx, (tid, nombre) in enumerate(chunk, start=start):
            emoji = numeros_emoji[idx] if idx < len(numeros_emoji) else f"{idx+1}."
            texto += f"{emoji} `{tid}` → {nombre}\n"
        if total > len(numeros_emoji):
            texto += f"\n(Selecciona el número del torneo: 1 - {total})"
        try:
            await ctx.author.send(texto)
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return None

    # 6) Pedir selección
    try:
        await ctx.author.send(f"✏️ Responde con el **número** del torneo que quieras usar (1 - {total}). Tienes {timeout} segundos.")
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
        return None

    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=timeout)
        seleccion = int(respuesta.content.strip())
        if seleccion < 1 or seleccion > total:
            await ctx.author.send("❌ Opción no válida. Cancelo la operación.")
            return None
        elegido = torneos[seleccion - 1][0]
        return elegido
    except ValueError:
        await ctx.author.send("❌ Debes responder con un número válido. Cancelo la operación.")
        return None
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo.")
        return None