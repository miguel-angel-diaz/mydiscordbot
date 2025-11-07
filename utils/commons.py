import asyncio
import aiohttp
import config
import discord
from functools import wraps
from discord.ext import commands

from difflib import get_close_matches


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

async def obtener_torneo_usuario(ctx, mensaje_inicial: str = None, complete=False):
    """
    Devuelve el código (tournament url/slug) o una lista con varios códigos si el usuario elige 'todos'.
    Solo muestra la opción 'todos' si complete=True.
    """
    # 1️⃣ Enviar mensaje inicial si existe
    if mensaje_inicial:
        try:
            await ctx.author.send(mensaje_inicial)
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return None

    # 2️⃣ Determinar si filtramos solo torneos inscritos
    comando_actual = getattr(ctx.command, "name", "").lower()
    solo_inscritos = comando_actual not in ("ver-inscritos", "iniciar-torneo")

    # 3️⃣ Obtener lista de torneos desde Challonge
    url_torneos = "https://api.challonge.com/v1/tournaments.json?state=all"
    async with aiohttp.ClientSession() as session:
        async with session.get(url_torneos, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await ctx.author.send("❌ Error al obtener la lista de torneos.")
                return None
            torneos_raw = await resp.json()

        torneos = []
        for entry in torneos_raw:
            t = entry.get("tournament", {})
            estado = t.get("state")
            tid = t.get("url") or str(t.get("id"))
            nombre = t.get("name") or "(sin nombre)"

            # 🔹 Filtrar según complete
            if complete and estado != "complete":
                continue  # solo torneos completados
            if not complete and estado == "complete":
                continue  # solo torneos no completados

            # 🔹 Si solo queremos torneos donde el usuario está inscrito
            if solo_inscritos:
                url_participantes = f"https://api.challonge.com/v1/tournaments/{tid}/participants.json"
                async with session.get(url_participantes, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as p_resp:
                    if p_resp.status != 200:
                        continue
                    participantes_data = await p_resp.json()
                    inscritos = [p["participant"].get("name") for p in participantes_data]
                    usuario_id_str = str(ctx.author.id)
                    if usuario_id_str not in inscritos:
                        continue

            torneos.append((tid, nombre))

    # 4️⃣ Comprobación básica
    if not torneos:
        await ctx.author.send("📭 No se encontraron torneos disponibles.")
        return None

    # 5️⃣ Mostrar torneos por DM
    numeros_emoji = [
        "1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟",
        "1️⃣1️⃣","1️⃣2️⃣","1️⃣3️⃣","1️⃣4️⃣","1️⃣5️⃣","1️⃣6️⃣","1️⃣7️⃣","1️⃣8️⃣","1️⃣9️⃣","2️⃣0️⃣"
    ]
    chunk_size = 20
    total = len(torneos)
    header_base = f"📋 Se han encontrado **{total}** torneos {'completados' if complete else 'activos'}.\n"

    for start in range(0, total, chunk_size):
        chunk = torneos[start:start + chunk_size]
        texto = header_base if start == 0 else ""
        for idx, (tid, nombre) in enumerate(chunk, start=start):
            emoji = numeros_emoji[idx] if idx < len(numeros_emoji) else f"{idx+1}."
            texto += f"{emoji} `{tid}` → {nombre}\n"
        
        # 🔸 Solo mostrar la opción "todos" si complete=True
        if complete and total > 1:
            texto += "\n🟢 Puedes escribir **todos** para analizar todos los torneos completados."

        try:
            await ctx.author.send(texto)
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return None

    # 6️⃣ Pedir selección
    await ctx.author.send(f"✏️ Responde con el **número** del torneo que quieras usar (1 - {total})" +
                          (" o escribe **todos**." if complete and total > 1 else ".") +
                          " Tienes 90 segundos.")

    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
        contenido = respuesta.content.strip().lower()

        # ✅ Solo aceptar "todos" si complete=True
        if complete and contenido == "todos":
            return [tid for tid, _ in torneos]

        # ✅ Aceptar número de torneo
        seleccion = int(contenido)
        if seleccion < 1 or seleccion > total:
            await ctx.author.send("❌ Opción no válida. Cancelo la operación.")
            return None

        elegido = torneos[seleccion - 1][0]
        return elegido

    except ValueError:
        await ctx.author.send("❌ Respuesta no válida. Cancelo la operación.")
        return None
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo.")
        return None



def obtener_sugerencias_arquetipos(nombre_usuario: str, max_sugerencias: int = 5):
    """
    Devuelve una lista de arquetipos similares al texto ingresado.
    """
    nombres_validos = [a["nombre"] for a in config.ARQUETIPOS_PREMODERN]
    nombre_usuario = nombre_usuario.strip().lower()

    # Buscar coincidencias aproximadas (por similitud)
    sugerencias = get_close_matches(nombre_usuario, nombres_validos, n=max_sugerencias, cutoff=0.4)

    # Buscar coincidencias que contengan la palabra directamente
    sugerencias_extra = [n for n in nombres_validos if nombre_usuario in n.lower()]
    for s in sugerencias_extra:
        if s not in sugerencias:
            sugerencias.append(s)

    return sugerencias[:max_sugerencias]