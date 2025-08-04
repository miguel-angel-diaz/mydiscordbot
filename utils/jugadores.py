import aiohttp
import discord
import asyncio
from datetime import datetime, timedelta
import re
import config
from utils.torneos import generar_codigo_unico, partidos_pendientes_handle
from utils.admin import moderador_permisos_handle
from utils.commons import borrar_mensaje_seguro, validar_canal_correcto, buscar_usuario_en_servidor

import config

MAX_ERRORES = 3
TIEMPO_LIMITE_MINUTOS = 10
intentos_fallidos = {}  # Guardado temporal por usuario

async def agendar_partida_handle(ctx, fecha=None, hora=None, jugador1=None, _vs=None, jugador2=None):
    await borrar_mensaje_seguro(ctx)

    if not await validar_canal_correcto(ctx, "agenda", "!agendar-partida"):
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
        f"\nPuedes consultarlo en el canal `#agenda` con el comando `!partidas-pendientes`."
    )

    for jugador in (jugador1, jugador2):
        try:
            await jugador.send(mensaje_privado)
        except discord.Forbidden:
            await ctx.author.send(f"⚠️ No se pudo enviar mensaje privado a {jugador.mention}.")

    if ctx.author.id in intentos_fallidos:
        del intentos_fallidos[ctx.author.id]

async def extraer_mencion(mensaje, ctx):
    if mensaje.mentions:
        return mensaje.mentions[0]
    else:
        try:
            return await ctx.guild.fetch_member(int(mensaje.content.strip("<@!>")))
        except:
            return None

async def manejar_error_de_agendamiento(ctx):
    ahora = datetime.now()
    usuario_id = ctx.author.id

    intentos = intentos_fallidos.get(usuario_id, [])
    intentos = [t for t in intentos if ahora - t < timedelta(minutes=TIEMPO_LIMITE_MINUTOS)]
    intentos.append(ahora)
    intentos_fallidos[usuario_id] = intentos

    intentos_restantes = MAX_ERRORES - len(intentos)

    mensaje = (
        f"❌ **Comando incorrecto.** Asegúrate de usar este formato:\n"
        "`!agendar-partida dd/mm/yyyy hh:mm @Jugador1 vs @Jugador2`\n"
        f"🔄 Ejemplo: `!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`\n\n"
        f"⚠️ Tienes {intentos_restantes} intento(s) antes de recibir el rol **Strike**."
    )

    await ctx.send(mensaje)

    if len(intentos) >= MAX_ERRORES:
        rol_strike = discord.utils.get(ctx.guild.roles, name="Strike")
        if rol_strike and rol_strike not in ctx.author.roles:
            await ctx.author.add_roles(rol_strike)
            await ctx.send(f"🚫 {ctx.author.mention}, has cometido demasiados errores. Se te ha asignado el rol **Strike**.")

async def eventos_hoy_handle(ctx):
    # Intentar eliminar el mensaje del canal público
    await borrar_mensaje_seguro(ctx)
    
    # Validar canal correcto
    if not await validar_canal_correcto(ctx, "agenda", "!eventos-hoy"):
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
    

def tiene_rol_permitido(member: discord.Member, roles_permitidos: set):
    return any(role.name in roles_permitidos for role in member.roles)


async def inscribirse_handler(ctx, codigo_torneo: str, usuario: discord.Member = None):
    # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!inscribirse"):
        return
    
    if usuario and usuario != ctx.author:
        tiene_permiso = await moderador_permisos_handle(ctx)
        if not tiene_permiso:
            return
    
    if not codigo_torneo:
        try:
            # Mostrar torneos disponibles antes de preguntar por el código
            canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
            if canal_torneos:
                torneos_disponibles = []
                async for mensaje in canal_torneos.history(limit=100):
                    lineas = mensaje.content.splitlines()
                    codigo = None
                    nivel = "Todos"  # Valor por defecto

                    for linea in lineas:
                        if "**Código:**" in linea:
                            codigo = linea.split("**Código:**")[-1].strip().strip("`")
                        if "Nivel:" in linea or "Roles permitidos:" in linea:
                            # Normalizamos el texto quitando símbolos y espacios
                            linea_limpia = linea.replace("*", "").lower()
                            if "nivel:" in linea_limpia:
                                nivel = linea_limpia.split("nivel:")[-1].strip()
                            elif "roles permitidos:" in linea_limpia:
                                nivel = linea_limpia.split("roles permitidos:")[-1].strip()

                    if not codigo:
                        continue

                    roles_permitidos = config.ROLES_SOCIOS if nivel == "socios" else config.ROLES_TODOS

                    if tiene_rol_permitido(ctx.author, roles_permitidos):
                        # Capitalizamos solo al mostrar
                        torneos_disponibles.append(f"• `{codigo}` — Nivel: {nivel.capitalize()}")

                if torneos_disponibles:
                    texto_torneos = "\n".join(torneos_disponibles)
                    await ctx.author.send(f"🎯 **Torneos disponibles:**\n{texto_torneos}")
                else:
                    await ctx.author.send("⚠️ No hay torneos activos disponibles en este momento.")
                    return
            else:
                await ctx.author.send("⚠️ No encontré el canal `#torneos-activos`.")
                return

            # Ahora sí, pedirle el código
            await ctx.author.send(
                "📩 Por favor, respóndeme con el **código del torneo** al que deseas inscribirte. Tienes 60 segundos."
            )
            def dm_check(m): return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)
            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!inscribirse <código>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    apuntado = usuario or ctx.author

    tipo_torneo_socios = "socio" in codigo_torneo.lower()
    roles_permitidos = config.ROLES_SOCIOS if tipo_torneo_socios else config.ROLES_TODOS

   

    if not tiene_rol_permitido(apuntado, roles_permitidos):
        await ctx.author.send(f"❌ El usuario {apuntado.display_name} no tiene los roles necesarios para inscribirse a este torneo.")
        return

    # Buscar canal de torneos activos
    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    if not canal_torneos:
        await ctx.author.send("⚠️ No encontré el canal `#torneos-activos` para extraer información del torneo.")
        return

    deck_url = None
    total_maximo = None
    torneo_activo = False

    async for mensaje in canal_torneos.history(limit=100):
        if codigo_torneo in mensaje.content:
            torneo_activo = True
            for linea in mensaje.content.splitlines():
                if linea.startswith("📥"):
                    deck_url = linea.split("📥 **Decks:**")[-1].strip()
                if linea.startswith("👥"):
                    try:
                        total_maximo = int(linea.split("👥 **Jugadores:**")[-1].strip())
                    except ValueError:
                        total_maximo = None
            break

    if not torneo_activo:
        await ctx.author.send(f"❌ El torneo `{codigo_torneo}` no está activo o no fue encontrado en `#torneos-activos`.")
        return

    # Obtener participantes actuales
    url_get = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url_get, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as get_resp:
            if get_resp.status != 200:
                error_text = await get_resp.text()
                await ctx.author.send(f"⚠️ No pude obtener la lista de inscritos: {error_text}")
                return
            participantes = await get_resp.json()
            total_inscritos = len(participantes)

            if total_maximo and total_inscritos >= total_maximo:
                await ctx.author.send("❌ No quedan plazas disponibles para este torneo.")
                return

            # Inscribir
            payload = {
                "api_key": config.CHALLONGE_API_KEY,
                "participant": {
                    "name": str(apuntado.id)
                }
            }
            url_post = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"

            async with session.post(url_post, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
                if resp.status not in (200, 201):
                    error_text = await resp.text()
                    await ctx.author.send(f"❌ Error al inscribir al usuario: {error_text}")
                    return

    # Enviar DM con URL del deck
    if deck_url:
        try:
            await apuntado.send(
                f"✅ Estás inscrito en el torneo `{codigo_torneo}`.\n"
                f"📥 Sube tu deck aquí: {deck_url}"
            )
        except discord.Forbidden:
            await ctx.author.send(
                f"⚠️ No pude enviar un mensaje directo a {apuntado.display_name}. "
                f"Es posible que tenga los DMs cerrados."
            )
        except discord.HTTPException as e:
            await ctx.author.send(
                f"⚠️ No se pudo enviar el mensaje a {apuntado.display_name} por un error inesperado: {str(e)}"
            )
    else:
        await ctx.author.send("⚠️ No se encontró la URL de decks para este torneo en `#torneos-activos`.")

    # Anunciar inscripción en canal público
    canal_inscripciones = discord.utils.get(ctx.guild.text_channels, name="inscripciones")
    if canal_inscripciones:
        if total_maximo:
            plazas_restantes = total_maximo - total_inscritos - 1  # restamos ya al nuevo inscrito
            mensaje = f"✅ `{apuntado.display_name}` se ha inscrito en {codigo_torneo}. Quedan **{plazas_restantes}** plazas."
        else:
            mensaje = f"✅ `{apuntado.display_name}` se ha inscrito en {codigo_torneo}."
        await canal_inscripciones.send(mensaje)
    else:
        await ctx.author.send("⚠️ No encontré el canal `#inscripciones` para anunciar la inscripción.")

async def desinscribirse_handler(ctx, codigo_torneo: str, usuario: discord.Member = None):
      # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!desinscribirse"):
        return
    
    if codigo_torneo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
                "Por favor, respóndeme con el **código del torneo** del que quieres desinscribirte. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!desinscribirse <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return
    
    apuntado = usuario or ctx.author

    # Si el autor quiere desinscribir a otro, requiere permisos de moderador
    if apuntado != ctx.author:
        tiene_permiso = await moderador_permisos_handle(ctx)
        if not tiene_permiso:
            return

    # Buscar el ID del participante en Challonge
    url_get = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    participant_id = None
    total_inscritos = 0

    async with aiohttp.ClientSession() as session:
        async with session.get(url_get, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                await ctx.author.send(f"❌ Error al buscar participantes: {error_text}")
                return
            data = await resp.json()

        for participante in data:
            p = participante.get("participant", {})
            if p.get("name") == str(apuntado.id):
                participant_id = p.get("id")
            total_inscritos += 1

        if not participant_id:
            await ctx.author.send(f"❌ No se encontró a {apuntado.display_name} inscrito en el torneo `{codigo_torneo}`.")
            return

        # Eliminar participante
        url_delete = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants/{participant_id}.json"
        async with session.delete(url_delete, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as delete_resp:
            if delete_resp.status not in (200, 202):
                error_text = await delete_resp.text()
                await ctx.author.send(f"❌ Error al desinscribir: {error_text}")
                return

    await ctx.author.send(f"✅ {apuntado.display_name} ha sido desinscrito del torneo `{codigo_torneo}`.")
    if apuntado != ctx.author:
        try:
            await apuntado.send(f"❌ Has sido desinscrito del torneo `{codigo_torneo}`.")
        except discord.Forbidden:
            await ctx.author.send(
                f"⚠️ No pude enviar un mensaje directo a {apuntado.display_name}. "
                f"Es posible que tenga los DMs cerrados."
            )
        except discord.HTTPException as e:
            await ctx.author.send(
                f"⚠️ No se pudo enviar el mensaje a {apuntado.display_name} por un error inesperado: {str(e)}"
            )
        

    # Buscar canal de torneos activos
    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    canal_inscripciones = discord.utils.get(ctx.guild.text_channels, name="inscripciones")

    if not canal_torneos or not canal_inscripciones:
        await ctx.author.send("⚠️ No se encontraron los canales `#torneos-activos` o `#inscripciones` para notificar.")
        return

   
    total_maximo = None

    async for mensaje in canal_torneos.history(limit=100):
        if codigo_torneo in mensaje.content:
            for linea in mensaje.content.splitlines():
                if linea.startswith("👥"):
                    try:
                        total_maximo =int(linea.split("👥 **Jugadores:**")[-1].strip())
                    except ValueError:
                        total_maximo = None
            break

    if total_maximo is not None:
        plazas_disponibles = total_maximo - (total_inscritos - 1)  # -1 porque ya está desinscrito
        await canal_inscripciones.send(
            f"📤 {apuntado.mention} se ha desinscrito del torneo `{codigo_torneo}`.\n"
            f"🪑 Plazas disponibles: {plazas_disponibles}/{total_maximo}"
        )

async def ver_inscritos_handler(ctx, codigo_torneo: str):
    # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!ver-inscritos"):
        return
    
    if codigo_torneo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
                "Por favor, respóndeme con el **código del torneo** del torneo que quieres ver los inscritos. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!ver-inscritos <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return
    url = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                await ctx.send(f"❌ Error al obtener los participantes: {error_text}")
                return

            data = await resp.json()

    if not data:
        await ctx.send(f"📭 No hay jugadores inscritos en el torneo `{codigo_torneo}`.")
        return

    inscritos = []
    for i, p in enumerate(data, 1):
        nombre = p.get("participant", {}).get("name", "Desconocido")
        try:
            miembro = await ctx.guild.fetch_member(int(nombre))
        except (ValueError, discord.NotFound):
            nombre_mostrado = nombre  # No era un ID o no se encontró en el servidor

        inscritos.append(f"{i}. {miembro.display_name} (<@{miembro.id}>)")

        inscritos_str = "\n".join(inscritos)
    await ctx.author.send(
        f"📋 **Jugadores inscritos en `{codigo_torneo}`:**\n```{inscritos_str}```"
    )
async def reportar_resultado_handle(ctx, codigo_torneo: str, jugador1: discord.Member, resultado: str, jugador2: discord.Member):
    # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "resultados", "!reportar-resultado"):
        return
    author = ctx.author
    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        if not all([codigo_torneo, jugador1, resultado, jugador2]):
            await author.send("📊 Vamos a reportar un resultado. Responde a las siguientes preguntas:")

            if not codigo_torneo:
                await author.send("1️⃣ ¿Cuál es el **código del torneo**?")
                respuesta_codigo = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
                codigo_torneo = respuesta_codigo.content.strip()

            if not jugador1:
                await author.send("2️⃣ Escribe el nombre o apodo del **jugador 1** (tal como aparece en el servidor):")
                respuesta_j1 = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
                jugador1 = buscar_usuario_en_servidor(ctx.guild, respuesta_j1.content.strip())

            if not resultado:
                await author.send("3️⃣ ¿Cuál fue el **resultado**? (formato ejemplo: `2-1`)")
                respuesta_resultado = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
                resultado = respuesta_resultado.content.strip()

            if not jugador2:
                await author.send("4️⃣ Escribe el nombre o apodo del **jugador 2**:")
                respuesta_j2 = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
                jugador2 = buscar_usuario_en_servidor(ctx.guild, respuesta_j2.content.strip())

            if not jugador1 or not jugador2:
                await author.send("❌ No se pudieron identificar uno o ambos jugadores. Verifica los nombres.")
                return

        # Validación de permisos
        if author != jugador1 and author != jugador2:
            es_mod = await moderador_permisos_handle(ctx)
            if not es_mod:
                await author.send("❌ Solo los jugadores involucrados o un moderador pueden reportar el resultado.")
                return

        # Aquí continuarías con la lógica que ya tenías: buscar match en Challonge, registrar resultado, etc.

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentar con `!reportar-resultado`.")
        return
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes privados. Activa los mensajes en tu configuración de privacidad.")
        return
    except Exception as e:
        await author.send("❌ Ocurrió un error inesperado durante el proceso.")
        raise e
    # Obtener participantes del torneo
    url_participantes = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url_participantes, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await author.send("❌ No se pudieron obtener los participantes del torneo.")
                return
            participantes_data = await resp.json()

        # Obtener IDs de Challonge de los dos jugadores
        id_jugador1 = id_jugador2 = None
        for entry in participantes_data:
            p = entry.get("participant", {})
            if p.get("name") == str(jugador1.id):
                id_jugador1 = p["id"]
            elif p.get("name") == str(jugador2.id):
                id_jugador2 = p["id"]

        if not id_jugador1 or not id_jugador2:
            await author.send("❌ No se encontraron ambos jugadores inscritos en el torneo.")
            return

        # Buscar el match entre esos jugadores
        url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"
        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await author.send("❌ No se pudieron obtener los emparejamientos.")
                return
            matches_data = await resp.json()

        match_id = None
        for match in matches_data:
            m = match["match"]
            players = {m["player1_id"], m["player2_id"]}
            if {id_jugador1, id_jugador2} == players:
                match_id = m["id"]
                player1_is_p1 = m["player1_id"] == id_jugador1
                break

        if not match_id:
            await author.send("❌ No se encontró un match entre estos dos jugadores.")
            return

        # Procesar el resultado tipo "2-1"
        if not resultado or "-" not in resultado:
            await author.send("❌ El resultado debe tener el formato 'X-Y', por ejemplo '2-1'.")
            return

        try:
            puntos1, puntos2 = map(int, resultado.split("-"))
        except ValueError:
            await author.send("❌ El resultado debe tener números válidos, por ejemplo '2-1'.")
            return

        winner_id = id_jugador1 if puntos1 > puntos2 else id_jugador2
        scores_csv = f"{puntos1}-{puntos2}" if player1_is_p1 else f"{puntos2}-{puntos1}"

        # Enviar resultado a Challonge
        url_put = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches/{match_id}.json"
        if puntos1 == puntos2:
            payload = {
                "match": {
                    "scores_csv": scores_csv,
                    "winner_id" : "tie"
                    # No enviar winner_id en caso de empate
                }
            }
        else:
            winner_id = id_jugador1 if puntos1 > puntos2 else id_jugador2
            payload = {
                "match": {
                    "scores_csv": scores_csv,
                    "winner_id": winner_id
                }
            }

        async with session.put(url_put, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as put_resp:
            if put_resp.status not in (200, 202):
                error = await put_resp.text()
                await author.send(f"❌ Error al reportar el resultado: {error}")
                return

    # Mandar mensaje privado a ambos jugadores
    jugadores = [jugador1, jugador2]
    for jugador in jugadores:
        try:
            await jugador.send(
                f"📢 Se ha reportado el resultado del torneo `{codigo_torneo}`:\n"
                f"🆚 {jugador1.display_name} vs {jugador2.display_name}\n"
                f"📊 Resultado: {resultado}"
            )
        except discord.Forbidden:
            await author.send(
                f"⚠️ No pude enviar un mensaje directo a {jugador.display_name}. "
                f"Es posible que tenga los DMs cerrados."
            )
        except discord.HTTPException as e:
            await author.send(
                f"⚠️ No se pudo enviar el mensaje a {jugador.display_name} por un error inesperado: {str(e)}"
            )
    # Canal de resultados
    canal_resultados = discord.utils.get(ctx.guild.text_channels, name="resultados")
    if canal_resultados:
        await canal_resultados.send(
            f"🏆 Resultado reportado en `{codigo_torneo}`:\n"
            f"**{jugador1.display_name}** {resultado} **{jugador2.display_name}**"
        )
    await author.send(
        "✅ Resultado reportado correctamente.:\n"
        f"**{jugador1.display_name}** {resultado} **{jugador2.display_name}**"
    )

    await partidos_pendientes_handle(ctx, codigo_torneo, 'user')

async def inscribirse_sorteo_handle(ctx, codigo: str):
    await borrar_mensaje_seguro(ctx)

    user = ctx.author
    guild = ctx.guild

    if codigo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
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

    sorteo_activo = False
    async for mensaje in canal_activos.history(limit=100):
        if mensaje.content.startswith("🎉") and codigo in mensaje.content:
            sorteo_activo = True
            break

    if not sorteo_activo:
        await user.send(f"❌ El sorteo con código `{codigo}` no está activo o no existe.")
        return

    # Inscribir al usuario en el canal #inscritos-sorteos
    canal_inscritos = discord.utils.get(guild.text_channels, name="inscritos-sorteos")
    if not canal_inscritos:
        await user.send("⚠️ No se encontró el canal `#inscritos-sorteos`.")
        return

    # Verificar que el usuario no esté ya inscrito
    ya_inscrito = False
    contador = 1
    async for mensaje in canal_inscritos.history(limit=200, oldest_first=True):
        if f"{codigo} <@{user.id}>" in mensaje.content:
            ya_inscrito = True
        if mensaje.content.startswith(f"{contador}"):
            contador += 1

    if ya_inscrito:
        await user.send(f"⚠️ Ya estás inscrito en el sorteo `{codigo}`.")
        return

    # Publicar inscripción
    linea = f"{contador} | {codigo} | {user.id} <@{user.id}>"
    await canal_inscritos.send(linea)

    try:
        await user.send(f"✅ Te has inscrito correctamente al sorteo `{codigo}`.")
    except discord.Forbidden:
        await ctx.send(f"⚠️ No pude enviarte un mensaje privado, revisa tus DMs.")

async def mis_comandos_handle(ctx):
    """Muestra los comandos disponibles según tus permisos y roles - !mis-comandos"""
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!mis-comandos"):
        return

    roles_usuario = [rol.name for rol in ctx.author.roles]
    comandos_disponibles = []

    for comando in config.COMANDOS_INFO:
        roles_permitidos = comando["roles_permitidos"]
        if any(rol in roles_usuario for rol in roles_permitidos):
            comandos_disponibles.append(f"!{comando['comando']} - {comando['descripcion']}")

    if not comandos_disponibles:
        await ctx.author.send("❌ No tienes acceso a ningún comando.")
        return

    embed = discord.Embed(
        title="📋 Tus comandos disponibles",
        description="\n".join(comandos_disponibles),
        color=discord.Color.green()
    )

    try:
        await ctx.author.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte un mensaje privado. Revisa tus ajustes de privacidad.")