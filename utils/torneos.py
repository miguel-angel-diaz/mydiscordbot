import discord

import aiohttp
import asyncio

import re
import config
from datetime import datetime
import random
import string

from utils.commons import borrar_mensaje_seguro, validar_canal_correcto, obtener_torneo_usuario
from utils.admin import moderador_permisos_handle

CHALLONGE_API_KEY = "DwMmC03iVa5UKm377ZaScn6omJ3EA6jWRcPvzZOJ"

def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))

def slugify_challonge(value: str) -> str:
    # Convierte a minúsculas y elimina cualquier carácter que no sea letra o número
    value = value.lower()
    return re.sub(r'[^a-z0-9]', '', value)

async def new_tournament_assistance_handle(ctx, *, args=None):
    """Asistente por DM para crear un torneo paso a paso sin pedir deck URL."""
    await borrar_mensaje_seguro(ctx)

    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!nuevo-torneo"):
        return

    if args:
        await nuevo_torneo(ctx, args=args)
        return

    try:
        await ctx.author.send("🎮 ¡Vamos a crear un torneo! Responde a las siguientes preguntas paso a paso. Puedes cancelar escribiendo `cancelar`.")

        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        await ctx.author.send("1️⃣ ¿Nombre del torneo?")
        nombre = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if nombre.content.lower() == "cancelar": return

        await ctx.author.send("2️⃣ ¿Formato? (Ej: Premodern, Classic-Legacy, 7Pts, ...)")
        formato = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        if formato.content.lower() == "cancelar": return

        await ctx.author.send("3️⃣ ¿Tipo de torneo? (Ej: Swiss, Round Robin, Single elimination)")
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

        # Construir args final sin deck URL
        args_final = f"{nombre.content} | {formato.content} | {tipo.content} | {jugadores.content} | {fecha.content} | {nivel.content}"
        await nuevo_torneo(ctx, args=args_final)

    except discord.Forbidden:
        await ctx.send("❌ No pude enviarte mensajes privados. Asegúrate de tener los DMs habilitados.")
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Puedes volver a intentarlo enviando `!nuevo-torneo` en el servidor.")


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
    if len(partes) != 6:  # Eliminamos deck URL
        await ctx.author.send("❌ Formato incorrecto. Usa:\n`!nuevo-torneo Nombre | Formato | tipo | Jugadores | Fecha | Nivel`")
        return

    nombre, formato, tipo_challonge, jugadores, fecha, nivel = partes

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
            "start_at": fecha_obj.isoformat(),
            # ↓ Configuración de desempates
            "ranked_by": "match wins",  # Swiss system points
            "tie_breaks": [
                "match wins vs tied",     # Tie Break #1: Participantes ganadores vs. empatados
                "game w/l difference",    # Tie Break #2: Game/Set W-L Difference
                "median buchholz"         # Tie Break #3: Sistema de Median-Buchholz
            ]
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
                )

                # 📣 Anuncio en canal de torneos
                canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
                if canal_anuncios:
                    await canal_anuncios.send(
                        f"📢 **Nuevo torneo creado!**\n"
                        f"🏷️ **Nombre:** {nombre}\n"
                        f"🎮 **Formato:** {formato}\n"
                        f"👥 **Jugadores máximos:** {jugadores}\n"
                        f"📅 **Inicio:** {fecha}\n"
                        f"🔒 **Nivel:** {nivel}\n"
                        f" **Código:** {url_challonge}\n"
                    )
                else:
                    await ctx.author.send("⚠️ No se encontró el canal `📰-cartelera‐torneos` en este servidor.")
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

  # 🔹 Obtener código de torneo si no se pasó como argumento
    if codigo_torneo is None:
        mensaje_inicial = (
            "📩 No escribiste el código del torneo.\n"
            "Por favor, selecciona el torneo en el que deseas iniciar."
        )
        codigo_torneo = await obtener_torneo_usuario(ctx, mensaje_inicial=mensaje_inicial)
        if not codigo_torneo:
            return  # Usuario canceló o no está en ningún torneo
    # 4️⃣ Revisar qué jugadores han subido deck
    canal_decks = discord.utils.get(ctx.guild.text_channels, name="submitted-decks")
    decks_subidos = set()
    if canal_decks:
        async for msg in canal_decks.history(limit=500):
            for embed in msg.embeds:
                if embed.title and "Deck Subido" in embed.title:
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

   # 🔹 Obtener participantes del torneo
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                await ctx.author.send("⚠️ No se pudo obtener la lista de participantes.")
                return
            data = await resp.json()

    participantes = []
    no_subieron = []

    for p in data:
        participant = p.get("participant", {})
        user_id_str = str(participant.get("name"))  # Suponemos que es el ID de Discord
        codigo_completo = f"{codigo_torneo}_{user_id_str}"
        if codigo_completo in decks_subidos:
            participantes.append(f"{participant.get('name')} ✅")
        else:
            no_subieron.append({
                "name": participant.get("name"),        # Discord ID o lo que uses
                "challonge_id": participant.get("id")   # ID real de Challonge
            })

    # 🔹 Preparar mensaje DM
    mensaje_dm = "**Revisión de decks antes de iniciar el torneo:**\n\n"
    mensaje_dm += "Jugadores con deck subido:\n" + "\n".join(participantes) + "\n\n"
    mensaje_dm += "Jugadores SIN deck subido:\n" + "\n".join([p['name'] + " ❌" for p in no_subieron]) + "\n\n"
   # 🔹 Preguntar qué hacer con los participantes sin deck
    mensaje_dm += (
        "❓ ¿Qué deseas hacer con los jugadores que NO subieron deck?\n"
        "Responde con **'continuar'** para iniciar el torneo con todos los participantes, \n"
        "o **'eliminar'** para quitar a los que no subieron el deck. Tienes 90 segundos."
    )

    try:
        await ctx.author.send(mensaje_dm)

        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        respuesta = await ctx.bot.wait_for("message", check=dm_check, timeout=90.0)
        accion = respuesta.content.lower().strip()

        if accion == "eliminar":
            # Eliminar participantes sin deck usando el ID de Challonge
            for participant in no_subieron:
                url_delete = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants/{participant['challonge_id']}.json"
                async with aiohttp.ClientSession() as session:
                    async with session.delete(url_delete, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
                        if resp.status in (200, 204):
                            await ctx.author.send(f"✅ Eliminado del torneo: {participant['name']}")
                        else:
                            await ctx.author.send(f"⚠️ No se pudo eliminar: {participant['name']} (status {resp.status})")

        elif accion == "continuar":
            await ctx.author.send("✅ Se iniciará el torneo con todos los participantes, aunque algunos no hayan subido deck.")
        else:
            await ctx.author.send("❌ Opción no reconocida. Cancelo la operación.")
            return

        # 🔹 Confirmación de inicio del torneo
        confirmacion_msg = (
            "Se han actualizado los participantes según tu elección.\n"
            "¿Deseas iniciar el torneo ahora? Responde con **'sí'** para continuar o **'no'** para cancelar. Tienes 60 segundos."
        )
        await ctx.author.send(confirmacion_msg)

        respuesta_confirmacion = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        accion_inicio = respuesta_confirmacion.content.lower().strip()

        if accion_inicio != "sí" and accion_inicio != "si":
            await ctx.author.send("❌ Inicio de torneo cancelado por el usuario.")
            return

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Cancelando operación.")
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
                await ctx.author.send(f"⚠️ Error al obtener 🍸-citas‐a‐ciegas: {error_text}")
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

    # 🔹 Mapear IDs de participantes a nombres o miembros de Discord
    id_to_member = {}
    for p in participants_data:
        participant = p.get("participant", {})
        try:
            user_id = int(participant["name"])
            member = await ctx.guild.fetch_member(user_id)
            id_to_member[participant["id"]] = member  # Guardamos el Member real
        except (ValueError, discord.NotFound):
            # Si no se puede obtener el miembro, guardamos el string
            id_to_member[participant["id"]] = participant["name"]

    # 🔹 Función para mostrar participante de manera segura
    def formato_participante(member_or_name):
        if isinstance(member_or_name, discord.Member):
            return f"{member_or_name.display_name} ({member_or_name.mention})"
        else:
            return f"{member_or_name} (no en el servidor)"

    # 🔹 Preparar emparejamientos
    emparejamientos = []
    for match in matches_data:
        m = match.get("match", {})
        p1 = id_to_member.get(m.get("player1_id"))
        p2 = id_to_member.get(m.get("player2_id"))

        # Si no hay jugador asignado todavía
        if not p1 or not p2:
            emparejamientos.append(f"• Ronda {m.get('round')}: TBD vs TBD")
            continue

        # Mostrar "Nombre (@Mención)" usando la función segura
        p1_texto = formato_participante(p1)
        p2_texto = formato_participante(p2)

        emparejamientos.append(f"• Ronda {m.get('round')}: {p1_texto} vs {p2_texto}")

    # 🔹 Buscar canal de emparejamientos
    canal_emparejamientos = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
    if not canal_emparejamientos:
        await ctx.author.send("⚠️ No se encontró el canal `#🍸-citas‐a‐ciegas`.")
    else:
        # Publicar los emparejamientos
        await canal_emparejamientos.send(
            f"📢 **🍸-citas‐a‐ciegas de la primera ronda - Torneo `{codigo_torneo}`:**\n" +
            "\n".join(emparejamientos)
        )
   # Obtener clasificación inicial del torneo
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

                    # Intentamos mostrar como mención si es un ID válido
                    try:
                        miembro = await ctx.guild.fetch_member(int(nombre))
                        nombre_mostrado = f"{miembro.display_name} ({miembro.mention})"
                    except (ValueError, discord.NotFound):
                        nombre_mostrado = f"{nombre} (no en el servidor)"

                    clasificacion.append((seed, nombre_mostrado))

                clasificacion.sort()

                # Construir tabla en Markdown con tamaños fijos
                mensaje = f"📊 **Clasificación del torneo `{codigo_torneo}`:**\n"
                mensaje += "```"
                mensaje += "Rango | Participante           | G-P-E | MP  | OMW%   | GW%    | OGW%\n"
                mensaje += "------|------------------------|-------|-----|--------|--------|-------\n"

                for i, (seed, nombre) in enumerate(clasificacion, 1):
                    gpe = "0-0-0"
                    linea = f"{i:<5} | {nombre[:22]:<22} | {gpe:<5} | {0:<3} | {0:.3f}  | {0:.3f}  | {0:.3f}"
                    mensaje += linea + "\n"

                mensaje += "```"

                # 🔹 Canal de destino
                canal_clasificaciones = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
                if canal_clasificaciones:
                    await canal_clasificaciones.send(mensaje)
                else:
                    await ctx.author.send("⚠️ No se encontró el canal `#🍺-el‐ranking‐de‐la‐barra`.")
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

async def actualizar_clasificacion_handle(ctx, codigo_torneo: str):
    await borrar_mensaje_seguro(ctx)
    if not await moderador_permisos_handle(ctx):
        return

    if not codigo_torneo:
        await ctx.author.send("❌ Necesitas enviar el código del torneo.")
        return

    # 🔹 Obtener datos de Challonge
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"

    async with aiohttp.ClientSession() as session:
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return await ctx.send("❌ Error al obtener participantes.")
            participantes_raw = await resp.json()

        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                return await ctx.send("❌ Error al obtener emparejamientos.")
            matches_raw = await resp.json()

    # 🔹 Inicializar jugadores
    jugadores = {}
    for p in participantes_raw:
        part = p["participant"]
        jugadores[part["id"]] = {
            "name": part["name"],
            "mp": 0.0,  # match points: win=1, draw=0.5
            "games_won": 0,
            "games_played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "opponents": []
        }

    # 🔹 Procesar matches
    for m in matches_raw:
        match = m["match"]
        if match["state"] != "complete":
            continue

        p1, p2 = match["player1_id"], match["player2_id"]
        scores = match.get("scores_csv", "")
        try:
            s1, s2 = map(int, scores.strip().split("-"))
        except:
            continue

        if p1 not in jugadores or p2 not in jugadores:
            continue

        jugadores[p1]["opponents"].append(p2)
        jugadores[p2]["opponents"].append(p1)

        # Games
        jugadores[p1]["games_won"] += s1
        jugadores[p1]["games_played"] += s1 + s2
        jugadores[p2]["games_won"] += s2
        jugadores[p2]["games_played"] += s1 + s2

        # Match Points según Challonge
        if s1 > s2:
            jugadores[p1]["mp"] += 1.0
            jugadores[p1]["wins"] += 1
            jugadores[p2]["losses"] += 1
        elif s2 > s1:
            jugadores[p2]["mp"] += 1.0
            jugadores[p2]["wins"] += 1
            jugadores[p1]["losses"] += 1
        else:
            jugadores[p1]["mp"] += 0.5
            jugadores[p2]["mp"] += 0.5
            jugadores[p1]["draws"] += 1
            jugadores[p2]["draws"] += 1

    # 🔹 Calcular desempates y construir clasificación
    clasificacion = []
    for pid, datos in jugadores.items():
        # Tie Break #1: OMW% (Opponent Match Win)
        omw = 0.0
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            omw += opp["mp"] / total_matches
        omw = omw / len(datos["opponents"]) if datos["opponents"] else 0.0

        # Tie Break #2: Median-Buchholz
        buchholz_scores = []
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            buchholz_scores.append(opp["mp"] / total_matches)
        if buchholz_scores:
            if len(buchholz_scores) > 2:
                buchholz_scores_sorted = sorted(buchholz_scores)[1:-1]  # descartar mejor y peor
            else:
                buchholz_scores_sorted = buchholz_scores
            buchholz = sum(buchholz_scores_sorted) / len(buchholz_scores_sorted)
        else:
            buchholz = 0.0

        # Diferencia de puntos
        diff = datos["games_won"] - (datos["games_played"] - datos["games_won"])

        # Nombre visible
        try:
            miembro = await ctx.guild.fetch_member(int(datos["name"]))
            nombre = f"@{miembro.display_name}"
        except (ValueError, discord.NotFound):
            nombre = datos["name"]

        clasificacion.append({
            "nombre": nombre,
            "mp": datos["mp"],
            "omw": omw,
            "buchholz": buchholz,
            "diff": diff,
            "wins": datos["wins"],
            "losses": datos["losses"],
            "draws": datos["draws"]
        })

    # 🔹 Ordenar según criterios de Challonge
    clasificacion.sort(key=lambda x: (-x["mp"], -x["diff"], -x["buchholz"], -x["omw"]))
    # clasificacion.sort(key=lambda x: (-x["mp"], -x["omw"], -x["diff"], -x["buchholz"]))

    # Construir tabla en Markdown
    mensaje = f"📊 **Clasificación del torneo `{codigo_torneo}`:**\n"
    mensaje += "```markdown\n"
    mensaje += "Rango | Participante           | G-P-E | Pts  | OMW%   | Buchholz | Dif\n"
    mensaje += "------|------------------------|-------|------|--------|----------|-----\n"
    for i, p in enumerate(clasificacion, 1):
        gpe = f"{p['wins']}-{p['losses']}-{p['draws']}"
        linea = f"{i:<5} | {p['nombre'][:22]:<22} | {gpe:<5} | {p['mp']:<4.1f} | {p['omw']:.3f}  | {p['buchholz']:.5f}  | {p['diff']:+}"
        mensaje += linea + "\n"
    mensaje += "```"

    # 🔹 Canal de destino
    canal = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal:
        return await ctx.send("⚠️ No se encontró el canal de clasificaciones.")

    # Revisar si ya existe un mensaje con el mismo torneo
    mensaje_existente = None
    async for msg in canal.history(limit=50):
        if msg.author == ctx.guild.me and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del torneo `{codigo_torneo}`:**"):
                mensaje_existente = msg
                break

    if mensaje_existente:
        await mensaje_existente.edit(content=mensaje)
    else:
        await canal.send(mensaje)

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
                await ctx.author.send("❌ Error al obtener las 🍸-citas‐a‐ciegas del torneo.")
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
    mensaje = f"📋 **🍸-citas‐a‐ciegas del torneo `{codigo_torneo}`:**\n"
    for ronda, p1, p2, _, _ in pendientes:
        mensaje += f"• Ronda {ronda}: {p1} vs {p2}\n"

    # Canal de emparejamientos
    canal_emparejamientos = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
    if canal_emparejamientos:
        # Buscar mensajes existentes con el mismo torneo y eliminarlos
        async for msg in canal_emparejamientos.history(limit=50):
            if msg.author == ctx.guild.me and not msg.embeds:
                if msg.content.startswith(f"📋 **🍸-citas‐a‐ciegas pendientes del torneo `{codigo_torneo}`:**"):
                    try:
                        await msg.delete()
                    except discord.Forbidden:
                        pass  # No tenemos permisos para borrar
                    except discord.NotFound:
                        pass  # Mensaje ya borrado

        # Enviar nuevo mensaje
        await canal_emparejamientos.send(mensaje)
    else:
        await ctx.author.send("⚠️ No se encontró el canal `#🍸-citas‐a‐ciegas`.")

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


    await actualizar_clasificacion_handle(ctx, codigo_torneo)

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
                await ctx.send("❌ Error al obtener las 🍸-citas‐a‐ciegas del torneo.")
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
        "🍺-quién‐se‐lleva‐la‐ronda",
        "🍸-citas‐a‐ciegas"
    ]

    for nombre_canal in canales_a_limpiar:
        canal = discord.utils.get(ctx.guild.text_channels, name=nombre_canal)
        if not canal:
            await ctx.send(f"⚠️ No se encontró el canal `{nombre_canal}`.")
            continue
        try:
            def filtro(msg):
                return codigo_torneo in msg.content
            await canal.purge(check=filtro)
        except Exception as e:
            await ctx.send(f"⚠️ No se pudo limpiar el canal `{nombre_canal}`: {e}")
     # Enviar anuncio al canal #anuncios
    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
    if canal_anuncios:
        try:
            await canal_anuncios.send(
                f"📢 @everyone\n"
                f"🏁 El torneo `{codigo_torneo}` ha finalizado. ¡Gracias por participar!\n"
                f"Consulta la clasificación final en `#🍺-el‐ranking‐de‐la‐barra`."
            )
        except Exception as e:
            await ctx.send(f"⚠️ No se pudo enviar el mensaje en `#anuncios`: {e}")

    # Publicar clasificación final
    await actualizar_clasificacion_handle(ctx, codigo_torneo)


