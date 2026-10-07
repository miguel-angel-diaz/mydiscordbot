######## jugadores.py #######
import discord
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import io
import re
import config
import time

from utils.torneos_estado import generar_codigo_unico, obtener_torneo_estado


from utils.admin import moderador_permisos_handle

from utils.commons import (
    borrar_mensaje_seguro,
    validar_canal_correcto,
    buscar_usuario_en_servidor,
    obtener_torneo_usuario,
    obtener_sugerencias_arquetipos,
    cartas_mas_jugadas,
    best_decks_handle,
    obtener_deck_en_canal,
    validar_torneo_para_edicion,
    comprobar_edicion_deck,
    CAMPO_EDICIONES,
    leer_inscritos_sorteo,
    ids_con_deck,
    enviar_en_trozos,
    sorteo_esta_activo,
    anadir_campos_lista,
    EDICION_NO_EXISTE,
    EDICION_NO_INSCRITO,
    EDICION_FINALIZADO,
    EDICION_EMPEZADO,
    EDICION_ABIERTO,
    limpiar_deck_raw,
    contar_cartas
)

import config

MAX_ERRORES = 3
TIEMPO_LIMITE_MINUTOS = 10
intentos_fallidos = {}  # Guardado temporal por usuario

async def agendar_partida_handle(ctx, fecha=None, hora=None, jugador1=None, _vs=None, jugador2=None):
    await borrar_mensaje_seguro(ctx)

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!agendar-partida"):
        return

    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    # Si falta algún argumento, empieza la conversación por DM
    if not all([fecha, hora, jugador1, jugador2]) or _vs is None or _vs.lower() != "vs":
        try:
            await ctx.author.send("📅 Vamos a agendar una partida. Responde a las siguientes preguntas:")

            await ctx.author.send("1️⃣ ¿Qué **fecha** es la partida? (formato: `dd/mm/yyyy`)")
            respuesta_fecha = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            fecha = respuesta_fecha.content.strip()
            try:
                datetime.strptime(fecha, "%d/%m/%Y")
            except ValueError:
                await ctx.author.send("❌ Fecha inválida. Usa el formato `dd/mm/yyyy`.")
                return

            await ctx.author.send("2️⃣ ¿A qué **hora** es la partida? (formato: `hh:mm`)")
            respuesta_hora = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            hora = respuesta_hora.content.strip()
            try:
                datetime.strptime(hora, "%H:%M")
            except ValueError:
                await ctx.author.send("❌ Hora inválida. Usa el formato `hh:mm`.")
                return

            await ctx.author.send("3️⃣ Escribe el nombre o apodo del **jugador 1** tal como aparece en el servidor:")
            respuesta_j1 = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            jugador1 = buscar_usuario_en_servidor(ctx.guild, respuesta_j1.content.strip())

            await ctx.author.send("4️⃣ Escribe el nombre o apodo del **jugador 2** tal como aparece en el servidor:")
            respuesta_j2 = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            jugador2 = buscar_usuario_en_servidor(ctx.guild, respuesta_j2.content.strip())

            if not jugador1 or not jugador2:
                await ctx.author.send("❌ Uno o ambos jugadores no fueron reconocidos. Asegúrate de mencionar correctamente.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Vuelve a intentar con `!agendar-partida`.")
            return
        except Exception as e:
            await ctx.author.send("❌ Ocurrió un error inesperado al intentar agendar la partida.")
            raise e

    # Envío a canal de agenda
    canal_destino = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal_destino:
        await ctx.author.send("❌ No se encontró el canal `#partidos-agendados`.")
        return

    mensaje_agendado = (
        f"📅 [EVENTO] {fecha} {hora} | {jugador1.mention} vs {jugador2.mention} | "
        f"Agendado por {ctx.author.mention}"
    )

    await canal_destino.send(mensaje_agendado)
    await ctx.author.send("✅ Has agendado la partida correctamente.")

    mensaje_privado = (
        f"✅ Se ha agendado una partida para el `{fecha}` a las `{hora}` entre {jugador1.mention} y {jugador2.mention}."
    )

    for jugador in (jugador1, jugador2):
        try:
            await jugador.send(mensaje_privado)
        except discord.Forbidden:
            await ctx.author.send(f"⚠️ No se pudo enviar mensaje privado a {jugador.mention}.")

    if ctx.author.id in intentos_fallidos:
        del intentos_fallidos[ctx.author.id]
    # Publicar partidas agendadas esta semana
    await actualizar_proximas_partidas(ctx)

async def extraer_mencion(mensaje, ctx):
    if mensaje.mentions:
        return mensaje.mentions[0]
    else:
        try:
            return await ctx.guild.fetch_member(int(mensaje.content.strip("<@!>")))
        except:
            return None

async def modificar_partida_agendada_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    canal_destino = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal_destino:
        await ctx.send("❌ No se encontró el canal `#partidos-agendados`.")
        return

    mensajes = [m async for m in canal_destino.history(limit=100) if ctx.author.mention in m.content]
    if not mensajes:
        await ctx.send("❌ No tienes partidas agendadas recientemente.")
        return

    def dm_check(m): 
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    # Selección de partida si hay varias
    if len(mensajes) > 1:
        opciones = "\n".join([f"{i+1}. {m.content}" for i, m in enumerate(mensajes[:5])])
        await ctx.author.send(
            f"📋 He encontrado varias partidas agendadas por ti:\n{opciones}\n\n"
            "Responde con el número de la que quieras modificar o eliminar:"
        )
        try:
            resp = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
            idx = int(resp.content.strip()) - 1
            mensaje = mensajes[idx]
        except (asyncio.TimeoutError, ValueError, IndexError):
            await ctx.author.send("❌ Selección inválida o tiempo agotado. No se modificó ninguna partida.")
            return
    else:
        mensaje = mensajes[0]

    # Extraer datos de la partida seleccionada
    partes = mensaje.content.split("|")
    fecha_hora = partes[0].replace("📅 [EVENTO]", "").strip()
    jugador1_vs = partes[1].strip()
    jugador1, jugador2 = jugador1_vs.split("vs")
    fecha, hora = fecha_hora.split(" ")[0], fecha_hora.split(" ")[1]

    # Bucle interactivo
    while True:
        dm_embed = discord.Embed(
            title="⚙️ Modificar/Eliminar partida agendada",
            description="Actualmente tienes agendada esta partida:",
            color=discord.Color.blue()
        )
        dm_embed.add_field(name="Fecha", value=fecha, inline=False)
        dm_embed.add_field(name="Hora", value=hora, inline=False)
        dm_embed.add_field(name="Jugador 1", value=jugador1.strip(), inline=False)
        dm_embed.add_field(name="Jugador 2", value=jugador2.strip(), inline=False)

        await ctx.author.send(embed=dm_embed)
        await ctx.author.send(
            "✏️ ¿Qué deseas hacer?\n"
            "1️⃣ Modificar fecha\n"
            "2️⃣ Modificar hora\n"
            "3️⃣ Modificar jugador 1\n"
            "4️⃣ Modificar jugador 2\n"
            "🗑️ Escribe `eliminar` para borrar esta partida\n"
            "✅ Escribe `ok` para confirmar cambios sin más modificaciones."
        )

        try:
            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. No se modificó la partida agendada.")
            return

        opcion = respuesta.content.strip().lower()

        if opcion in ["ok", "confirmar"]:
            break
        elif opcion == "eliminar":
            await mensaje.delete()
            await ctx.author.send("🗑️ Tu partida agendada ha sido eliminada correctamente.")
            await actualizar_proximas_partidas(ctx)
            return

        try:
            if opcion == "1":
                await ctx.author.send("📅 Nueva fecha (dd/mm/yyyy):")
                resp = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                fecha = resp.content.strip()
            elif opcion == "2":
                await ctx.author.send("⏰ Nueva hora (hh:mm):")
                resp = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                hora = resp.content.strip()
            elif opcion == "3":
                await ctx.author.send("👤 Nuevo Jugador 1 (mención o nombre):")
                resp = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                jugador1 = resp.content.strip()
            elif opcion == "4":
                await ctx.author.send("👤 Nuevo Jugador 2 (mención o nombre):")
                resp = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                jugador2 = resp.content.strip()
            else:
                await ctx.author.send("❌ Opción no válida.")
        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. No se actualizó esa opción.")

    # Si no se eliminó, actualizamos mensaje
    nuevo_mensaje = f"📅 [EVENTO] {fecha} {hora} | {jugador1} vs {jugador2} | Agendado por {ctx.author.mention}"
    await mensaje.edit(content=nuevo_mensaje)
    await ctx.author.send("✅ Tu partida ha sido modificada correctamente.")
    await actualizar_proximas_partidas(ctx)

async def actualizar_proximas_partidas(ctx):
    canal_destino = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    canal_proximas = discord.utils.get(ctx.guild.text_channels, name="🎭-cartelera‐proximas-partidas")
    if not canal_destino or not canal_proximas:
        return

    hoy = datetime.now().date()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    fin_semana = inicio_semana + timedelta(days=6)

    eventos_semana = []
    async for mensaje in canal_destino.history(limit=200):
        if "[EVENTO]" in mensaje.content:
            partes = mensaje.content.split("|")
            fecha_hora = partes[0].replace("📅 [EVENTO]", "").strip()
            try:
                fecha_msg, hora_msg = fecha_hora.split(" ")[0], fecha_hora.split(" ")[1]
                fecha_obj = datetime.strptime(fecha_msg, "%d/%m/%Y").date()
                if inicio_semana <= fecha_obj <= fin_semana:
                    jugadores = partes[1].strip()
                    jugador1, jugador2 = jugadores.split("vs")
                    eventos_semana.append((fecha_obj, hora_msg, jugador1.strip(), jugador2.strip()))
            except Exception:
                continue

    if not eventos_semana:
        return  # No hay eventos esta semana

    embed = discord.Embed(
        title="📅 Partidas programadas esta semana",
        color=discord.Color.blue()
    )
    for fecha_ev, hora_ev, j1, j2 in sorted(eventos_semana):
        embed.add_field(name=f"{fecha_ev.strftime('%d/%m/%Y')} {hora_ev}", value=f"{j1} vs {j2}", inline=False)

    # Revisar si ya existe un mensaje de esta semana
    mensaje_existente = None
    async for msg in canal_proximas.history(limit=50):
        if msg.author == ctx.guild.me and "📅 Partidas programadas esta semana" in (msg.embeds[0].title if msg.embeds else ""):
            mensaje_existente = msg
            break

    if mensaje_existente:
        await mensaje_existente.edit(embed=embed)
    else:
        await canal_proximas.send(embed=embed)


async def eventos_hoy_handle(ctx):
    # Intentar eliminar el mensaje del canal público
    await borrar_mensaje_seguro(ctx)
    
    # Validar canal correcto
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!eventos-hoy"):
        return

    canal = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal:
        await ctx.author.send("❌ No se encontró el canal `#partidos-agendados`.")
        return

    hoy = datetime.now().date()
    eventos_hoy = []

    patron = re.compile(
        r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
    )

    async for mensaje in canal.history(limit=100):
        if not mensaje.content.startswith("📅 [EVENTO]"):
            continue

        match = patron.search(mensaje.content)
        if not match:
            continue

        fecha_str, hora_str, jugador1, jugador2 = match.groups()
        try:
            fecha_completa = datetime.strptime(f"{fecha_str} {hora_str}", "%d/%m/%Y %H:%M")
        except ValueError:
            continue

        if fecha_completa.date() == hoy:
            eventos_hoy.append((fecha_completa.strftime("%H:%M"), jugador1.strip(), jugador2.strip()))

    if not eventos_hoy:
        await ctx.author.send("📭 No hay eventos agendados para hoy.")
        return

    embed = discord.Embed(title="📅 Partidas de hoy", color=discord.Color.green())
    for hora, jugador1, jugador2 in sorted(eventos_hoy):
        embed.add_field(name=hora, value=f"{jugador1} vs {jugador2}", inline=False)

    await ctx.author.send(embed=embed)

async def nueva_peticion_handle(ctx, descripcion):
    # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!nueva-peticion"):
        return

    # Validar descripción
    if not descripcion:
        try:
            await ctx.author.send(
                "📝 No escribiste una descripción para la petición.\n"
                "Por favor, respóndeme con la descripción de tu sugerencia o petición (tienes 90 segundos)."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
            descripcion = respuesta.content.strip()

            if not descripcion:
                await ctx.author.send("❌ La descripción no puede estar vacía. Cancelo la petición.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!nueva-peticion <descripción>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    # Obtener canal destino
    canal_destino = discord.utils.get(ctx.guild.text_channels, name="peticiones-de-usuarios")
    if not canal_destino:
        try:
            await ctx.author.send("❌ No se encontró el canal `#peticiones-de-usuarios`.")
        except discord.Forbidden:
            await ctx.send("❌ No se encontró el canal `#peticiones-de-usuarios` y no puedo contactarte por DM.")
        return

    # Generar código y crear embed
    codigo = generar_codigo_unico()
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(
        title="📬 Nueva petición recibida",
        description=descripcion,
        color=discord.Color.blue()
    )
    embed.add_field(name="👤 Usuario", value=ctx.author.mention, inline=True)
    embed.add_field(name="🆔 Código", value=f"`{codigo}`", inline=True)
    embed.add_field(name="📅 Fecha", value=fecha, inline=True)
    embed.add_field(name="📌 Estado", value="🟢 **Abierta**", inline=False)
    embed.set_footer(text=str(ctx.author.id))  # Aquí se guarda el ID

    # Enviar al canal público
    await canal_destino.send(embed=embed)

    # Confirmación por DM o fallback público
    try:
        await ctx.author.send(f"✅ Tu petición ha sido registrada con el código `{codigo}`.")
    except discord.Forbidden:
        await ctx.send(f"✅ Tu petición ha sido registrada con el código `{codigo}`, pero no pude enviarte mensaje privado.")
    


async def ver_inscritos_handler(ctx, codigo_torneo: str = None):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!ver-inscritos"):
        return

    # 1️⃣ Obtener código de torneo si no se proporcionó
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 No escribiste el código del torneo.\n"
                            "Elige uno de los torneos en los que estás inscrito para ver los jugadores:"
        )
        if not codigo_torneo:
            return

    # 2️⃣ Inscritos desde el estado del bot (los torneos se gestionan con el sistema propio, no con Challonge)
    from utils.torneos_estado import obtener_torneo_estado

    torneo = await obtener_torneo_estado(ctx.bot, codigo_torneo)
    if not torneo:
        await ctx.author.send(f"❌ El torneo `{codigo_torneo}` no existe o ya no está activo.")
        return
    inscritos_ids = torneo.get("inscritos_ids", [])
    if not inscritos_ids:
        await ctx.author.send(f"📭 No hay jugadores inscritos en el torneo `{codigo_torneo}`.")
        return

    jugadores = {}   # {str(discord_id): nombre_mostrado}
    for uid in inscritos_ids:
        miembro = ctx.guild.get_member(int(uid))
        jugadores[str(uid)] = miembro.display_name if miembro else f"Usuario {uid}"

    # 3️⃣ Qué jugadores han subido deck (código exacto del torneo)
    decks_subidos = {f"{codigo_torneo}_{uid}" for uid in await ids_con_deck(ctx.guild, codigo_torneo)}

    # 4️⃣ Verificar si el autor es moderador
    es_moderador = await moderador_permisos_handle(ctx, only_check=True)
    author_id = str(ctx.author.id)

    # 5️⃣ Construir la respuesta según el rol
    if es_moderador:
        # --- ADMIN: listado completo con ticks ---
        inscritos_lista = []
        for jugador_id, nombre_mostrado in jugadores.items():
            deck_key = f"{codigo_torneo}_{jugador_id}"
            tick = "✅" if deck_key in decks_subidos else "❌"
            inscritos_lista.append(f"{nombre_mostrado} {tick}")

        total = len(inscritos_lista)
        await ctx.author.send(f"📋 **Jugadores inscritos en `{codigo_torneo}` ({total}):**")
        await enviar_en_trozos(ctx.author, "\n".join(inscritos_lista))   # con muchos jugadores supera los 2000 caracteres
        await ctx.author.send("✅ = deck subido · ❌ = deck pendiente")
    else:
        # --- JUGADOR NORMAL: solo su estado ---
        if author_id not in jugadores:
            await ctx.author.send(f"❌ No estás inscrito en el torneo `{codigo_torneo}`.")
            return

        deck_key = f"{codigo_torneo}_{author_id}"
        subido = deck_key in decks_subidos
        estado_deck = "✅ Sí, ya lo has subido." if subido else "❌ Todavía no has subido tu deck."

        await ctx.author.send(
            f"📋 **Estado de tu inscripción en `{codigo_torneo}`:**\n"
            f"👤 **Jugador:** {jugadores[author_id]}\n"
            f"🎴 **Deck:** {estado_deck}"
        )
        


_locks_sorteo = {}   # código de sorteo -> asyncio.Lock


async def inscribirse_sorteo_handle(ctx, codigo: str):
    await borrar_mensaje_seguro(ctx)

    user = ctx.author
    guild = ctx.guild

    if codigo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del Sorteo.\n"
                "Por favor, respóndeme con el **código del sorteo** para apuntarte al sorteo. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo = respuesta.content.strip()

            if not codigo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!inscribirse-sorteo <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    # Verificar que el sorteo está activo
    canal_activos = discord.utils.get(guild.text_channels, name="sorteos-activos")
    if not canal_activos:
        await user.send("⚠️ No se encontró el canal `#sorteos-activos`.")
        return

    if not await sorteo_esta_activo(canal_activos, codigo):
        await user.send(f"❌ El sorteo con código `{codigo}` no está activo o no existe.")
        return

    # Inscribir al usuario en el canal #inscritos-sorteos
    canal_inscritos = discord.utils.get(guild.text_channels, name="inscritos-sorteos")
    if not canal_inscritos:
        await user.send("⚠️ No se encontró el canal `#inscritos-sorteos`.")
        return

    # Lock por sorteo: dos inscripciones a la vez no pueden duplicarse ni repetir número
    async with _locks_sorteo.setdefault(codigo, asyncio.Lock()):
        inscritos = await leer_inscritos_sorteo(canal_inscritos, codigo)
        if user.id in inscritos:
            await user.send(f"⚠️ Ya estás inscrito en el sorteo `{codigo}`.")
            return

        # Número de inscripción dentro de ESTE sorteo
        linea = f"{len(inscritos) + 1} | {codigo} | {user.id} <@{user.id}>"
        await canal_inscritos.send(linea)

    try:
        await user.send(f"✅ Te has inscrito correctamente al sorteo `{codigo}`.")
    except discord.Forbidden:
        await ctx.send(f"⚠️ No pude enviarte un mensaje privado, revisa tus DMs.")

async def mis_comandos_handle(ctx):
    """Asistente de búsqueda de comandos con tutorial - !mis-comandos"""
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!mis-comandos"):
        return

    author = ctx.author
    guild = ctx.guild

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    # 1️⃣ Filtrar comandos disponibles según los roles del autor
    roles_usuario = [rol.name for rol in author.roles]
    comandos_disponibles = []
    for comando in config.COMANDOS_INFO:
        if any(rol in roles_usuario for rol in comando["roles_permitidos"]):
            comandos_disponibles.append(comando)

    if not comandos_disponibles:
        try:
            await author.send(
                "❌ No tienes acceso a ningún comando.\n"
                "Si crees que deberías tener acceso, contacta con un moderador del servidor."
            )
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
        return

    try:
        # 2️⃣ Enviar introducción y lista numerada de comandos
        await author.send(
            "👋 ¡Hola! Vamos a buscar el comando que necesitas.\n"
            "Aquí tienes la lista de comandos disponibles según tus roles:"
        )

        # Construir lista en bloques para no exceder límites de Discord
        bloques = []
        bloque = ""
        for i, c in enumerate(comandos_disponibles, 1):
            linea = f"`{i}.` **!{c['comando']}** — {c['descripcion']}\n"
            if len(bloque) + len(linea) > 3800:
                bloques.append(bloque)
                bloque = ""
            bloque += linea
        if bloque:
            bloques.append(bloque)

        for i, bloque in enumerate(bloques):
            titulo = "📋 Comandos disponibles" if i == 0 else f"📋 Comandos disponibles (cont. {i+1})"
            embed_lista = discord.Embed(
                title=titulo,
                description=bloque.strip(),
                color=discord.Color.green()
            )
            await author.send(embed=embed_lista)

        await author.send("✏️ Responde con el **número** o el **nombre** del comando que buscas (o escribe `cancelar`):")

        # 3️⃣ Esperar respuesta del usuario
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
        contenido = respuesta.content.strip().lower()

        if contenido == "cancelar":
            await author.send("❌ Asistente cancelado.")
            return

        # 4️⃣ Buscar el comando por número, nombre o alias
        comando_encontrado = None
        if contenido.isdigit():
            idx = int(contenido) - 1
            if 0 <= idx < len(comandos_disponibles):
                comando_encontrado = comandos_disponibles[idx]
        else:
            contenido_limpio = contenido.lstrip("!")
            for c in comandos_disponibles:
                if contenido_limpio == c["comando"].lower():
                    comando_encontrado = c
                    break
                if any(contenido_limpio == a.lower() for a in c.get("aliases", [])):
                    comando_encontrado = c
                    break

        if not comando_encontrado:
            await author.send(
                "❌ No he encontrado ese comando.\n"
                "Vuelve a intentarlo con `!mis-comandos` en el canal."
            )
            return

        # 5️⃣ Mostrar info del comando encontrado
        aliases = comando_encontrado.get("aliases", [])
        aliases_str = ", ".join([f"`!{a}`" for a in aliases]) if aliases else "Sin aliases"

        embed_info = discord.Embed(
            title=f"📖 !{comando_encontrado['comando']}",
            description=comando_encontrado["descripcion"],
            color=discord.Color.blue()
        )
        embed_info.add_field(name="Aliases", value=aliases_str, inline=False)
        await author.send(embed=embed_info)

        # 6️⃣ Preguntar si quiere tutorial
        await author.send("❓ ¿Quieres ver un **tutorial paso a paso** sobre cómo usarlo? (sí/no)")

        resp_tut = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
        if resp_tut.content.strip().lower() not in ("sí", "si", "yes", "y", "s"):
            await author.send(
                "👌 Perfecto. Si necesitas más ayuda, vuelve a escribir `!mis-comandos` en el canal."
            )
            return

        # 7️⃣ Mostrar tutorial
        tutorial = comando_encontrado.get("tutorial")
        if not tutorial:
            await author.send(
                f"ℹ️ No hay un tutorial detallado para `!{comando_encontrado['comando']}`, "
                f"pero puedes preguntar a un admin si tienes dudas."
            )
            return

        embed_tut = discord.Embed(
            title=f"📚 Tutorial: !{comando_encontrado['comando']}",
            color=discord.Color.purple()
        )
        for i, paso in enumerate(tutorial, 1):
            embed_tut.add_field(name=f"Paso {i}", value=paso, inline=False)

        await author.send(embed=embed_tut)
        await author.send("✅ ¡Listo! Si necesitas más ayuda, vuelve a escribir `!mis-comandos`.")

    except asyncio.TimeoutError:
        try:
            await author.send("⏰ Tiempo agotado. Vuelve a intentarlo con `!mis-comandos`.")
        except Exception:
            pass
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
    except Exception as e:
        print(f"❌ Error en mis_comandos_wizard_handle: {e}")

async def enviar_comandos_a_miembro(member: discord.Member):
    """Envía por DM la lista de comandos disponibles (sin necesitar ctx)."""
    if member.bot:
        return

    roles_usuario = [rol.name for rol in member.roles]
    comandos_disponibles = []

    for comando in config.COMANDOS_INFO:
        roles_permitidos = comando["roles_permitidos"]
        if any(rol in roles_usuario for rol in roles_permitidos):
            comandos_disponibles.append(f"!{comando['comando']} - {comando['descripcion']}")

    if not comandos_disponibles:
        try:
            await member.send(
                "❌ No tienes acceso a ningún comando.\n"
                "Si crees que deberías tener acceso, contacta con un moderador del servidor."
            )
        except discord.Forbidden:
            print(f"[INFO] No pude enviar DM a {member}")
        return

    mensaje_intro = (
        "👋 ¡Hola! Aquí tienes los comandos que puedes usar en el servidor:\n\n"
        "Para usar un comando, simplemente escríbelo en el canal preguntale-a-el-barbas "
        "yo te ayudare a que todo vaya en su sitio. Por ejemplo:\n"
        "`!reportar-resultado`, `!ver-inscritos`, `!subir-deck`, etc.\n\n"
        "📋 Lista de comandos disponibles según tus roles:"
    )

    embed = discord.Embed(
        title="📋 Tus comandos disponibles",
        description="\n".join(comandos_disponibles),
        color=discord.Color.green()
    )

    mensaje_ayuda = (
        "💡 **¿No sabes cómo funciona algún comando?**\n"
        "Escribe `!mis-comandos` en el canal **#preguntale-a-el-barbas** "
        "y te guiaré paso a paso con un tutorial.\n\n"
        "Si sigues con dudas, consulta con un **admin** del servidor."
    )

    try:
        await member.send(mensaje_intro)
        await member.send(embed=embed)
        await member.send(mensaje_ayuda)
    except discord.Forbidden:
        print(f"[INFO] No pude enviar comandos a {member}")


INTENTOS_LISTA = 3   # veces que se vuelve a pedir la decklist o el sideboard si no son válidos


async def deck_dm_flow(ctx, author: discord.Member, codigo_torneo: str, modo: str = "subir"):
    """
    Flujo de DM para subir o editar un deck.
    Retorna: nombre_deck, formato, archetype, decklist, sideboard, mensaje_deck
    """
    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    await author.send(f"📝 Vamos a {'subir tu deck' if modo=='subir' else 'editar tu deck'}.")

    
    torneo = await obtener_torneo_estado(ctx.bot, codigo_torneo)
    formato_torneo = torneo.get("formato", "Premodern") if torneo else "Premodern"

    if modo == "subir":
        try:
            await author.send("1️⃣ Nombre de tu deck:")
            nombre_deck = (await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)).content.strip()

            # 2️⃣ Preguntar formato
            await author.send(
                f"2️⃣ ¿Cuál es el **formato** del torneo? (Premodern / Pauper)\n"
                f"*(Por defecto: {formato_torneo})*"
            )
            while True:
                msg = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
                respuesta_formato = msg.content.strip()
                if not respuesta_formato:
                    formato = formato_torneo
                    break
                formato_lower = respuesta_formato.lower()
                if "premodern" in formato_lower:
                    formato = "Premodern"
                    break
                elif "pauper" in formato_lower:
                    formato = "Pauper"
                    break
                else:
                    await author.send("❌ Formato no reconocido. Escribe `Premodern` o `Pauper`.")
            await author.send(f"✅ Formato seleccionado: **{formato}**.")

            # 3️⃣ Preguntar arquetipo según el formato
            await author.send(
                f"3️⃣ ¿Cuál es el **archetype** de tu deck?\n"
                f"(Puedes escribir el nombre exacto o algo parecido, te ayudaré a encontrarlo)"
            )
            pendiente = None   # nombre escrito tras ver sugerencias: se procesa sin pedirlo otra vez
            while True:
                if pendiente is None:
                    msg = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
                    archetype_raw = msg.content.strip()
                else:
                    archetype_raw, pendiente = pendiente, None
                sugerencias = obtener_sugerencias_arquetipos(archetype_raw, formato=formato)

                if not sugerencias:
                    await author.send(
                        "❌ No se reconoció el arquetipo.\n"
                        "Intenta escribirlo de nuevo."
                    )
                    continue

                if any(s.lower() == archetype_raw.lower() for s in sugerencias):
                    archetype = next(s for s in sugerencias if s.lower() == archetype_raw.lower())
                    await author.send(f"✅ Arquetipo reconocido como **{archetype}**.")
                    break

                opciones_texto = "\n".join([f"{i+1}. {s}" for i, s in enumerate(sugerencias)])
                await author.send(
                    f"🤔 No encontré un arquetipo exacto, pero aquí tienes algunas sugerencias:\n"
                    f"{opciones_texto}\n\n"
                    "👉 Escribe el **número** del arquetipo correcto o vuelve a intentarlo escribiendo otro nombre."
                )

                try:
                    msg_opcion = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
                    contenido = msg_opcion.content.strip()
                    if contenido.isdigit():
                        indice = int(contenido) - 1
                        if 0 <= indice < len(sugerencias):
                            archetype = sugerencias[indice]
                            await author.send(f"✅ Arquetipo seleccionado: **{archetype}**.")
                            break
                        await author.send("❌ Número fuera de rango. Escribe el nombre del arquetipo de nuevo:")
                    else:
                        pendiente = contenido
                        continue
                except asyncio.TimeoutError:
                    await author.send("⏰ Tiempo agotado. Cancelando selección de arquetipo.")
                    return None

            # 4️⃣ Decklist (se vuelve a pedir si no llega a 60 cartas, sin perder lo anterior)
            await author.send("4️⃣ Sube tu **decklist** (solo el Main, mínimo 60 cartas):")
            for intento in range(INTENTOS_LISTA):
                decklist_raw = (await ctx.bot.wait_for("message", check=dm_check, timeout=600.0)).content.strip()
                decklist = limpiar_deck_raw(decklist_raw)
                total = contar_cartas(decklist)
                if total >= 60:
                    break
                if intento == INTENTOS_LISTA - 1:
                    await author.send(f"❌ Tu deck tiene {total} cartas (mínimo 60). Cancelando.")
                    return None
                await author.send(f"❌ Tu deck tiene {total} cartas (mínimo 60). Envíala de nuevo:")

            # 5️⃣ Sideboard (máx. 15 cartas, igual que al editar)
            await author.send("5️⃣ Sube tu **sideboard** (máx 15 cartas, o 'N/A'):")
            for intento in range(INTENTOS_LISTA):
                sideboard_raw = (await ctx.bot.wait_for("message", check=dm_check, timeout=300.0)).content.strip()
                if sideboard_raw.lower() == "n/a":
                    sideboard = "N/A"
                    break
                sideboard = limpiar_deck_raw(sideboard_raw) or "N/A"   # vacío rompería el embed
                total = contar_cartas(sideboard) if sideboard != "N/A" else 0
                if total <= 15:
                    break
                if intento == INTENTOS_LISTA - 1:
                    await author.send(f"❌ Tu sideboard tiene {total} cartas (máximo 15). Cancelando.")
                    return None
                await author.send(f"❌ Tu sideboard tiene {total} cartas (máximo 15). Envíala de nuevo o escribe 'N/A':")
            mensaje_deck = None
        except asyncio.TimeoutError:
            await author.send("⌛ Se acabó el tiempo. El proceso fue cancelado.")
            return None

    else:  # modo "editar"
        codigo_deck = f"{codigo_torneo}_{author.id}"
        deck_actual = await obtener_deck_en_canal(ctx.guild, codigo_deck)
        if not deck_actual:
            await author.send("❌ No se encontró tu deck en `submitted-decks`. Debes subirlo primero.")
            return None

        nombre_deck = deck_actual["nombre_deck"]
        archetype = deck_actual["archetype"]
        decklist = deck_actual["decklist"]
        sideboard = deck_actual["sideboard"]
        mensaje_deck = deck_actual["mensaje"]
        # En edición usamos el formato del torneo
        formato = formato_torneo

        while True:
            dm_embed = discord.Embed(
                title=f"🃏 Deck actual: {nombre_deck}",
                description=f"**Código del deck:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`\n**Formato:** {formato}",
                color=discord.Color.orange()
            )
            dm_embed.add_field(name="Jugador", value=f"{author} (ID: {author.id})", inline=False)
            dm_embed.add_field(name="Archetype", value=archetype, inline=False)
            anadir_campos_lista(dm_embed, "Decklist", decklist)
            anadir_campos_lista(dm_embed, "Sideboard", sideboard)
            dm_embed.set_footer(text="Este es un registro privado de tu deck.")
            await author.send(embed=dm_embed)

            await author.send(
                "✏️ ¿Qué deseas editar?\n"
                "1️⃣ Nombre del deck\n2️⃣ Archetype\n3️⃣ Decklist\n4️⃣ Sideboard\n"
                "Escribe el número correspondiente o `ok` si está todo correcto."
            )

            try:
                respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=300.0)
            except asyncio.TimeoutError:
                await author.send("⏰ No respondiste a tiempo. Se mantiene tu deck sin cambios.")
                break

            contenido = respuesta.content.strip().lower()
            if contenido in ["ok", "sí", "si", "confirmar"]:
                break

            elif contenido == "1":
                await author.send("Escribe el nuevo **nombre del deck**:")
                try:
                    msg = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
                    nombre_deck = msg.content.strip()
                except asyncio.TimeoutError:
                    await author.send("⏰ Tiempo agotado. No se actualizó el nombre.")

            elif contenido == "2":
                await author.send(
                    "2️⃣ ¿Cuál es el **archetype** de tu deck?\n"
                    "(Puedes escribir el nombre exacto o algo parecido, te ayudaré a encontrarlo)"
                )

                while True:
                    try:
                        msg = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
                    except asyncio.TimeoutError:
                        await author.send("⏰ Tiempo agotado. Cancelando selección de arquetipo.")
                        return None

                    archetype_raw = msg.content.strip()
                    sugerencias = obtener_sugerencias_arquetipos(archetype_raw, formato=formato)

                    if not sugerencias:
                        await author.send(
                            f"❌ No he encontrado ningún arquetipo que coincida con **{archetype_raw}**.\n"
                            "🔍 Puedes intentar escribirlo de otra forma."
                        )
                        continue

                    coincidencia_exacta = next((s for s in sugerencias if s.lower() == archetype_raw.lower()), None)
                    if coincidencia_exacta:
                        archetype = coincidencia_exacta
                        await author.send(f"✅ Arquetipo reconocido como **{archetype}**.")
                        break

                    opciones_texto = "\n".join([f"{i+1}. {s}" for i, s in enumerate(sugerencias)])
                    await author.send(
                        f"🤔 No encontré una coincidencia exacta, pero aquí tienes algunas opciones similares:\n"
                        f"{opciones_texto}\n\n"
                        "👉 Escribe el **número** del arquetipo correcto o directamente el **nombre completo**."
                    )

                    try:
                        msg_opcion = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
                    except asyncio.TimeoutError:
                        await author.send("⏰ Tiempo agotado. Cancelando selección de arquetipo.")
                        return None

                    respuesta = msg_opcion.content.strip()

                    if respuesta.isdigit():
                        indice = int(respuesta) - 1
                        if 0 <= indice < len(sugerencias):
                            archetype = sugerencias[indice]
                            await author.send(f"✅ Arquetipo seleccionado: **{archetype}**.")
                            break
                        else:
                            await author.send("❌ Número fuera de rango. Intenta de nuevo.")
                            continue

                    nuevo_intento = respuesta
                    sugerencias_nuevas = obtener_sugerencias_arquetipos(nuevo_intento, formato=formato)

                    if not sugerencias_nuevas:
                        await author.send(
                            f"❌ No se encontró ningún arquetipo que coincida con **{nuevo_intento}**."
                        )
                        continue

                    coincidencia_exacta = next((s for s in sugerencias_nuevas if s.lower() == nuevo_intento.lower()), None)
                    if coincidencia_exacta:
                        archetype = coincidencia_exacta
                        await author.send(f"✅ Arquetipo reconocido como **{archetype}**.")
                        break
                    else:
                        opciones_texto = "\n".join([f"{i+1}. {s}" for i, s in enumerate(sugerencias_nuevas)])
                        await author.send(
                            f"❌ No hay coincidencia exacta, pero encontré estas sugerencias:\n"
                            f"{opciones_texto}\n"
                            "👉 Escribe el **número** del arquetipo correcto o vuelve a intentarlo."
                        )
                        continue

            elif contenido == "3":
                await author.send("Sube la nueva **decklist** (Main, mínimo 60 cartas):")
                try:
                    msg = await ctx.bot.wait_for("message", check=dm_check, timeout=600.0)
                    decklist_raw = msg.content.strip()
                    decklist_limpia = limpiar_deck_raw(decklist_raw)
                    if contar_cartas(decklist_limpia) >= 60:
                        decklist = decklist_limpia
                    else:
                        await author.send("❌ La decklist debe tener al menos 60 cartas. No se actualizó.")
                except asyncio.TimeoutError:
                    await author.send("⏰ Tiempo agotado. No se actualizó la decklist.")

            elif contenido == "4":
                await author.send("Sube la nueva **sideboard** (máx 15 cartas, o 'N/A'):")
                try:
                    msg = await ctx.bot.wait_for("message", check=dm_check, timeout=300.0)
                    sideboard_raw = msg.content.strip()
                    if sideboard_raw.lower() == "n/a":
                        sideboard = "N/A"
                    else:
                        sideboard_limpia = limpiar_deck_raw(sideboard_raw)
                        if contar_cartas(sideboard_limpia) <= 15:
                            sideboard = sideboard_limpia
                        else:
                            await author.send("❌ La sideboard no puede superar 15 cartas. No se actualizó.")
                except asyncio.TimeoutError:
                    await author.send("⏰ Tiempo agotado. No se actualizó la sideboard.")

    return nombre_deck, formato, archetype, decklist, sideboard, mensaje_deck

async def submitted_deck_handle(ctx, codigo_torneo: str = None):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!subir-deck"):
        return
    author = ctx.author
    if ctx.guild is None:
        await author.send("❌ Este comando debe ejecutarse desde el servidor del torneo.")
        return

    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 Por favor, dime el **código del torneo** cuyo deck deseas subir:\n"
                            "Elige uno de los torneos en los que estás inscrito:"
        )
        if not codigo_torneo:
            await author.send("❌ No seleccionaste ningún torneo. Cancelando subida de deck.")
            return

    ok, error = await validar_torneo_para_edicion(codigo_torneo, author)
    if not ok:
        await author.send(error)
        return

    codigo_deck = f"{codigo_torneo}_{author.id}"
    deck_existente = await obtener_deck_en_canal(ctx.guild, codigo_deck)
    if deck_existente:
        await author.send(f"❌ Ya tienes un deck subido para este torneo. Usa `!editar-deck {codigo_torneo}` si deseas modificarlo.")
        return

    # Iniciar flujo manual directamente
    datos = await deck_dm_flow(ctx, author, codigo_torneo, modo="subir")
    if not datos or len(datos) != 6:
        print(f"❌ deck_dm_flow devolvió datos inesperados: {datos}")
        return

    nombre_deck, formato, archetype, decklist, sideboard, _ = datos

    # Publicar embed en submitted-decks
    canal_submitted = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    if canal_submitted:
        embed_final = discord.Embed(
            title=f"🃏 Deck Subido: {nombre_deck}",
            description=f"**Código:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`\n**Formato:** {formato}",
            color=discord.Color.purple()
        )
        embed_final.add_field(name="Jugador", value=f"{author} (ID: {author.id})", inline=False)
        embed_final.add_field(name="Archetype", value=archetype, inline=False)
        anadir_campos_lista(embed_final, "Decklist", decklist)
        anadir_campos_lista(embed_final, "Sideboard", sideboard)
        embed_final.add_field(name=CAMPO_EDICIONES, value="0/1", inline=False)

        embed_final.set_footer(text="Deck subido correctamente.")
        await canal_submitted.send(embed=embed_final)
        await author.send(f"✅ Tu deck ha sido enviado con éxito al torneo `{codigo_torneo}`.")
        await author.send(embed=embed_final)

async def editar_deck_handle(ctx, codigo_torneo: str = None):
    await borrar_mensaje_seguro(ctx)

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!editar-deck"):
        return

    author = ctx.author

    if ctx.guild is None:
        await author.send("❌ Este comando debe ejecutarse desde el servidor del torneo.")
        return

    # ✅ Pedir código del torneo si no se proporcionó
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 Por favor, dime el **código del torneo** cuyo deck deseas editar:\n"
                            "Elige uno de los torneos en los que estás inscrito:"
        )
        if not codigo_torneo:
            await author.send("❌ No seleccionaste ningún torneo. Cancelando edición.")
            return

    # 🔎 Recuperar deck existente
    codigo_deck = f"{codigo_torneo}_{author.id}"
    deck_existente = await obtener_deck_en_canal(ctx.guild, codigo_deck)

    # 🔐 VALIDAR TORNEO E INSCRIPCIÓN (por motivo, no por el texto del mensaje)
    motivo, mensaje_validacion = await comprobar_edicion_deck(codigo_torneo, author)
    ok_validacion = motivo == EDICION_ABIERTO

    # ❌ Torneo inexistente, no inscrito o torneo ya finalizado: no se puede tocar el deck
    if motivo in (EDICION_NO_EXISTE, EDICION_NO_INSCRITO, EDICION_FINALIZADO):
        await author.send(mensaje_validacion)
        return

    # ❌ Sin deck y con el torneo ya empezado: subir uno nuevo no es una "edición" (igual que !subir-deck)
    if not deck_existente and motivo == EDICION_EMPEZADO:
        await author.send(
            f"❌ El torneo `{codigo_torneo}` ya ha comenzado y no subiste tu deck a tiempo, "
            "así que ya no se puede subir. Si crees que es un error, habla con un admin."
        )
        return

    # 🆕 SI NO HAY DECK, ESTÁ INSCRITO Y EL TORNEO NO HA EMPEZADO → PERMITIR SUBIR
    if not deck_existente:
        await author.send(
            f"ℹ️ No se encontró tu deck para el torneo `{codigo_torneo}`.\n\n"
            "✅ Como estás inscrito en el torneo, puedes **subir tu deck ahora**.\n"
            "¿Deseas continuar? (Escribe `si` para subir tu deck o espera 30 segundos para cancelar)"
        )

        def dm_check(m):
            return m.author == author and isinstance(m.channel, discord.DMChannel)

        try:
            msg = await ctx.bot.wait_for("message", check=dm_check, timeout=30.0)
            if msg.content.strip().lower() not in ["si", "sí", "yes", "continuar"]:
                await author.send("❌ Operación cancelada.")
                return
        except asyncio.TimeoutError:
            await author.send("⏰ Tiempo agotado. Operación cancelada.")
            return

        # 🔄 REDIRIGIR A FLUJO DE SUBIDA
        await subir_deck_desde_edicion(ctx, author, codigo_torneo, ok_validacion, mensaje_validacion)
        return

    # ✅ DECK ENCONTRADO: COMPROBAR SI YA EDITÓ
    edited = deck_existente.get("edited", 0)
    mensaje_deck = deck_existente.get("mensaje")

    # 🔒 BLOQUEO GLOBAL: Si ya editó una vez, no puede volver a editar
    if edited >= 1:
        await author.send(
            "❌ **No puedes editar tu deck**\n\n"
            "Ya has usado tu única edición disponible (1/1).\n"
            "El deck quedará bloqueado hasta que finalice el torneo."
        )
        return

    # Si es la primera edición, avisar según el estado del torneo
    if not ok_validacion:
        # Torneo ya comenzado
        await author.send(
            "⚠️ **AVISO IMPORTANTE**\n\n"
            "El torneo **ya ha comenzado**, pero aún tienes **1 edición disponible**.\n"
            "⚡ Esta será tu **última oportunidad** para modificar el deck.\n"
            f"ℹ️ {mensaje_validacion}\n\n"
            "¿Deseas continuar? (Escribe `continuar` o espera 30 segundos para cancelar)"
        )

        def dm_check(m):
            return m.author == author and isinstance(m.channel, discord.DMChannel)

        try:
            msg = await ctx.bot.wait_for("message", check=dm_check, timeout=30.0)
            if msg.content.strip().lower() != "continuar":
                await author.send("❌ Edición cancelada.")
                return
        except asyncio.TimeoutError:
            await author.send("⏰ Tiempo agotado. Edición cancelada.")
            return
    else:
        # Torneo abierto, primera edición
        await author.send(
            f"✅ **Edición permitida**\n\n"
            f"{mensaje_validacion}\n"
            "⚠️ **Recuerda:** solo puedes editar tu deck UNA VEZ, sea cual sea el estado del torneo.\n"
            "¿Deseas continuar? (Escribe `continuar` o espera 30 segundos para cancelar)"
        )

        def dm_check(m):
            return m.author == author and isinstance(m.channel, discord.DMChannel)

        try:
            msg = await ctx.bot.wait_for("message", check=dm_check, timeout=30.0)
            if msg.content.strip().lower() != "continuar":
                await author.send("❌ Edición cancelada.")
                return
        except asyncio.TimeoutError:
            await author.send("⏰ Tiempo agotado. Edición cancelada.")
            return

    # 🔹 Continuar flujo normal de edición
    datos = await deck_dm_flow(ctx, author, codigo_torneo, modo="editar")
    if not datos or len(datos) != 6:
        print(f"❌ deck_dm_flow devolvió datos inesperados: {datos}")
        await author.send("❌ Edición cancelada.")
        return

    nombre_deck, formato, archetype, decklist, sideboard, _ = datos

    # 📊 SIEMPRE INCREMENTAMOS EL CONTADOR
    nuevo_edited = edited + 1

    # 🎨 COLOR DEL EMBED: Naranja porque ya usó su edición
    color_embed = discord.Color.orange()

    embed_final = discord.Embed(
        title=f"🃏 Deck Actualizado: {nombre_deck}",
        description=f"**Código:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`\n**Formato:** {formato}",
        color=color_embed
    )

    embed_final.add_field(
        name="Jugador",
        value=f"{author.mention} (ID: {author.id})",
        inline=False
    )
    embed_final.add_field(
        name="Archetype",
        value=archetype,
        inline=False
    )
    anadir_campos_lista(embed_final, "Decklist", decklist)
    anadir_campos_lista(embed_final, "Sideboard", sideboard)
    embed_final.add_field(
        name=CAMPO_EDICIONES,
        value=f"{nuevo_edited}/1",
        inline=False
    )

    # 🕐 Timestamp de la última edición
    timestamp_ahora_ms = int(time.time() * 1000)
    fecha_legible = datetime.fromtimestamp(timestamp_ahora_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    embed_final.set_footer(text=f"Última edición: {fecha_legible}")

    # 💾 ACTUALIZAR MENSAJE EXISTENTE
    if mensaje_deck:
        try:
            await mensaje_deck.edit(embed=embed_final)
            await author.send("✅ Tu deck ha sido actualizado correctamente.")
        except discord.errors.NotFound:
            await author.send(
                "❌ No se pudo actualizar el mensaje original (fue eliminado).\n"
                "Contacta con un administrador."
            )
            return
        except discord.errors.Forbidden:
            await author.send("❌ No tengo permisos para editar el mensaje del deck.")
            return
        except Exception as e:
            await author.send(f"❌ Error inesperado al actualizar el deck: {str(e)}")
            return
    else:
        # Fallback: si no hay mensaje, crear uno nuevo
        canal_submitted = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
        if canal_submitted:
            try:
                await canal_submitted.send(embed=embed_final)
                await author.send("⚠️ Se creó un nuevo mensaje porque no se encontró el original.")
            except Exception as e:
                await author.send(f"❌ Error al crear el mensaje: {str(e)}")
                return
        else:
            await author.send("❌ No se encontró el canal `submitted-decks`.")
            return

    # 📬 Enviar confirmación al usuario con el embed
    await author.send("📋 **Resumen de tu deck actualizado:**")
    await author.send(embed=embed_final)
    await author.send(
        "⚠️ **Importante:** Has usado tu única edición disponible.\n"
        "Ya no podrás modificar este deck hasta que finalice el torneo."
    )

async def subir_deck_desde_edicion(ctx, author: discord.Member, codigo_torneo: str, torneo_activo: bool, mensaje_estado: str):
    """
    Permite subir un deck cuando el usuario está inscrito pero no tiene deck registrado.
    """
    # Mostrar estado del torneo
    if not torneo_activo:
        await author.send(
            "⚠️ **IMPORTANTE:** El torneo ya ha comenzado.\n"
            "Al subir tu deck ahora, **no tendrás ediciones adicionales disponibles**.\n"
            f"ℹ️ {mensaje_estado}"
        )
        edited_inicial = 1  # Ya usó su "edición" al subirlo tarde
    else:
        await author.send(
            f"✅ Perfecto, vamos a subir tu deck.\n"
            f"ℹ️ {mensaje_estado}"
        )
        edited_inicial = 0

    # 🔹 Flujo de subida
    datos = await deck_dm_flow(ctx, author, codigo_torneo, modo="subir")
    if not datos or len(datos) != 6:
        print(f"❌ deck_dm_flow devolvió datos inesperados: {datos}")
        await author.send("❌ Subida cancelada.")
        return

    nombre_deck, formato, archetype, decklist, sideboard, _ = datos

    codigo_deck = f"{codigo_torneo}_{author.id}"

    # 🎨 CREAR EMBED
    color_embed = discord.Color.green() if edited_inicial == 0 else discord.Color.orange()

    embed_final = discord.Embed(
        title=f"🃏 Deck Subido: {nombre_deck}",
        description=f"**Código:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`\n**Formato:** {formato}",
        color=color_embed
    )

    embed_final.add_field(
        name="Jugador",
        value=f"{author.mention} (ID: {author.id})",
        inline=False
    )
    embed_final.add_field(
        name="Archetype",
        value=archetype,
        inline=False
    )
    anadir_campos_lista(embed_final, "Decklist", decklist)
    anadir_campos_lista(embed_final, "Sideboard", sideboard)
    embed_final.add_field(
        name=CAMPO_EDICIONES,
        value=f"{edited_inicial}/1",
        inline=False
    )

    # 🕐 Timestamp
    timestamp_ahora_ms = int(time.time() * 1000)
    fecha_legible = datetime.fromtimestamp(timestamp_ahora_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    embed_final.set_footer(text=f"Subido el: {fecha_legible}")

    # 💾 PUBLICAR EN CANAL
    canal_submitted = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    if not canal_submitted:
        await author.send("❌ No se encontró el canal `submitted-decks`.")
        return

    try:
        await canal_submitted.send(embed=embed_final)
        await author.send("✅ Tu deck ha sido registrado correctamente.")
        await author.send(embed=embed_final)

        if edited_inicial == 1:
            await author.send(
                "⚠️ **Recuerda:** Como el torneo ya comenzó, este deck no podrá ser editado."
            )
    except Exception as e:
        await author.send(f"❌ Error al publicar el deck: {str(e)}")

async def cartas_mas_jugadas_handle(ctx, codigo_torneo: str = None, channel: str = None):
    await cartas_mas_jugadas(ctx, codigo_torneo, channel)


async def best_decks(ctx, codigo_torneo: str = None, channel: str = None):
    await best_decks_handle(ctx, codigo_torneo, channel)

