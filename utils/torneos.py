import discord

import aiohttp
import asyncio

import re
import config
from datetime import datetime
import random
import string

from utils.commons import borrar_mensaje_seguro, validar_canal_correcto
from utils.admin import moderador_permisos_handle

CHALLONGE_API_KEY = "DwMmC03iVa5UKm377ZaScn6omJ3EA6jWRcPvzZOJ"

def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))

def slugify_challonge(value: str) -> str:
    # Convierte a minúsculas y elimina cualquier carácter que no sea letra o número
    value = value.lower()
    return re.sub(r'[^a-z0-9]', '', value)

async def nuevo_torneo(ctx, *, args: str):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!nuevo-torneo"):
        return
    
      # Verificar permisos
    if not await moderador_permisos_handle(ctx):
      return
    if not args or "|" not in args:
        await ctx.author.send("❌ Formato incorrecto. Usa:\n`!nuevo-torneo Nombre | Formato | tipo | Jugadores | Fecha | Nivel | DeckURL`")
        return

    partes = [p.strip() for p in args.split("|")]
    if len(partes) != 7:
        await ctx.author.send("❌ Formato incorrecto. Usa:\n`!nuevo-torneo Nombre | Formato | tipo | Jugadores | Fecha | Nivel | DeckURL`")
        return

    nombre, formato, tipo_challonge, jugadores, fecha, nivel, deck_url = partes

    try:
        jugadores = int(jugadores)
    except ValueError:
        await ctx.author.send("❌ El número de jugadores debe ser un número entero.")
        return

    try:
        fecha_obj = datetime.strptime(fecha, "%d/%m/%Y")
    except ValueError:
        await ctx.author.send("❌ La fecha debe tener el formato `DD/MM/AAAA` (ej. 20/08/2025).")
        return

    # 🔢 Generar código único y construir URL de Challonge
    slug_formato = slugify_challonge(formato)
    slug_nivel = slugify_challonge(nivel)
    codigo = generar_codigo_unico()
    url_challonge = f"{slug_formato}{slug_nivel}{codigo}"

    # 📦 Payload para Challonge
    payload = {
        "api_key": config.CHALLONGE_API_KEY,
        "tournament": {
            "name": nombre,
            "url": url_challonge,
            "tournament_type": tipo_challonge,
            "description": f"Torneo {formato} - {nivel}",
            "signup_cap": jugadores,
            "start_at": fecha_obj.isoformat()
        }
    }

    # 🌐 Llamada a Challonge
    async with aiohttp.ClientSession() as session:
        async with session.post(config.CHALLONGE_API_URL, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as response:
            if response.status in (200, 201):
                data = await response.json()
                tournament = data["tournament"]

                # ✅ DM al creador
                await ctx.author.send(
                    f"✅ Torneo creado con éxito: **{tournament['name']}**\n"
                    f"🌐 URL: https://challonge.com/{url_challonge}\n"
                    f"📥 Decklists: {deck_url}"
                )

                # 📣 Anuncio en canal de torneos
                canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios-torneos")
                if canal_anuncios:
                    await canal_anuncios.send(
                        f"📢 **Nuevo torneo creado!**\n"
                        f"🏷️ **Nombre:** {nombre}\n"
                        f"🎮 **Formato:** {formato}\n"
                        f"👥 **Jugadores máximos:** {jugadores}\n"
                        f"📅 **Inicio:** {fecha}\n"
                        f"🔒 **Nivel:** {nivel}\n"
                        f"📥 **Decks:** {deck_url}\n"
                        f" **Código:** {url_challonge}\n"
                        f"🌐 **Challonge:** https://challonge.com/{url_challonge}"
                    )
                else:
                    await ctx.author.send("⚠️ No se encontró el canal `anuncios-torneos` en este servidor.")
                            # Buscar el canal de torneos activos
                canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
                if canal_torneos is None:
                    await ctx.author.send("⚠️ No encontré el canal `#torneos-activos`. Por favor, créalo.")
                    return

                # Crear el mensaje público
                mensaje_torneo = (
                    f"🎮 **Torneo creado:** {nombre}\n"
                    f"🏷️ **Código:** `{url_challonge}`\n"
                    f"📋 **Formato:** {formato}\n"
                    f"👥 **Jugadores:** {jugadores}\n"
                    f"📅 **Inicio:** {fecha}\n"
                    f"🎯 **Nivel:** {nivel}\n"
                    f"📥 **Decks:** {deck_url}"
                )

                await canal_torneos.send(mensaje_torneo)
            else:
                error = await response.text()
                await ctx.author.send(f"❌ Error al crear el torneo:\n```{error}```")

async def iniciar_torneo_handle(ctx, codigo_torneo: str):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!iniciar-torneo"):
        return
    
    # Verificar permisos de moderador
    if not await moderador_permisos_handle(ctx):
        return

    if codigo_torneo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
                "Por favor, respóndeme con el **código del torneo** que quieres iniciar. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!iniciar-torneo <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    # Iniciar el torneo en Challonge
    url_start = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/start.json"

    async with aiohttp.ClientSession() as session:
        async with session.post(url_start, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status not in (200, 201):
                error_text = await resp.text()
                await ctx.author.send(f"❌ Error al iniciar el torneo: {error_text}")
                return

    await ctx.author.send(f"✅ Torneo `{codigo_torneo}` iniciado correctamente.")

    # Obtener emparejamientos
    url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                await ctx.author.send(f"⚠️ Error al obtener emparejamientos: {error_text}")
                return
            matches_data = await resp.json()

    # Obtener participantes para mapear los IDs
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await ctx.send("⚠️ No se pudo obtener la lista de participantes.")
                return
            participants_data = await resp.json()

    # Mapear IDs de participantes a nombres
    id_to_member = {}
    for p in participants_data:
        participant = p.get("participant", {})
        try:
            user_id = int(participant["name"])
            member = await ctx.guild.fetch_member(user_id)
            id_to_member[participant["id"]] = member.display_name
        except (ValueError, discord.NotFound):
            id_to_member[participant["id"]] = participant["name"]

    # Preparar emparejamientos
    emparejamientos = []
    for match in matches_data:
        m = match.get("match", {})
        p1 = id_to_member.get(m.get("player1_id"), "TBD")
        p2 = id_to_member.get(m.get("player2_id"), "TBD")
        emparejamientos.append(f"🆚 {p1} vs {p2}")

    # Buscar canal de emparejamientos
    canal_emparejamientos = discord.utils.get(ctx.guild.text_channels, name="emparejamientos")
    if not canal_emparejamientos:
        await ctx.author.send("⚠️ No se encontró el canal `#emparejamientos`.")
        return

    # Publicar los emparejamientos
    await canal_emparejamientos.send(
        f"📢 **Emparejamientos de la primera ronda - Torneo `{codigo_torneo}`:**\n" +
        "\n".join(emparejamientos)
    )
    # Obtener clasificación actual del torneo
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"

    async with aiohttp.ClientSession() as session:
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status == 200:
                data = await resp.json()

                clasificacion = []
                for p in data:
                    part = p.get("participant", {})
                    nombre = part.get("name", "Desconocido")
                    seed = part.get("seed")
                    try:
                        miembro = await ctx.guild.fetch_member(int(nombre))
                        nombre_mostrado = f"{miembro.display_name} (<@{miembro.id}>)"
                    except (ValueError, discord.NotFound):
                        nombre_mostrado = nombre

                    clasificacion.append((seed, nombre_mostrado))

                clasificacion.sort()

                mensaje_clasificacion = f"📊 **Clasificación inicial del torneo `{codigo_torneo}`:**\n"
                for i, (seed, nombre) in enumerate(clasificacion, 1):
                    mensaje_clasificacion += f"{i}. {nombre}\n"

                canal_clasificaciones = discord.utils.get(ctx.guild.text_channels, name="clasificaciones-torneos")
                if canal_clasificaciones:
                    await canal_clasificaciones.send(mensaje_clasificacion)
                else:
                    await ctx.author.send("⚠️ No se encontró el canal `#clasificaciones-torneos`.")
            else:
                await ctx.author.send("❌ Error al obtener la clasificación del torneo.")
                
    # Eliminar mensaje del torneo en #torneos-activos
    canal_torneos_activos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    if canal_torneos_activos:
        async for mensaje in canal_torneos_activos.history(limit=100):
            if codigo_torneo in mensaje.content:
                try:
                    await mensaje.delete()
                    break
                except discord.Forbidden:
                    await ctx.author.send("⚠️ No tengo permisos para eliminar mensajes en `#torneos-activos`.")
                except discord.HTTPException as e:
                    await ctx.author.send(f"⚠️ No se pudo eliminar el mensaje de `#torneos-activos`: {e}")

    canal_inscripciones = discord.utils.get(ctx.guild.text_channels, name="inscripciones")
    if canal_inscripciones:
        async for mensaje in canal_inscripciones.history(limit=100):
            if codigo_torneo in mensaje.content:
                try:
                    await mensaje.delete()
                except discord.Forbidden:
                    await ctx.author.send("⚠️ No tengo permisos para eliminar mensajes en `#inscripciones`.")
                    break
                except discord.HTTPException as e:
                    await ctx.author.send(f"⚠️ No se pudo eliminar un mensaje de `#inscripciones`: {e}")
                    break

async def actualizar_clasificacion_handle(ctx, codigo_torneo: str, canal_destino: str = "clasificaciones-torneos", from_chanel: int = 0):
    if from_chanel == 0: 
        await borrar_mensaje_seguro(ctx)
        if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!iniciar-torneo"):
            return
    
        # Verificar permisos de moderador
        if not await moderador_permisos_handle(ctx):
            return
        
        if codigo_torneo is None:
            try:
                await ctx.author.send(
                    "📩 No escribiste el código del torneo.\n"
                    "Por favor, respóndeme con el **código del torneo** al que quieres actualizar la clasificacion. Tienes 60 segundos."
                )

                def dm_check(m):
                    return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

                respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
                codigo_torneo = respuesta.content.strip()

                if not codigo_torneo:
                    await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                    return

            except asyncio.TimeoutError:
                await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!actualizar-clasificacion <código_torneo>`.")
                return
            except discord.Forbidden:
                await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
                return
    
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"

    async with aiohttp.ClientSession() as session:
        # Participantes
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await ctx.send("❌ Error al obtener participantes.")
                return
            participantes_raw = await resp.json()

        # Emparejamientos
        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await ctx.send("❌ Error al obtener emparejamientos.")
                return
            matches_raw = await resp.json()

    participantes_map = {}
    for p in participantes_raw:
        part = p["participant"]
        participantes_map[part["id"]] = {
            "name": part["name"],
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "points": 0.0,
            "diff": 0,
            "opponents": [],
        }

    for m in matches_raw:
        match = m["match"]
        if match["state"] != "complete":
            continue

        p1_id = match["player1_id"]
        p2_id = match["player2_id"]
        scores = match.get("scores_csv", "")

        try:
            s1, s2 = map(int, scores.strip().split("-"))
        except:
            continue

        participantes_map[p1_id]["opponents"].append(p2_id)
        participantes_map[p2_id]["opponents"].append(p1_id)

        participantes_map[p1_id]["diff"] += s1 - s2
        participantes_map[p2_id]["diff"] += s2 - s1

        if s1 > s2:
            participantes_map[p1_id]["wins"] += 1
            participantes_map[p2_id]["losses"] += 1
            participantes_map[p1_id]["points"] += 3
        elif s2 > s1:
            participantes_map[p2_id]["wins"] += 1
            participantes_map[p1_id]["losses"] += 1
            participantes_map[p2_id]["points"] += 3
        else:
            participantes_map[p1_id]["draws"] += 1
            participantes_map[p2_id]["draws"] += 1
            participantes_map[p1_id]["points"] += 1
            participantes_map[p2_id]["points"] += 1

    clasificacion = []
    for pid, datos in participantes_map.items():
        total = datos["wins"] + datos["losses"] + datos["draws"]
        tb = (datos["points"] / total) if total > 0 else 0

        buchholz_sum = 0
        valid_opp = 0
        for opp_id in datos["opponents"]:
            opp = participantes_map.get(opp_id)
            if not opp:
                continue
            opp_total = opp["wins"] + opp["losses"] + opp["draws"]
            if opp_total == 0:
                continue
            buchholz_sum += opp["points"] / opp_total
            valid_opp += 1
        buchholz = buchholz_sum / valid_opp if valid_opp > 0 else 0

        try:
            miembro = await ctx.guild.fetch_member(int(datos["name"]))
            nombre_mostrado = f"(@{miembro.display_name})"
        except (ValueError, discord.NotFound):
            nombre_mostrado = datos["name"]

        clasificacion.append({
            "nombre": nombre_mostrado,
            "g": datos["wins"],
            "p": datos["losses"],
            "e": datos["draws"],
            "puntos": datos["points"],
            "tb": tb,
            "buchholz": buchholz,
            "diff": datos["diff"],
        })

    clasificacion.sort(key=lambda x: (-x["puntos"], -x["diff"], -x["tb"], -x["buchholz"]))

    # Construir tabla en Markdown
    mensaje = f"📊 **Clasificación del torneo `{codigo_torneo}`:**\n"
    mensaje += "```markdown\n"
    mensaje += "Rango | Participante           | G-P-E | Pts | TB%   | Buchholz | Dif\n"
    mensaje += "------|------------------------|-------|-----|-------|----------|-----\n"

    for i, p in enumerate(clasificacion, 1):
        linea = f"{i:<5} | {p['nombre'][:22]:<22} | {p['g']}-{p['p']}-{p['e']} | {p['puntos']:.1f} | {p['tb']:.3f} | {p['buchholz']:.5f}  | {p['diff']:+}"
        mensaje += linea + "\n"

    mensaje += "```"

    canal_clasificaciones = discord.utils.get(ctx.guild.text_channels, name=canal_destino)
    if canal_clasificaciones:
        await canal_clasificaciones.send(mensaje)
    else:
        await ctx.send("⚠️ No se encontró el canal `#clasificaciones-torneos`.")

async def partidos_pendientes_handle(ctx, codigo_torneo: str, type: str):
    await borrar_mensaje_seguro(ctx)

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!partidos-pendientes"):
        return
    
    if codigo_torneo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
                "Por favor, respóndeme con el **código del torneo** del torneo que quieres conocer los partidos pendientes. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la solicitud.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!partidos-pendientes <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"

    async with aiohttp.ClientSession() as session:
        # Obtener participantes
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp_part:
            if resp_part.status != 200:
                await ctx.author.send("❌ Error al obtener participantes del torneo.")
                return
            participantes_raw = await resp_part.json()

        # Obtener emparejamientos
        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp_match:
            if resp_match.status != 200:
                await ctx.author.send("❌ Error al obtener los emparejamientos del torneo.")
                return
            matches_raw = await resp_match.json()

    # Mapeo de ID de participante a miembro/nombre
    id_to_name = {}
    id_to_member = {}
    for p in participantes_raw:
        part = p["participant"]
        try:
            miembro = await ctx.guild.fetch_member(int(part["name"]))
            id_to_name[part["id"]] = f"{miembro.display_name} (<@{miembro.id}>)"
            id_to_member[part["id"]] = miembro
        except (ValueError, discord.NotFound):
            id_to_name[part["id"]] = part["name"]

    # Filtrar partidos no jugados
    pendientes = []
    for m in matches_raw:
        match = m["match"]
        if match["state"] == "open":
            p1_id = match["player1_id"]
            p2_id = match["player2_id"]
            ronda = match["round"]
            p1 = id_to_name.get(p1_id, "Jugador 1")
            p2 = id_to_name.get(p2_id, "Jugador 2")
            pendientes.append((ronda, p1, p2, p1_id, p2_id))

    if not pendientes:
        await finalizar_torneo_handle(ctx, codigo_torneo)
        return

    # Ordenar por ronda
    pendientes.sort(key=lambda x: x[0])

    # Enviar mensaje general al canal de emparejamientos
    mensaje = f"📋 **Partidos pendientes del torneo `{codigo_torneo}`:**\n"
    for ronda, p1, p2, _, _ in pendientes:
        mensaje += f"• Ronda {ronda}: {p1} vs {p2}\n"

    canal_emparejamientos = discord.utils.get(ctx.guild.text_channels, name="emparejamientos")
    if canal_emparejamientos:
        await canal_emparejamientos.send(mensaje)
    else:
        await ctx.author.send("⚠️ No se encontró el canal `#emparejamientos`.")

    if type == 'torneos':
        # Enviar mensajes privados a los jugadores
        for ronda, _, _, p1_id, p2_id in pendientes:
            p1_member = id_to_member.get(p1_id)
            p2_member = id_to_member.get(p2_id)

            texto_dm = (
                f"👥 **Tienes una partida pendiente de la ronda {ronda} del torneo `{codigo_torneo}`**\n"
                f"🆚 Tu oponente: {id_to_name.get(p2_id)}\n"
                f"📅 Tienes hasta el **lunes** para jugarla.\n\n"
                "⚠️ Si no se juega a tiempo, el resultado será registrado como **empate**.\n"
                "🚫 Forzar empates o no intentar jugar puede ser motivo de expulsión."
            )

            if p1_member:
                try:
                    await p1_member.send(texto_dm.replace(id_to_name.get(p2_id), id_to_name.get(p2_id)))
                except discord.Forbidden:
                    pass  # No enviar error si tiene los DMs cerrados

            if p2_member:
                try:
                    await p2_member.send(texto_dm.replace(id_to_name.get(p2_id), id_to_name.get(p1_id)))
                except discord.Forbidden:
                    pass

        
        await actualizar_clasificacion_handle(ctx, codigo_torneo, canal_destino = "clasificaciones-torneos",  from_chanel = 1)

async def forzar_ronda_handle(ctx, codigo_torneo: str):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!forzar-ronda"):
        return
    if not await moderador_permisos_handle(ctx):
      return
    if codigo_torneo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
                "Por favor, respóndeme con el **código del torneo** del que quieres forzar la nueva ronda. Tienes 60 segundos."
            )

            def dm_check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

            respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!partidos-pendientes <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"

    async with aiohttp.ClientSession() as session:
        # Obtener participantes
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp_part:
            if resp_part.status != 200:
                await ctx.send("❌ Error al obtener los participantes del torneo.")
                return
            participantes_data = await resp_part.json()

        # Obtener matches
        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp_matches:
            if resp_matches.status != 200:
                await ctx.send("❌ Error al obtener los emparejamientos del torneo.")
                return
            matches_data = await resp_matches.json()

        # Identificar ronda actual (la más baja de los matches incompletos)
        rondas_pendientes = [m["match"]["round"] for m in matches_data if m["match"]["state"] != "complete"]
        if not rondas_pendientes:
            await ctx.send("✅ No hay rondas pendientes por forzar.")
            return
        ronda_actual = min(rondas_pendientes)

        # Procesar empates
        empates_aplicados = 0
        for m in matches_data:
            match = m["match"]
            if match["state"] == "complete" or match["round"] != ronda_actual:
                continue

            match_id = match["id"]
            p1 = match.get("player1_id")
            p2 = match.get("player2_id")
            if not p1 or not p2:
                continue  # Match sin jugadores

            url_put = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches/{match_id}.json"
            payload = {
                "match": {
                    "scores_csv": "0-0",  # Empate,
                    "winner_id" : "tie"
                }
            }

            async with session.put(url_put, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp_put:
                if resp_put.status == 200:
                    empates_aplicados += 1
                else:
                    await ctx.send(f"⚠️ Error al forzar empate en match {match_id} (status {resp_put.status})")

    await ctx.send(f"🤝 Se han forzado {empates_aplicados} empates en la ronda {ronda_actual}.")
    await partidos_pendientes_handle(ctx, codigo_torneo, 'torneos')

async def finalizar_torneo_handle(ctx, codigo_torneo: str):
    canales_a_limpiar = [
        "clasificaciones-torneos",
        "resultados",
        "emparejamientos",
        "torneos-activos",
        "agenda"
    ]

    for nombre_canal in canales_a_limpiar:
        canal = discord.utils.get(ctx.guild.text_channels, name=nombre_canal)
        if not canal:
            await ctx.send(f"⚠️ No se encontró el canal `{nombre_canal}`.")
            continue

        try:
            if nombre_canal == "clasificaciones-torneos":
                # Eliminar todo en clasificaciones
                await canal.purge()
            else:
                # Eliminar solo los mensajes que contienen el código del torneo
                def filtro(msg):
                    return codigo_torneo in msg.content
                await canal.purge(check=filtro)
        except Exception as e:
            await ctx.send(f"⚠️ No se pudo limpiar el canal `{nombre_canal}`: {e}")
     # Enviar anuncio al canal #anuncios
    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios-torneos")
    if canal_anuncios:
        try:
            await canal_anuncios.send(
                f"📢 @everyone\n"
                f"🏁 El torneo `{codigo_torneo}` ha finalizado. ¡Gracias por participar!\n"
                f"Consulta la clasificación final en `#clasificaciones-torneos`."
            )
        except Exception as e:
            await ctx.send(f"⚠️ No se pudo enviar el mensaje en `#anuncios`: {e}")

    # Publicar clasificación final
    await actualizar_clasificacion_handle(ctx, codigo_torneo, canal_destino="clasificacion-general",  from_chanel = 1 )

async def new_tournament_assistance_handle(ctx, *, args=None):
    """Asistente por DM para crear un torneo paso a paso."""
    await borrar_mensaje_seguro(ctx)

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!nuevo-torneo"):
        return

    if args:
        await nuevo_torneo(ctx, args=args)
        return

    try:
        await ctx.author.send("🎮 ¡Vamos a crear un torneo! Responde a las siguientes preguntas paso a paso. Puedes cancelar en cualquier momento escribiendo `cancelar`.")

        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        await ctx.author.send("1️⃣ ¿Nombre del torneo?")
        nombre = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if nombre.content.lower() == "cancelar": return

        await ctx.author.send("2️⃣ ¿Formato? (Ej: Premodern, Classic-Legacy, 7Pts, Premodern Bondage, ...)")
        formato = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if formato.content.lower() == "cancelar": return

        await ctx.author.send("3️⃣ ¿Tipo de torneo en Challonge? (Ej: swiss, round robin, Single elimination)")
        tipo = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if tipo.content.lower() == "cancelar": return

        await ctx.author.send("4️⃣ ¿Número máximo de jugadores?")
        jugadores = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if jugadores.content.lower() == "cancelar": return
        try:
            int(jugadores.content)
        except ValueError:
            await ctx.author.send("❌ Debe ser un número.")
            return

        await ctx.author.send("5️⃣ ¿Fecha de inicio? (Formato: DD/MM/AAAA)")
        fecha = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if fecha.content.lower() == "cancelar": return
        try:
            datetime.strptime(fecha.content, "%d/%m/%Y")
        except ValueError:
            await ctx.author.send("❌ Fecha inválida. Usa el formato DD/MM/AAAA.")
            return

        await ctx.author.send("6️⃣ ¿Nivel o rol permitido para inscribirse? (Ej: abierto, nivel1, etc.)")
        nivel = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if nivel.content.lower() == "cancelar": return

        await ctx.author.send("7️⃣ ¿URL para envío de mazos (decklists)?")
        deck = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if deck.content.lower() == "cancelar": return

        # Construir args para pasar a la función existente
        args_final = f"{nombre.content} | {formato.content} | {tipo.content} | {jugadores.content} | {fecha.content} | {nivel.content} | {deck.content}"
        await nuevo_torneo(ctx, args=args_final)

    except discord.Forbidden:
        await ctx.send("❌ No pude enviarte mensajes privados. Asegúrate de tener los DMs habilitados.")
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Puedes volver a intentarlo enviando `!nuevo-torneo` en el servidor.")
