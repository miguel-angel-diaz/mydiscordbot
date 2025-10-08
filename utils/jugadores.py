import aiohttp
import discord
import asyncio
from collections import Counter
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
import re
import config
from utils.torneos import generar_codigo_unico, partidos_pendientes_handle
from utils.admin import moderador_permisos_handle
from utils.commons import borrar_mensaje_seguro, validar_canal_correcto, buscar_usuario_en_servidor, obtener_torneo_usuario

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
            # Recoger torneos disponibles en #torneos-activos
            canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
            if not canal_torneos:
                await ctx.author.send("⚠️ No encontré el canal `#torneos-activos`.")
                return

            torneos_disponibles = []
            async for mensaje in canal_torneos.history(limit=100):
                lineas = mensaje.content.splitlines()
                codigo = None
                nivel = "Todos"

                for linea in lineas:
                    if "**Código:**" in linea:
                        codigo = linea.split("**Código:**")[-1].strip().strip("`")
                    if "Nivel:" in linea or "Roles permitidos:" in linea:
                        linea_limpia = linea.replace("*", "").lower()
                        if "nivel:" in linea_limpia:
                            nivel = linea_limpia.split("nivel:")[-1].strip()
                        elif "roles permitidos:" in linea_limpia:
                            nivel = linea_limpia.split("roles permitidos:")[-1].strip()

                if not codigo:
                    continue

                roles_permitidos = config.ROLES_SOCIOS if nivel == "socios" else config.ROLES_TODOS
                if tiene_rol_permitido(ctx.author, roles_permitidos):
                    torneos_disponibles.append((codigo, nivel.capitalize()))

            if not torneos_disponibles:
                await ctx.author.send("⚠️ No hay torneos activos disponibles.")
                return

            # Mostrar lista con números
            mensaje_lista = "🎯 **Torneos disponibles:**\n"
            for idx, (codigo, nivel) in enumerate(torneos_disponibles, 1):
                mensaje_lista += f"{idx}. `{codigo}` — Nivel: {nivel}\n"
            mensaje_lista += "\nResponde con el **número** del torneo que deseas."

            await ctx.author.send(mensaje_lista)

            # Esperar respuesta con número
            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            seleccion = int(respuesta.content.strip())
            if seleccion < 1 or seleccion > len(torneos_disponibles):
                await ctx.author.send("❌ Opción no válida. Cancelo la operación.")
                return

            codigo_torneo = torneos_disponibles[seleccion - 1][0]

        except ValueError:
            await ctx.author.send("❌ Debes responder con un número válido. Cancelo la operación.")
            return
        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!inscribirse`.")
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

    total_maximo = None
    torneo_activo = False

    async for mensaje in canal_torneos.history(limit=100):
        if codigo_torneo in mensaje.content:
            torneo_activo = True
            for linea in mensaje.content.splitlines():
                if linea.startswith("👥"):
                    try:
                        total_maximo = int(linea.split("👥 **Jugadores:**")[-1].strip())
                    except ValueError:
                        total_maximo = None
            break

    if not torneo_activo:
        await ctx.author.send(f"❌ El torneo `{codigo_torneo}` no está activo o no fue encontrado en `#torneos-activos`.")
        return

    # Obtener participantes actuales desde Challonge
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
                "participant": {"name": str(apuntado.id)}
            }
            url_post = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
            async with session.post(url_post, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
                if resp.status not in (200, 201):
                    error_text = await resp.text()
                    await ctx.author.send(f"❌ Error al inscribir al usuario: {error_text}")
                    return

    # Preguntar al jugador si quiere subir su deck
    try:
        await apuntado.send(
            f"✅ Estás inscrito en el torneo `{codigo_torneo}`.\n"
            f"¿Quieres subir tu deck ahora? Responde con `sí` o `no`."
        )
        def dm_check(m): return m.author == apuntado and isinstance(m.channel, discord.DMChannel)
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)

        if respuesta.content.lower() in ["sí", "si", "s"]:
            await submitted_deck_handle(ctx, codigo_torneo)
        else:
            await apuntado.send("👌 Perfecto, podrás subir tu deck más tarde usando el comando correspondiente.")
    except (asyncio.TimeoutError, discord.Forbidden):
        await ctx.author.send("⚠️ No pude enviar el mensaje para subir deck. Podrás hacerlo más tarde con el comando adecuado.")

   # Anunciar inscripción en canal público
    canal_anuncios_torneos = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
    if canal_anuncios_torneos:
        plazas_ocupadas = total_inscritos + 1  # el que acaba de inscribirse
        if total_maximo:
            plazas_restantes = total_maximo - plazas_ocupadas
            mensaje = (
                f"📥 {apuntado.mention} se ha inscrito en el torneo `{codigo_torneo}`.\n"
                f"🪑 Plazas restantes: {plazas_restantes}/{total_maximo}"
            )
        else:
            mensaje = f"📥 {apuntado.mention} se ha inscrito en el torneo `{codigo_torneo}`."
        await canal_anuncios_torneos.send(mensaje)
    else:
        await ctx.author.send("⚠️ No encontré el canal `#📰-cartelera‐torneos` para anunciar la inscripción.")

async def desinscribirse_handler(ctx, codigo_torneo: str, usuario: discord.Member = None):
      # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!desinscribirse"):
        return
    
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 No escribiste el código del torneo.\n"
                            "Elige uno de los torneos en los que estás inscrito para desinscribirte:"
        )
        if not codigo_torneo:
            return  # Si devuelve None, se cancela la operación
    
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
    canal_anuncios_torneos = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")

    if not canal_torneos or not canal_anuncios_torneos:
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
        await canal_anuncios_torneos.send(
            f"📤 {apuntado.mention} se ha desinscrito del torneo `{codigo_torneo}`.\n"
            f"🪑 Plazas disponibles: {plazas_disponibles}/{total_maximo}"
        )
    # 🔹 Eliminar deck enviado si existe en submitted-decks
    canal_submitted = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    if canal_submitted:
        codigo_deck = f"{codigo_torneo}_{apuntado.id}"
        async for mensaje in canal_submitted.history(limit=200):
            if mensaje.embeds:
                for embed in mensaje.embeds:
                    # Revisar título
                    if embed.title and codigo_deck in embed.title:
                        try:
                            await mensaje.delete()
                            ctx.author.send(f"[INFO] Se eliminó el deck {codigo_deck} de submitted-decks")
                        except discord.Forbidden:
                            await ctx.author.send(f"⚠️ No tengo permisos para eliminar el deck `{codigo_deck}`.")
                        except discord.HTTPException as e:
                            await ctx.author.send(f"⚠️ Error al eliminar el deck `{codigo_deck}`: {str(e)}")
                        break  # ya borramos el mensaje, pasamos al siguiente

                    # Revisar descripción
                    if embed.description and codigo_deck in embed.description:
                        try:
                            await mensaje.delete()
                            ctx.author.send(f"[INFO] Se eliminó el deck {codigo_deck} de submitted-decks")
                        except discord.Forbidden:
                            await ctx.author.send(f"⚠️ No tengo permisos para eliminar el deck `{codigo_deck}`.")
                        except discord.HTTPException as e:
                            await ctx.author.send(f"⚠️ Error al eliminar el deck `{codigo_deck}`: {str(e)}")
                        break

                    # Revisar campos
                    if embed.fields:
                        for field in embed.fields:
                            if codigo_deck in field.value or codigo_deck in field.name:
                                try:
                                    await mensaje.delete()
                                    ctx.author.send(f"[INFO] Se eliminó el deck {codigo_deck} de submitted-decks")
                                except discord.Forbidden:
                                    await ctx.author.send(f"⚠️ No tengo permisos para eliminar el deck `{codigo_deck}`.")
                                except discord.HTTPException as e:
                                    await ctx.author.send(f"⚠️ Error al eliminar el deck `{codigo_deck}`: {str(e)}")
                                break

async def ver_inscritos_handler(ctx, codigo_torneo: str):
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

    # 2️⃣ Obtener participantes del torneo
    url = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                await ctx.author.send(f"❌ Error al obtener los participantes: {error_text}")
                return
            data = await resp.json()

    if not data:
        await ctx.author.send(f"📭 No hay jugadores inscritos en el torneo `{codigo_torneo}`.")
        return

    # 3️⃣ Preparar diccionario de jugadores {id_usuario: nombre_mostrado}
    jugadores = {}
    for p in data:
        participante = p.get("participant", {})
        nombre = participante.get("name", "Desconocido")
        try:
            miembro = await ctx.guild.fetch_member(int(nombre))
            jugadores[miembro.id] = miembro.display_name
        except (ValueError, discord.NotFound):
            jugadores[nombre] = nombre  # No es un ID válido, usar nombre tal cual

    # 4️⃣ Revisar qué jugadores han subido deck
    canal_decks = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    decks_subidos = set()
    if canal_decks:
        async for msg in canal_decks.history(limit=500):
            for embed in msg.embeds:
                if embed.title and "🃏 Deck " in embed.title:
                    contenido = ""
                    if embed.description:
                        contenido += embed.description + "\n"
                    for field in embed.fields:
                        contenido += f"{field.name}: {field.value}\n"

                    # Buscar línea con "Código:"
                    for linea in contenido.splitlines():
                        if "Código:" in linea:
                            match = re.search(r'`(.+?)`', linea)
                            if match:
                                codigo_embed = match.group(1)
                                decks_subidos.add(codigo_embed)

    # 5️⃣ Verificar si el usuario es moderador
    es_moderador = await moderador_permisos_handle(ctx, only_check=True)

    # 6️⃣ Construir lista con ticks
    inscritos_lista = []
    for jugador_id, nombre_mostrado in jugadores.items():
        tick = ""
        if es_moderador:
            # Construir string que debe existir en decks_subidos
            deck_key = f"{codigo_torneo}_{jugador_id}" if isinstance(jugador_id, int) else None
            if deck_key and deck_key in decks_subidos:
                tick = "✅"
            elif deck_key:
                tick = "❌"
        inscritos_lista.append(f"{nombre_mostrado} {tick}")

    # 7️⃣ Enviar al usuario por privado
    mensaje_final = "\n".join(inscritos_lista)
    await ctx.author.send(f"📋 **Jugadores inscritos en `{codigo_torneo}`:**\n```{mensaje_final}```")

async def reportar_resultado_handle(ctx, codigo_torneo: str = None, jugador1: discord.Member = None, resultado: str = None, jugador2: discord.Member = None):
    # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!reportar-resultado"):
        return
    author = ctx.author
    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        if not all([codigo_torneo, jugador1, resultado, jugador2]):
            await author.send("📊 Vamos a reportar un resultado. Responde a las siguientes preguntas:\n")
            if not codigo_torneo:
                codigo_torneo = await obtener_torneo_usuario(
                    ctx,
                    mensaje_inicial="1️⃣ Elige uno de los torneos en los que estás inscrito para reportar el resultado:"
                )
                if not codigo_torneo:
                    return  # Se cancela si no selecciona ningún torneo
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
        

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentar con `!reportar-resultado`.")
        return
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes privados. Activa los mensajes en tu configuración de privacidad.")
        return
    except Exception as e:
        await author.send("❌ Ocurrió un error inesperado durante el proceso.")
        raise e
    
    if author.id != jugador1.id and author.id != jugador2.id:
            es_mod = await moderador_permisos_handle(ctx, only_check=True)
            if not es_mod:
                await author.send("❌ Solo los jugadores involucrados o un moderador pueden reportar el resultado.")
                return
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
                await author.send("❌ No se pudieron obtener las 🍸-citas‐a‐ciegas.")
                return
            matches_data = await resp.json()

        match_id = None
        player1_id = player2_id = None
        for match in matches_data:
            m = match["match"]
            if {id_jugador1, id_jugador2} == {m["player1_id"], m["player2_id"]}:
                match_id = m["id"]
                player1_id = m["player1_id"]
                player2_id = m["player2_id"]
                break

        if not match_id:
            await author.send("❌ No se encontró un match entre estos dos jugadores.")
            return

        if not resultado or "-" not in resultado:
            await author.send("❌ El resultado debe tener el formato 'X-Y', por ejemplo '2-1'.")
            return

        try:
            puntos_j1, puntos_j2 = map(int, resultado.split("-"))
        except ValueError:
            await author.send("❌ El resultado debe contener números válidos, por ejemplo '2-1'.")
            return

        # Normalizar orden según Challonge
        if player1_id == id_jugador1:
            scores_csv = f"{puntos_j1}-{puntos_j2}"
            winner_id = id_jugador1 if puntos_j1 > puntos_j2 else id_jugador2
        else:
            scores_csv = f"{puntos_j2}-{puntos_j1}"
            winner_id = id_jugador2 if puntos_j2 > puntos_j1 else id_jugador1

        # Construir payload para Challonge
        payload = {"match": {"scores_csv": scores_csv}}
        if puntos_j1 == puntos_j2:
            payload["match"]["winner_id"] = "tie"  # Empate explícito
        else:
            payload["match"]["winner_id"] = winner_id

        url_put = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches/{match_id}.json"
        async with session.put(url_put, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as put_resp:
            if put_resp.status not in (200, 202):
                error = await put_resp.text()
                await author.send(f"❌ Error al reportar el resultado: {error}")
                return

   # Mandar mensaje privado a ambos jugadores
    jugadores = [jugador1, jugador2]
    for jugador in jugadores:
        try:
            if puntos_j1 == puntos_j2:
                resultado_texto = "⚖️ Empate"
            else:
                ganador = jugador1 if puntos_j1 > puntos_j2 else jugador2
                resultado_texto = f"🏅 Ganador: {ganador.display_name}"

            await jugador.send(
                f"📢 Se ha reportado el resultado del torneo `{codigo_torneo}`:\n"
                f"🆚 {jugador1.display_name} vs {jugador2.display_name}\n"
                f"📊 Resultado: {resultado}\n"
                f"{resultado_texto}"
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
    canal_resultados = discord.utils.get(ctx.guild.text_channels, name="🍺-quién‐se‐lleva‐la‐ronda")
    if canal_resultados:
        if puntos_j1 == puntos_j2:
            mensaje = (
                f"🏆 Resultado reportado en `{codigo_torneo}`:\n"
                f"**{jugador1.display_name}** {resultado} **{jugador2.display_name}**\n"
                f"⚖️ Empate"
            )
        else:
            ganador = jugador1 if puntos_j1 > puntos_j2 else jugador2
            mensaje = (
                f"🏆 Resultado reportado en `{codigo_torneo}`:\n"
                f"**{jugador1.display_name}** {resultado} **{jugador2.display_name}**\n"
                f"🏅 Ganador: {ganador.mention}"
            )
        await canal_resultados.send(mensaje)
    await author.send(
        "✅ resultado reportado correctamente.:\n"
        f"**{jugador1.display_name}** {resultado} **{jugador2.display_name}**"
    )

    await partidos_pendientes_handle(ctx, codigo_torneo, 'user')

async def modificar_resultado_handle(ctx, codigo_torneo: str = None):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!modificar-resultado"):
        return

    author = ctx.author
    def dm_check(m): return m.author == author and isinstance(m.channel, discord.DMChannel)

   # 1) Preguntar código si falta
    try:
        if not codigo_torneo:
            codigo_torneo = await obtener_torneo_usuario(
                ctx,
                mensaje_inicial="📌 Indica el **código del torneo** donde quieres modificar un resultado:\n"
                                "Elige uno de los torneos en los que estás inscrito:"
            )
            if not codigo_torneo:
                await author.send("❌ No seleccionaste ningún torneo. Se cancela la modificación.")
                return
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. No se modificó ningún resultado.")
        return
    except discord.Forbidden:
        await ctx.send("❌ No puedo escribirte por DM. Activa mensajes privados para continuar.")
        return

    # 2) Cargar participantes y matches (API v1)
    url_participantes = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    url_matches       = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"

    async with aiohttp.ClientSession() as session:
        # participantes
        async with session.get(url_participantes, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await author.send("❌ No se pudieron obtener los participantes del torneo. Verifica el código.")
                return
            participantes_data = await resp.json()

        # mapa participante_id -> (discord_member | None, display_text)
        id_to_member = {}
        for entry in participantes_data:
            p = entry.get("participant", {})
            pid = p.get("id")
            raw_name = p.get("name", "")
            display = raw_name
            member = None
            # si guardas el ID de Discord en 'name'
            try:
                uid = int(raw_name)
                member = ctx.guild.get_member(uid)
                if member:
                    display = member.display_name
                else:
                    # si no está en el guild, dejar el id como texto
                    display = f"<@{uid}>"
            except:
                # name no es un ID de Discord
                display = raw_name or f"Player {pid}"
            id_to_member[pid] = (member, display)

        # matches
        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await author.send("❌ No se pudieron obtener las 🍸-citas‐a‐ciegas del torneo.")
                return
            matches_data = await resp.json()

    # 3) Determinar ronda(s) aún en juego (no completamente finalizada)
    if not matches_data:
        await author.send("❌ No hay 🍸-citas‐a‐ciegas en este torneo.")
        return

    # agrupar por ronda y ver cuáles NO están completas
    rondas = {}
    for m in matches_data:
        mm = m["match"]
        r = mm["round"]
        rondas.setdefault(r, []).append(mm)

    rondas_incompletas = [r for r, lst in rondas.items() if any(x["state"] != "complete" for x in lst)]
    if not rondas_incompletas:
        await author.send("🏁 El torneo no tiene rondas en juego. No es posible modificar resultados.")
        return

    # “ronda actual” en winners: la menor ronda positiva incompleta
    # “ronda actual” en losers: la mayor ronda negativa incompleta (más cercana a 0)
    winners_actual = min((r for r in rondas_incompletas if r > 0), default=None)
    losers_actual  = max((r for r in rondas_incompletas if r < 0), default=None)

    # 4) De esas rondas actuales, solo permitir modificar matches ya 'complete'
    modificables = []

    # comprobar si autor es moderador/admin
    es_mod = await moderador_permisos_handle(ctx, only_check=True)

    for m in matches_data:
        mm = m["match"]
        r = mm["round"]
        if mm["state"] == "complete" and (r == winners_actual or r == losers_actual):
            p1_id = mm["player1_id"]
            p2_id = mm["player2_id"]

            # Mapeamos a los miembros de Discord desde id_to_member
            m1, _ = id_to_member.get(p1_id, (None, f"Player {p1_id}"))
            m2, _ = id_to_member.get(p2_id, (None, f"Player {p2_id}"))

            # Condición: o es jugador del match o es moderador
            if author == m1 or author == m2 or es_mod:
                modificables.append(mm)

    if not modificables:
        await author.send("⚠️ No tienes ningún resultado modificable en esta ronda (o no eres jugador/admin).")
        return
    

    # 5) Listar opciones
    descripcion = ""
    opciones = []
    for i, mm in enumerate(modificables, start=1):
        p1_id, p2_id = mm["player1_id"], mm["player2_id"]
        _, n1 = id_to_member.get(p1_id, (None, f"Player {p1_id}"))
        _, n2 = id_to_member.get(p2_id, (None, f"Player {p2_id}"))
        score = mm.get("scores_csv") or "?"
        descripcion += f"{i}️⃣ {n1} vs {n2} → {score} (Ronda {mm['round']})\n"
        opciones.append(mm)

    embed = discord.Embed(
        title="🔧 Resultados modificables (ronda en juego)",
        description=descripcion[:4000],  # por si se hace largo
        color=discord.Color.orange()
    )
    try:
        await author.send(embed=embed)
        await author.send("👉 Escribe el **número** del emparejamiento a modificar:")
        msg_sel = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
        idx = int(msg_sel.content.strip()) - 1
        if idx < 0 or idx >= len(opciones):
            await author.send("❌ Número inválido. Cancelado.")
            return
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. No se modificó ningún resultado.")
        return
    except ValueError:
        await author.send("❌ Debes escribir un número válido.")
        return

    match = opciones[idx]
    match_id = match["id"]
    p1_id, p2_id = match["player1_id"], match["player2_id"]
    m1, n1 = id_to_member.get(p1_id, (None, f"Player {p1_id}"))
    m2, n2 = id_to_member.get(p2_id, (None, f"Player {p2_id}"))

    # 6) Permisos: autor debe ser uno de los jugadores o moderador
    if author != m1 and author != m2:
        es_mod = await moderador_permisos_handle(ctx)
        if not es_mod:
            await author.send("❌ Solo los jugadores del match o un moderador pueden modificar el resultado.")
            return

    # 7) Pedir nuevo resultado X-Y
    try:
        await author.send(f"📊 Nuevo resultado para **{n1} vs {n2}** (formato `X-Y`):")
        msg_res = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
        partes = msg_res.content.strip().split("-")
        if len(partes) != 2 or not all(p.isdigit() for p in partes):
            await author.send("❌ Formato inválido. Usa `X-Y` con números.")
            return
        puntos_j1, puntos_j2 = map(int, partes)
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. No se modificó el resultado.")
        return

    # 8) Confirmación
    try:
        await author.send(f"🔒 Confirma cambiar a **{puntos_j1}-{puntos_j2}** (sí/no):")
        msg_ok = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        if msg_ok.content.lower() not in ("si", "sí", "yes", "y"):
            await author.send("❌ Modificación cancelada.")
            return
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. No se modificó el resultado.")
        return

    # 9) Payload v1 (orden ya es player1 vs player2 del match)
    scores_csv = f"{puntos_j1}-{puntos_j2}"
    if puntos_j1 == puntos_j2:
        payload = {"match": {"scores_csv": scores_csv, "winner_id": "tie"}}
    else:
        winner_id = p1_id if puntos_j1 > puntos_j2 else p2_id
        payload = {"match": {"scores_csv": scores_csv, "winner_id": winner_id}}

    # 10) PUT v1 para actualizar
    async with aiohttp.ClientSession() as session:
        url_put = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches/{match_id}.json"
        async with session.put(url_put, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as put_resp:
            if put_resp.status not in (200, 202):
                err_txt = await put_resp.text()
                await author.send(f"❌ Error al modificar el resultado en Challonge: {err_txt}")
                return

    # 11) Notificaciones
    await author.send(f"✅ Resultado actualizado: **{n1} vs {n2} → {scores_csv}**")

    canal_resultados = discord.utils.get(ctx.guild.text_channels, name="🍺-quién‐se‐lleva‐la‐ronda")
    if canal_resultados:
        await canal_resultados.send(f"🔄 Resultado modificado en `{codigo_torneo}`: **{n1} vs {n2} → {scores_csv}**")

    # Intentar DM a los jugadores (si pudimos mapearlos)
    for miembro in (m1, m2):
        if not miembro:
            continue
        try:
            await miembro.send(
                f"🔄 Se ha **modificado** el resultado en `{codigo_torneo}`:\n"
                f"🆚 {n1} vs {n2}\n"
                f"📊 Nuevo resultado: {scores_csv}"
            )
        except discord.Forbidden:
            pass

    # 12) Actualizar panel de pendientes / estado
    try:
        await partidos_pendientes_handle(ctx, codigo_torneo, 'user')
    except Exception:
        pass

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
        await ctx.author.send(
            "❌ No tienes acceso a ningún comando.\n"
            "Si crees que deberías tener acceso, contacta con un moderador del servidor."
        )
        return

    # Mensaje introductorio
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

    try:
        await ctx.author.send(mensaje_intro)
        await ctx.author.send(embed=embed)
    except discord.Forbidden:
        await ctx.send(
            "❌ No puedo enviarte un mensaje privado. "
            "Revisa tus ajustes de privacidad o contacta con un moderador."
        )

def limpiar_deck_raw(lista_raw: str) -> str:
    """Devuelve solo las líneas que empiezan con un número, eliminando encabezados y líneas vacías."""
    lineas_validas = []
    for linea in lista_raw.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if linea[0].isdigit():
            lineas_validas.append(linea)
    return "\n".join(lineas_validas)

def contar_cartas(lista_raw: str) -> int:
    """Cuenta el total de cartas en un deck limpio."""
    total = 0
    lista_limpia = limpiar_deck_raw(lista_raw)
    for linea in lista_limpia.splitlines():
        partes = linea.split(" ", 1)
        try:
            total += int(partes[0].replace("x", ""))
        except ValueError:
            continue
    return total

async def obtener_deck_en_canal(guild: discord.Guild, codigo_deck: str):
    """
    Busca en el canal 'submitted-decks' un deck con el código dado.
    Retorna un dict con 'mensaje', 'nombre_deck', 'archetype', 'decklist', 'sideboard', o None si no existe.
    """
    canal_submitted = discord.utils.get(guild.text_channels, name="submitted-decks")
    if not canal_submitted:
        return None

    async for mensaje in canal_submitted.history(limit=500):
        for embed in mensaje.embeds:
            if embed.description and codigo_deck in embed.description:
                campos = {field.name.lower(): field.value for field in embed.fields}
                nombre_deck_extraido = embed.title.replace("🃏 Deck Subido: ", "").replace("🃏 Deck Actualizado: ", "")
                  # Extraer torneo y jugador del código
                id_torneo, jugador_id = codigo_deck.split("_")
                return {
                    "mensaje": mensaje,
                    "nombre_deck": nombre_deck_extraido,
                    "torneo": id_torneo,
                    "jugador_id": int(jugador_id),
                    "archetype": campos.get("archetype", ""),
                    "decklist": campos.get("decklist", ""),
                    "sideboard": campos.get("sideboard", "N/A")
                }
    return None

async def deck_dm_flow(ctx, author: discord.Member, codigo_torneo: str, modo: str = "subir"):
    """
    Flujo de DM para subir o editar un deck.
    Retorna: nombre_deck, archetype, decklist, sideboard, mensaje_deck (solo en edición)
    """
    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    await author.send(f"📝 Vamos a {'subir tu deck' if modo=='subir' else 'editar tu deck'}.")

    if modo == "subir":
        # ---- Pedir todos los datos ----
        try:
            await author.send("1️⃣ Nombre de tu deck:")
            nombre_deck = (await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)).content.strip()

            await author.send("2️⃣ ¿Cuál es el **archetype** de tu deck?")
            archetype = (await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)).content.strip()

            await author.send("3️⃣ Sube tu **decklist** Solo el Main (mínimo 60 cartas):")
            decklist_raw = (await ctx.bot.wait_for("message", check=dm_check, timeout=600.0)).content.strip()
            decklist = limpiar_deck_raw(decklist_raw)
            if contar_cartas(decklist) < 60:
                await author.send("❌ Tu deck tiene menos de 60 cartas. Cancelando.")
                return None

            await author.send("4️⃣ Sube tu **sideboard** (máx 15 cartas, o 'N/A'):")
            sideboard_raw = (await ctx.bot.wait_for("message", check=dm_check, timeout=300.0)).content.strip()
            sideboard = "N/A" if sideboard_raw.lower() == "n/a" else limpiar_deck_raw(sideboard_raw)
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

        # Inicializar datos del deck
        nombre_deck = deck_actual["nombre_deck"]
        archetype = deck_actual["archetype"]
        decklist = deck_actual["decklist"]
        sideboard = deck_actual["sideboard"]
        mensaje_deck = deck_actual["mensaje"]

        # ---- Bucle de edición ----
        while True:
            dm_embed = discord.Embed(
                title=f"🃏 Deck actual: {nombre_deck}",
                description=f"**Código del deck:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`",
                color=discord.Color.orange()
            )
            dm_embed.add_field(name="Jugador", value=f"{author} (ID: {author.id})", inline=False)
            dm_embed.add_field(name="Archetype", value=archetype, inline=False)
            dm_embed.add_field(name="Decklist", value=decklist[:1000], inline=False)
            dm_embed.add_field(name="Sideboard", value=sideboard[:1000], inline=False)
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
                await author.send("Escribe el nuevo **archetype**:")
                try:
                    msg = await ctx.bot.wait_for("message", check=dm_check, timeout=120.0)
                    archetype = msg.content.strip()
                except asyncio.TimeoutError:
                    await author.send("⏰ Tiempo agotado. No se actualizó el archetype.")

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

    return nombre_deck, archetype, decklist, sideboard, mensaje_deck


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
    # ✅ Pedir código del torneo si no se proporcionó
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 Por favor, dime el **código del torneo** cuyo deck deseas subir:\n"
                            "Elige uno de los torneos en los que estás inscrito:"
        )
        if not codigo_torneo:
            await author.send("❌ No seleccionaste ningún torneo. Cancelando subida de deck.")
            return

    # ✅ Comprobar si el torneo permite subir decks
    ok, error = await validar_torneo_para_edicion(codigo_torneo, author)
    if not ok:
       await author.send(error)
       return

    # ✅ Comprobar si ya hay un deck subido
    codigo_deck = f"{codigo_torneo}_{author.id}"
    deck_existente = await obtener_deck_en_canal(ctx.guild, codigo_deck)
    if deck_existente:
        await author.send(f"❌ Ya tienes un deck subido para este torneo. Usa `!editar-deck {codigo_torneo}` si deseas modificarlo.")
        return

    # Preguntar si quiere importar desde tcdecks
    await author.send(
        "📥 Elige cómo quieres subir tu deck:\n"
        "1️⃣ tcdecks.net\n"
        "2️⃣ Manual"
    )
    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        opcion = respuesta.content.strip()
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentarlo.")
        return

    decklist = ""
    sideboard = ""
    nombre_deck = "Deck importado"
    archetype = "Desconocido"

    if opcion == "1":
        # Leer deck desde TCDecks
        nombre_deck, archetype, decklist, sideboard = await leer_deck_tc_decks(ctx)
        if decklist is None:
            await author.send("❌ Error al leer el deck desde tcdecks.net. Intenta subirlo manualmente.")
            return
   
    elif opcion == "2":
        print("➡️ Opción 2 seleccionada: subir deck")  # Marca que entramos en esta opción

        datos = await deck_dm_flow(ctx, author, codigo_torneo, modo="subir")
        print(f"🔹 deck_dm_flow devolvió: {datos}")  # Muestra lo que devuelve

        if not datos:
            print("⚠️ deck_dm_flow devolvió None o lista vacía, saliendo")
            return

        try:
            nombre_deck, archetype, decklist_input, sideboard_input, extra = datos
            print(f"🔹 Desempaquetado:")
            print(f"    nombre_deck = {nombre_deck}")
            print(f"    archetype = {archetype}")
            print(f"    decklist_input = {decklist_input}")
            print(f"    sideboard_input = {sideboard_input}")
            print(f"    extra = {extra}")
        except Exception as e:
            print(f"❌ Error al desempaquetar datos: {e}")
            return

        decklist = decklist_input
        sideboard = sideboard_input

        print(f"✅ Decklist y Sideboard asignados correctamente")
        print(f"Decklist:\n{decklist}")
        print(f"Sideboard:\n{sideboard}")

    # ✅ Publicar embed en submitted-decks
    canal_submitted = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    if canal_submitted:
        embed_final = discord.Embed(
            title=f"🃏 Deck Subido: {nombre_deck}",
            description=f"**Código:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`",
            color=discord.Color.purple()
        )
        embed_final.add_field(name="Jugador", value=f"{author} (ID: {author.id})", inline=False)
        embed_final.add_field(name="Archetype", value=archetype, inline=False)
        embed_final.add_field(name="Decklist", value=decklist[:1000], inline=False)
        embed_final.add_field(name="Sideboard", value=sideboard[:1000], inline=False)
        embed_final.set_footer(text="Deck subido correctamente.")
        await canal_submitted.send(embed=embed_final)
        await author.send(f"✅ Tu deck ha sido enviado con éxito al torneo `{codigo_torneo}`.")
        await author.send(embed=embed_final)


async def editar_deck_handle(ctx, codigo_torneo: str = None):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!mis-comandos"):
        return
    author = ctx.author
    if ctx.guild is None:
        await author.send("❌ Este comando debe ejecutarse desde el servidor del torneo.")
        return
    def dm_check(m):
        return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)
    # ✅ Pedir código del torneo si no se proporcionó
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 Por favor, dime el **código del torneo** cuyo deck deseas editar:\n"
                            "Elige uno de los torneos en los que estás inscrito:"
        )
        if not codigo_torneo:
            await author.send("❌ No seleccionaste ningún torneo. Cancelando subida de deck.")
            return

    # ok, error = await validar_torneo_para_edicion(codigo_torneo, author)
    # if not ok:
    #    await author.send(error)
    #    return

    datos = await deck_dm_flow(ctx, author, codigo_torneo, modo="editar")
    if not datos:
        return
    nombre_deck, archetype, decklist, sideboard, mensaje_deck = datos

    # Publicar embed actualizado (edita el mensaje si existe)
    codigo_deck = f"{codigo_torneo}_{author.id}"
    embed_final = discord.Embed(
        title=f"🃏 Deck Actualizado: {nombre_deck}",
        description=f"**Código:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`",
        color=discord.Color.blue()
    )
    embed_final.add_field(name="Jugador", value=f"{author} (ID: {author.id})", inline=False)
    embed_final.add_field(name="Archetype", value=archetype, inline=False)
    embed_final.add_field(name="Decklist", value=decklist[:1000], inline=False)
    embed_final.add_field(name="Sideboard", value=sideboard[:1000], inline=False)
    embed_final.set_footer(text="Deck editado correctamente.")

    if mensaje_deck:
        await mensaje_deck.edit(embed=embed_final)
    else:
        canal_submitted = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
        if canal_submitted:
            await canal_submitted.send(embed=embed_final)

    await author.send("✅ Tu deck ha sido actualizado correctamente.")
    await author.send(embed=embed_final)

async def validar_torneo_para_edicion(codigo_torneo: str, author: discord.Member):
    async with aiohttp.ClientSession() as session:
        # Verificar inscripción
        url_get = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
        async with session.get(url_get, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return False, f"❌ No se pudo comprobar tu inscripción: {await resp.text()}"
            participantes = await resp.json()
            inscrito = any(p["participant"]["name"] == str(author.id) for p in participantes)
            if not inscrito:
                return False, f"❌ No estás inscrito en el torneo `{codigo_torneo}`."

        # Verificar fecha de inicio
        url_torneo = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}.json"
        async with session.get(url_torneo, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return False, "❌ No se pudo obtener la información del torneo."
            torneo_data = await resp.json()
            fecha_inicio = torneo_data["tournament"].get("start_at")
            if fecha_inicio:
                from datetime import datetime, timezone
                fecha_inicio_dt = datetime.fromisoformat(fecha_inicio.replace("Z", "+00:00"))
                ahora = datetime.now(timezone.utc)
                if ahora >= fecha_inicio_dt:
                    return False, "❌ El torneo ya ha comenzado. No puedes editar tu deck."

    return True, None

async def leer_deck_tc_decks(ctx):
    author = ctx.author
   
    def dm_check(m): 
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    # Pedir URL del deck
    await author.send("🔗 Por favor envíame la URL del deck (tcdecks.net):")
    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=120)
        url = respuesta.content.strip()
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentarlo.")
        return None, None, None, None

    # Extraer iddeck automáticamente
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        iddeck = query_params.get("iddeck", [None])[0]
        if not iddeck:
            await author.send("❌ No se pudo encontrar el parámetro `iddeck` en la URL.")
            return None, None, None, None
    except Exception as e:
        await author.send(f"❌ Error al procesar la URL: {e}")
        return None, None, None, None

    # Pedir nombre del deck
    await author.send("✏️ Por favor ingresa el **nombre de tu deck**:")
    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        nombre_deck = respuesta.content.strip() or "Deck importado"
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Usando nombre por defecto: Deck importado")
        nombre_deck = "Deck importado"

    # Pedir arquetipo
    await author.send("🧩 Por favor ingresa el **arquetipo de tu deck**:")
    try:
        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        archetype = respuesta.content.strip() or "Desconocido"
    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Usando arquetipo por defecto: Desconocido")
        archetype = "Desconocido"

    # Llamada a tcdecks
    print_url = f"https://www.tcdecks.net/print.php?iddeck={iddeck}"
    

    async with aiohttp.ClientSession(headers=config.headers) as session:
        async with session.get(print_url) as resp:
            if resp.status != 200:
                await author.send(f"❌ No se pudo acceder a la URL proporcionada. Código HTTP: {resp.status}")
                return nombre_deck, archetype, None, None
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")

    def limpiar_texto(td):
        texto = td.get_text(separator="\n", strip=True)
        lineas = [line for line in texto.split("\n") if line and not re.search(r'Number|Card Name', line)]
        lineas = [re.sub(r'\xa0', ' ', line) for line in lineas]
        return "\n".join(lineas)

    # Inicializar valores
    decklist = "No se pudo obtener la decklist."
    sideboard = "No hay sideboard."

    # Buscar h3 para Main Deck y Sideboard
    for h3 in soup.find_all("h3"):
        if "Main Deck" in h3.text:
            tabla = h3.find_next("table")
            if tabla:
                td = tabla.find("td")
                if td:
                    decklist = limpiar_texto(td)
        elif "Sideboard" in h3.text:
            tabla = h3.find_next("table")
            if tabla:
                td = tabla.find("td")
                if td:
                    sideboard = limpiar_texto(td)

    return nombre_deck, archetype, decklist, sideboard


async def cartas_mas_jugadas_handle(ctx, codigo_torneo: str = None):
    await borrar_mensaje_seguro(ctx)
    author = ctx.author

    # 🔹 Canal donde están los decks
    canal = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    if not canal:
        return await ctx.send("❌ No encontré el canal `submitted-decks` en este servidor.")

    # 🔹 Obtener torneo(s)
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx, 
            mensaje_inicial="📋 Por favor selecciona un torneo o 'todos' para analizarlos todos:",
            complete=True
        )
        if not codigo_torneo:
            return await ctx.send("❌ No se seleccionó ningún torneo. Operación cancelada.")

    # Si devuelve lista (varios torneos)
    if isinstance(codigo_torneo, list):
        torneos_a_analizar = codigo_torneo
    else:
        torneos_a_analizar = [codigo_torneo]

    cartas_basicas = {"mountain", "swamp", "plains", "island", "forest"}

    # 🔹 Recorrer cada torneo
    for torneo in torneos_a_analizar:
        contador_cartas = Counter()

        async for mensaje in canal.history(limit=None):
            for embed in mensaje.embeds:
                if not embed.description or torneo not in embed.description:
                    continue

                campos = {field.name.lower(): field.value for field in embed.fields}
                decklist = campos.get("decklist", "")
                if not decklist:
                    continue

                for linea in decklist.splitlines():
                    if not linea.strip():
                        continue
                    try:
                        cantidad, carta = linea.strip().split(" ", 1)
                        cantidad = int(cantidad)
                        if carta.lower() in cartas_basicas:
                            continue
                        contador_cartas[carta] += cantidad
                    except ValueError:
                        continue

        if not contador_cartas:
            await ctx.author.send(f"📭 No se encontraron decks válidos para el torneo `{torneo}`.")
            continue

        # 🔹 Top 10 cartas más jugadas
        top = contador_cartas.most_common(20)
        texto = f"📊 **Cartas más jugadas en {torneo} (sin tierras básicas):**\n"
        for idx, (carta, cant) in enumerate(top, start=1):
            texto += f"{idx}. {carta} → {cant} veces\n"

        await ctx.author.send(texto)

        # 🔹 Crear gráfico tipo donut
        nombres = [carta for carta, _ in top]
        cantidades = [cant for _, cant in top]

        fig, ax = plt.subplots(figsize=(6,6))
        wedges, texts, autotexts = ax.pie(
            cantidades,
            labels=nombres,
            autopct="%1.1f%%",
            startangle=90,
            pctdistance=0.85,
            textprops={'fontsize': 10}
        )

        centre_circle = plt.Circle((0,0),0.70,fc='white')
        fig.gca().add_artist(centre_circle)
        ax.axis('equal')
        plt.title(f"Top 10 cartas más jugadas\nTorneo: {torneo}", fontsize=12)

        buf = io.BytesIO()
        plt.savefig(buf, format='PNG')
        buf.seek(0)
        plt.close(fig)

        await ctx.author.send(file=discord.File(fp=buf, filename=f"cartas_mas_jugadas_{torneo}.png"))