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
    Devuelve el código de torneo elegido por el usuario.
    Si no está en ningún torneo o hay error → devuelve None.
    """
    if mensaje_inicial:
        try:
            await ctx.author.send(mensaje_inicial)
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return None

    url_torneos = "https://api.challonge.com/v1/tournaments.json?state=all"

    async with aiohttp.ClientSession() as session:
        async with session.get(url_torneos, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await ctx.author.send("❌ Error al obtener la lista de torneos.")
                return None
            torneos_raw = await resp.json()

        torneos_usuario = []
        for t in torneos_raw:
            torneo = t["tournament"]

            url_participants = f"https://api.challonge.com/v1/tournaments/{torneo['id']}/participants.json"
            async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp_part:
                if resp_part.status != 200:
                    continue
                participantes = await resp_part.json()

            for p in participantes:
                participante = p["participant"]
                if participante["name"] in [str(ctx.author.id), ctx.author.display_name]:
                    torneos_usuario.append((torneo["url"], torneo["name"]))  # <-- Aquí usamos el tournamentId legible
                    break

    if not torneos_usuario:
        await ctx.author.send("📭 No estás inscrito en ningún torneo.")
        return None

    # 🔹 Emojis numerados del 1️⃣ al 20️⃣
    numeros_emoji = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟",
                     "1️⃣1️⃣","1️⃣2️⃣","1️⃣3️⃣","1️⃣4️⃣","1️⃣5️⃣","1️⃣6️⃣","1️⃣7️⃣","1️⃣8️⃣","1️⃣9️⃣","2️⃣0️⃣"]

    # Mostrar lista de torneos
    mensaje_lista = "📋 Estás inscrito en estos torneos:\n"
    for idx, (tid, nombre) in enumerate(torneos_usuario, 0):
        emoji = numeros_emoji[idx] if idx < len(numeros_emoji) else f"{idx+1}."
        mensaje_lista += f"{emoji} `{tid}` → {nombre}\n"
    mensaje_lista += "\nResponde con el **número** del torneo que quieras usar."

    await ctx.author.send(mensaje_lista)

    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=timeout)
        seleccion = int(respuesta.content.strip())
        if seleccion < 1 or seleccion > len(torneos_usuario):
            raise IndexError
        return torneos_usuario[seleccion - 1][0]
    except (ValueError, IndexError):
        await ctx.author.send("❌ Opción no válida. Cancelo la operación.")
        return None
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo.")
        return None