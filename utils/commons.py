######## commons.py #######
import asyncio
import aiohttp
import config
import discord
from functools import wraps
from collections import Counter
import io
import matplotlib.pyplot as plt
import re
import time
from datetime import datetime, timezone

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
    nombre_busqueda = nombre_busqueda.strip().lower()

    for miembro in guild.members:
        if miembro.display_name.lower() == nombre_busqueda:
            return miembro

    for miembro in guild.members:
        if miembro.name.lower() == nombre_busqueda:
            return miembro

    for miembro in guild.members:
        if nombre_busqueda in miembro.display_name.lower():
            return miembro

    for miembro in guild.members:
        if nombre_busqueda in miembro.name.lower():
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

async def cartas_mas_jugadas(ctx, codigo_torneo: str = None, channel: str = None):
    await borrar_mensaje_seguro(ctx)
    if channel != None:
        canal_submitted = discord.utils.get(ctx.guild.text_channels, name = channel)
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

        if not canal_submitted:
            await ctx.author.send(file=discord.File(fp=buf, filename=f"cartas_mas_jugadas_{torneo}.png"))
        else:
            await canal_submitted.send(file=discord.File(fp=buf, filename=f"cartas_mas_jugadas_{torneo}.png"))
            return {
                "torneo": torneo,
                "top_cartas": top  # lista de (carta, cantidad)
            }

async def best_decks_handle(ctx, codigo_torneo: str = None, channel: str = None):
    await borrar_mensaje_seguro(ctx)
    author = ctx.author
    if channel != None:
        canal_submitted = discord.utils.get(ctx.guild.text_channels, name = channel)
    # 🔹 Obtener código de torneo
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 No escribiste el código del torneo.\n"
                            "Elige uno de los torneos en los que estás inscrito:",
            complete=True
        )
        if not codigo_torneo:
            return

    # 🔹 Canal ranking
    canal_ranking = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return await ctx.send("❌ No encontré el canal de ranking.")

    # 🔹 Buscar clasificación
    mensaje_clasificacion = None
    async for msg in canal_ranking.history(limit=100):
        if msg.content.startswith(f"📊 **Clasificación del torneo `{codigo_torneo}`:**"):
            mensaje_clasificacion = msg
            break

    if not mensaje_clasificacion:
        return await author.send(f"❌ No encontré clasificación para `{codigo_torneo}`.")

    # 🔹 Parsear jugadores (discord_id)
    jugadores_ordenados = []

    for linea in mensaje_clasificacion.content.splitlines():
        if "|" not in linea:
            continue
        if linea.strip().startswith(("Rango", "-----", "```")):
            continue

        partes = [p.strip() for p in linea.split("|")]
        if len(partes) < 2:
            continue

        nombre = partes[1].strip("@")
        miembro = buscar_usuario_en_servidor(ctx.guild, nombre)
        if miembro:
            jugadores_ordenados.append(miembro.id)

    if not jugadores_ordenados:
        return await author.send("❌ No se pudieron identificar jugadores.")

    # 🔹 TOP 4 + ÚLTIMO
    seleccionados = jugadores_ordenados[:4]
    if len(jugadores_ordenados) > 4:
        seleccionados.append(jugadores_ordenados[-1])

    await author.send(
        f"📊 **Best Decks – `{codigo_torneo}`**\n"
        f"TOP 4 + Último clasificado"
    )
    ranking = []
    # 🔹 Buscar y enviar decks
    for idx, jugador_id in enumerate(seleccionados):
        codigo_deck = f"{codigo_torneo}_{jugador_id}"
        deck = await obtener_deck_en_canal(ctx.guild, codigo_deck)

        if not deck:
            await author.send(f"⚠️ No encontré deck para <@{jugador_id}>.")
            continue

        # Determinar posición
        if idx == len(seleccionados) - 1:
            pos = "cuchara de palo"
        else:
            pos = idx + 1

        # Guardar ranking para IA
        ranking.append({
            "pos": pos,
            "archetype": deck["archetype"] or "Desconocido"
        })

        # --- EMBED (igual que antes) ---
        try:
            miembro = await ctx.guild.fetch_member(jugador_id)
            nombre = miembro.display_name
        except:
            nombre = str(jugador_id)

        embed_final = discord.Embed(
            title=f"🃏 Deck – {nombre}",
            color=discord.Color.blue()
        )

        embed_final.add_field(
            name="Jugador",
            value=f"{nombre} (ID: {jugador_id})",
            inline=False
        )

        embed_final.add_field(
            name="Archetype",
            value=deck["archetype"] or "No especificado",
            inline=False
        )

        embed_final.add_field(
            name="Decklist",
            value=deck["decklist"][:1000] or "Vacío",
            inline=False
        )

        embed_final.add_field(
            name="Sideboard",
            value=deck["sideboard"][:1000] or "N/A",
            inline=False
        )

        embed_final.set_footer(
            text=f"Torneo {codigo_torneo} • Best Decks"
        )

        await author.send(embed=embed_final)
    if not canal_submitted:
        await author.send(embed=embed_final)
    else:
        await canal_submitted.send(embed=embed_final)
        return {
            "torneo": codigo_torneo,
            "ranking": ranking
        }

    await author.send("✅ Análisis de mejores decks completado.")

async def obtener_deck_en_canal(guild: discord.Guild, codigo_deck: str):
    """
    Busca en el canal 'submitted-decks' un deck con el código dado.
    Retorna un dict con todos los datos del deck, o None si no existe.
    """
    canal_submitted = discord.utils.get(guild.text_channels, name="submitted-decks")
    if not canal_submitted:
        return None

    async for mensaje in canal_submitted.history(limit=500):
        for embed in mensaje.embeds:
            if embed.description and codigo_deck in embed.description:
                # Extraer campos del embed
                campos = {field.name.lower(): field.value for field in embed.fields}

                # Extraer nombre del deck del título
                nombre_deck_extraido = (
                    embed.title
                    .replace("🃏 Deck Subido: ", "")
                    .replace("🃏 Deck Actualizado: ", "")
                )

                # Extraer torneo y jugador del código
                partes = codigo_deck.split("_")
                if len(partes) != 2:
                    continue

                id_torneo, jugador_id = partes

                # ✅ Extraer el campo "edited" o "ediciones post-inicio"
                edited = 0
                for field_name in ["edited", "ediciones post-inicio"]:
                    if field_name in campos:
                        try:
                            valor = campos[field_name]
                            # Si es formato "1/1", tomar el primer número
                            if "/" in valor:
                                edited = int(valor.split("/")[0])
                            else:
                                edited = int(valor)
                            break
                        except (ValueError, IndexError):
                            edited = 0

                return {
                    "mensaje": mensaje,
                    "nombre_deck": nombre_deck_extraido,
                    "torneo": id_torneo,
                    "jugador_id": int(jugador_id),
                    "edited": edited,
                    "archetype": campos.get("archetype", ""),
                    "decklist": campos.get("decklist", ""),
                    "sideboard": campos.get("sideboard", "N/A")
                }

    return None

async def analizar_torneo_con_ia(ctx, cartas_data, decks_data):

    memoria = await cargar_memoria_ia(ctx.guild, limite=10)

    analisis = await generar_analisis_ia(cartas_data, decks_data, memoria)

    if not analisis or analisis.strip() == "":
        await ctx.send("⚠️ La IA no devolvió contenido.")
        return

    await publicar_en_discord(ctx, analisis)
    await guardar_memoria_ia(ctx.guild, "ANALYSIS", analisis)


# ==========================================================
# 🔹 GENERAR ANÁLISIS
# ==========================================================
async def generar_analisis_ia(cartas_data, decks_data, memoria):

    memoria_texto = "\n".join(memoria) if memoria else "Sin memoria previa."

    top_cartas = ", ".join(
        [f"{carta} ({cant})" for carta, cant in cartas_data['top_cartas'][:10]]
    )

    ranking = ", ".join(
        [f"Pos {r['pos']}: {r['archetype']}" for r in decks_data['ranking']]
    )

    prompt = f"""
Eres un analista experto de torneos de Magic.

Analiza el torneo en tono narrativo pero centrado en:
- Metajuego
- Interacción entre decks
- Cartas clave
- Tendencias reales

MEMORIA:
{memoria_texto}

TORNEO ACTUAL:

Cartas más jugadas:
{top_cartas}

Ranking:
{ranking}

Escribe un análisis completo con varios párrafos y conclusión clara.
"""

    return await llamar_a_openrouter(prompt)


# ==========================================================
# 🔹 LLAMADA A OPENROUTER
# ==========================================================
async def llamar_a_openrouter(prompt: str):

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "openrouter/free",
        "messages": [
            {"role": "system", "content": "Eres analista de torneos competitivo."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 1500
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                print("ERROR OPENROUTER:", resp.status)
                print(await resp.text())
                return None

            data = await resp.json()

            try:
                return data["choices"][0]["message"]["content"].strip()
            except:
                print("Respuesta inesperada:", data)
                return None


# ==========================================================
# 🔹 PUBLICAR EN DISCORD (DIVISIÓN INTELIGENTE 1000 CHARS)
# ==========================================================
async def publicar_en_discord(ctx, texto):

    canal = discord.utils.get(ctx.guild.text_channels, name="🧠📈analisis-torneos")
    destino = canal or ctx

    bloques = dividir_texto_inteligente(texto, 1000)

    for bloque in bloques:
        await destino.send(bloque)


# ==========================================================
# 🔹 GUARDAR MEMORIA (TAMBIÉN FRAGMENTADO)
# ==========================================================
async def guardar_memoria_ia(guild, tipo, contenido):

    canal = discord.utils.get(guild.text_channels, name="ia-context")
    if not canal:
        return

    texto = f"[{tipo}]\n{contenido}\n" + "-"*50

    bloques = dividir_texto_inteligente(texto, 1000)

    for bloque in bloques:
        await canal.send(bloque)


# ==========================================================
# 🔹 CARGAR MEMORIA
# ==========================================================
async def cargar_memoria_ia(guild, limite=10):

    canal = discord.utils.get(guild.text_channels, name="ia-context")
    if not canal:
        return []

    recuerdos = []

    async for msg in canal.history(limit=limite):
        recuerdos.append(msg.content)

    recuerdos.reverse()
    return recuerdos


# ==========================================================
# 🔹 FUNCIÓN CLAVE: DIVISIÓN INTELIGENTE
# ==========================================================
def dividir_texto_inteligente(texto, limite=1000):
    """
    Divide el texto buscando el punto más cercano antes del límite.
    Si no hay punto, corta por espacio.
    """

    bloques = []
    while len(texto) > limite:

        corte = texto.rfind(".", 0, limite)

        if corte == -1:
            corte = texto.rfind(" ", 0, limite)

        if corte == -1:
            corte = limite

        bloques.append(texto[:corte + 1].strip())
        texto = texto[corte + 1:].strip()

    if texto:
        bloques.append(texto)

    return bloques

async def calcular_clasificacion_torneo(guild, codigo_torneo: str):
    """
    Calcula la clasificación completa de un torneo de Challonge,
    cruzando los IDs de Discord guardados en Challonge con los
    miembros reales del servidor.

    Devuelve una lista de dicts, ya ordenada, con 'rank' asignado.
    Cada jugador incluye: nombre, avatar, mp, omw, buchholz, diff,
    wins, losses, draws, rank.
    """

    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"

    async with aiohttp.ClientSession() as session:
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                raise Exception("Error al obtener participantes.")
            participantes_raw = await resp.json()

        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                raise Exception("Error al obtener emparejamientos.")
            matches_raw = await resp.json()

    jugadores = {}
    for p in participantes_raw:
        part = p["participant"]
        jugadores[part["id"]] = {
            "name": part["name"],
            "mp": 0,
            "games_won": 0,
            "games_played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "opponents": []
        }

    for m in matches_raw:
        match = m["match"]
        if match["state"] != "complete":
            continue

        p1, p2 = match["player1_id"], match["player2_id"]
        scores = match.get("scores_csv", "").strip()

        if p1 and not p2 and p1 in jugadores:
            jugadores[p1]["mp"] += 3
            jugadores[p1]["wins"] += 1
            continue
        if p2 and not p1 and p2 in jugadores:
            jugadores[p2]["mp"] += 3
            jugadores[p2]["wins"] += 1
            continue

        try:
            s1, s2 = map(int, scores.split("-"))
        except Exception:
            continue

        if p1 not in jugadores or p2 not in jugadores:
            continue

        jugadores[p1]["opponents"].append(p2)
        jugadores[p2]["opponents"].append(p1)
        jugadores[p1]["games_won"] += s1
        jugadores[p1]["games_played"] += s1 + s2
        jugadores[p2]["games_won"] += s2
        jugadores[p2]["games_played"] += s1 + s2

        if s1 > s2:
            jugadores[p1]["mp"] += 3
            jugadores[p1]["wins"] += 1
            jugadores[p2]["losses"] += 1
        elif s2 > s1:
            jugadores[p2]["mp"] += 3
            jugadores[p2]["wins"] += 1
            jugadores[p1]["losses"] += 1
        else:
            jugadores[p1]["mp"] += 1
            jugadores[p2]["mp"] += 1
            jugadores[p1]["draws"] += 1
            jugadores[p2]["draws"] += 1

    clasificacion = []
    for pid, datos in jugadores.items():
        omw = 0.0
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            omw += opp["mp"] / (total_matches * 3)
        omw = omw / len(datos["opponents"]) if datos["opponents"] else 0.0

        buchholz_scores = []
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            buchholz_scores.append(opp["mp"] / (total_matches * 3))
        if buchholz_scores:
            buchholz_scores_sorted = sorted(buchholz_scores)[1:-1] if len(buchholz_scores) > 2 else buchholz_scores
            buchholz = sum(buchholz_scores_sorted) / len(buchholz_scores_sorted)
        else:
            buchholz = 0.0

        diff = datos["games_won"] - (datos["games_played"] - datos["games_won"])

        nombre = datos["name"]
        avatar = None
        try:
            miembro = await guild.fetch_member(int(datos["name"]))
            nombre = miembro.display_name
            avatar = str(miembro.display_avatar.url)
            discord_id_resuelto = str(miembro.id)
        except (ValueError, discord.NotFound, AttributeError):
            pass

        clasificacion.append({
            "nombre": nombre,
            "avatar": avatar,
            "mp": datos["mp"],
            "omw": round(omw, 3),
            "discord_id": discord_id_resuelto,   # NUEVO
            "buchholz": round(buchholz, 5),
            "diff": diff,
            "wins": datos["wins"],
            "losses": datos["losses"],
            "draws": datos["draws"]
        })

    clasificacion.sort(key=lambda x: (-x["mp"], -x["omw"], -x["diff"], -x["buchholz"]))

    for i, p in enumerate(clasificacion, 1):
        p["rank"] = i

    return clasificacion

DECK_ID_REGEX = re.compile(r"\(ID:\s*(\d+)\)")

def obtener_lista_arquetipos():
    """Lista completa de arquetipos, para poblar un <select>/<datalist>."""
    return [a["nombre"] for a in config.ARQUETIPOS_PREMODERN]

async def obtener_info_torneo_canal(guild, codigo_torneo):
    """
    Busca en #torneos-activos el mensaje del torneo y devuelve información
    (fecha_inicio, nivel, total_maximo) sin llamar a Challonge.
    """
    canal = discord.utils.get(guild.text_channels, name="torneos-activos")
    if not canal:
        return None
    async for msg in canal.history(limit=100):
        if codigo_torneo in msg.content:
            lineas = msg.content.splitlines()
            info = {}
            for linea in lineas:
                if "📅 Inicio:" in linea:
                    info["fecha_inicio"] = linea.split("📅 Inicio:")[1].strip()
                elif "🎯 Nivel:" in linea:
                    info["nivel"] = linea.split("🎯 Nivel:")[1].strip()
                elif "👥 Jugadores:" in linea:
                    try:
                        info["total_maximo"] = int(linea.split("👥 **Jugadores:**")[1].strip())
                    except:
                        pass
            return info
    return None

async def validar_torneo_para_edicion(codigo_torneo: str, author: discord.Member, bot=None):
    """
    Valida que el usuario pueda editar su deck en el torneo.
    Usa el estado y el canal #torneos-activos, sin llamar a Challonge.
    Retorna: (ok: bool, mensaje: str)
    """
    from utils.torneos_estado import leer_estado
    from datetime import datetime, timezone
    import time

    if bot is None:
        bot = author._state._get_client()

    guild = author.guild

    # 1. Verificar inscripción desde el estado
    estado = await leer_estado(bot)
    torneo_estado = next((t for t in estado.get("torneos", []) if t.get("codigo") == codigo_torneo), None)
    if not torneo_estado:
        return False, f"❌ El torneo `{codigo_torneo}` no está activo o no existe en el estado."

    inscritos_ids = torneo_estado.get("inscritos_ids", [])
    if str(author.id) not in inscritos_ids:
        return False, f"❌ No estás inscrito en el torneo `{codigo_torneo}`."

    # 2. Verificar fecha de inicio desde el canal #torneos-activos
    info_canal = await obtener_info_torneo_canal(guild, codigo_torneo)
    if not info_canal:
        # Si no hay info en el canal, pero está en el estado, permitimos edición (por si acaso)
        return True, "✅ Torneo encontrado en el estado, pero sin fecha de inicio en el canal. Edición permitida."

    fecha_inicio_str = info_canal.get("fecha_inicio")
    if not fecha_inicio_str:
        return True, "✅ Sin fecha de inicio configurada. Edición permitida."

    # Convertir a timestamp (formato DD/MM/YYYY)
    try:
        fecha_inicio_dt = datetime.strptime(fecha_inicio_str, "%d/%m/%Y")
        # Asumimos hora 00:00 UTC
        timestamp_inicio = fecha_inicio_dt.replace(tzinfo=timezone.utc).timestamp()
        timestamp_ahora = time.time()
        if timestamp_ahora >= timestamp_inicio:
            return False, f"❌ El torneo ya comenzó (inicio: {fecha_inicio_str})."
        else:
            horas_restantes = (timestamp_inicio - timestamp_ahora) / 3600
            return True, f"✅ El torneo comienza en {horas_restantes:.1f} horas."
    except Exception as e:
        print(f"Error parseando fecha: {e}")
        return True, "⚠️ No se pudo verificar la fecha de inicio. Edición permitida con precaución."
    
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

async def obtener_torneos_activos_canal(guild):
    canal_torneos = discord.utils.get(guild.text_channels, name="torneos-activos")
    if not canal_torneos:
        return []

    torneos = []
    async for mensaje in canal_torneos.history(limit=100):
        lineas = mensaje.content.splitlines()
        codigo = None
        nombre = None
        nivel = "Todos"
        total_maximo = None

        for linea in lineas:
            if "🏷️ Código:" in linea:
                codigo = linea.split("🏷️ Código:")[-1].strip().strip("`")
            if "🎮 **Torneo creado:**" in linea:
                nombre = linea.split("🎮 **Torneo creado:**")[-1].strip()
            elif "🏷️ **Nombre:**" in linea:
                nombre = linea.split("🏷️ **Nombre:**")[-1].strip()
            if "Nivel:" in linea or "Roles permitidos:" in linea:
                linea_limpia = linea.replace("*", "").lower()
                if "nivel:" in linea_limpia:
                    nivel = linea_limpia.split("nivel:")[-1].strip()
                elif "roles permitidos:" in linea_limpia:
                    nivel = linea_limpia.split("roles permitidos:")[-1].strip()
            if linea.startswith("👥"):
                try:
                    total_maximo = int(linea.split("👥 **Jugadores:**")[-1].strip())
                except ValueError:
                    total_maximo = None

        if not codigo:
            continue

        torneos.append({
            "codigo": codigo,
            "nombre": nombre or "Torneo sin nombre",
            "nivel": nivel.capitalize(),
            "total_maximo": total_maximo,
        })

    return torneos
async def obtener_estado_torneos_usuario(guild, member: discord.Member):
    """
    Versión SIN llamadas a Challonge. Lee el estado desde el canal de estado.
    """
    from utils.torneos_estado import leer_estado

    torneos_activos = await obtener_torneos_activos_canal(guild)
    if not torneos_activos:
        return []

    decks_usuario = await obtener_decks_por_usuario(guild, str(member.id))
    decks_por_torneo = {d["codigo_torneo"]: d for d in decks_usuario if d.get("codigo_torneo")}

    # Leer estado completo (una sola vez)
    estado = await leer_estado(guild._state._get_client())
    torneos_estado = {t["codigo"]: t for t in estado.get("torneos", [])}

    resultado = []
    for torneo in torneos_activos:
        codigo = torneo["codigo"]
        tipo_socios = "socio" in codigo.lower() or torneo["nivel"].lower() == "socios"
        roles_permitidos = config.ROLES_SOCIOS if tipo_socios else config.ROLES_TODOS
        if not tiene_rol_permitido(member, roles_permitidos):
            continue

        info_estado = torneos_estado.get(codigo, {})
        inscritos_ids = info_estado.get("inscritos_ids", [])
        total_inscritos = len(inscritos_ids)
        total_maximo = torneo.get("total_maximo")
        plazas_restantes = total_maximo - total_inscritos if total_maximo else None

        deck = decks_por_torneo.get(codigo)
        resultado.append({
            "codigo": codigo,
            "nivel": torneo["nivel"],
            "inscrito": str(member.id) in inscritos_ids,
            "total_inscritos": total_inscritos,
            "total_maximo": total_maximo,
            "plazas_restantes": plazas_restantes,
            "deck_subido": bool(deck),
            "deck_nombre": deck["nombre_deck"] if deck else None,
        })
    return resultado

# utils/commons.py

async def inscribir_usuario_web(guild, member: discord.Member, codigo_torneo: str):
    """
    Versión SIN Challonge: inscribe al usuario en el torneo usando el estado del canal.
    Devuelve (ok: bool, mensaje: str).
    """
    from utils.torneos_estado import leer_estado, guardar_estado

    # 1. Leer el estado completo
    estado = await leer_estado(guild._state._get_client())  # pasamos el bot
    torneos_estado = estado.get("torneos", [])
    torneo = next((t for t in torneos_estado if t.get("codigo") == codigo_torneo), None)

    if not torneo:
        return False, "Ese torneo no está activo o no se encontró en el estado."

    # 2. Validar roles (nivel)
    nivel = torneo.get("nivel", "todos").lower()
    roles_permitidos = config.ROLES_SOCIOS if nivel == "socios" else config.ROLES_TODOS
    if not tiene_rol_permitido(member, roles_permitidos):
        return False, "No tienes los roles necesarios para inscribirte a este torneo."

    # 3. Verificar si ya está inscrito
    inscritos_ids = torneo.get("inscritos_ids", [])
    if str(member.id) in inscritos_ids:
        return False, "Ya estás inscrito en este torneo."

    # 4. Verificar plazas
    total_maximo = torneo.get("total_maximo")
    if total_maximo and len(inscritos_ids) >= total_maximo:
        return False, "No quedan plazas disponibles para este torneo."

    # 5. Añadir al usuario
    inscritos_ids.append(str(member.id))
    torneo["inscritos_ids"] = inscritos_ids

    # 6. Guardar el estado actualizado
    await guardar_estado(guild._state._get_client(), estado)

    return True, f"Te has inscrito correctamente en `{codigo_torneo}`."

def tiene_rol_permitido(member: discord.Member, roles_permitidos: set):
    return any(role.name in roles_permitidos for role in member.roles)


# utils/commons.py

def _parsear_embed_deck(embed: discord.Embed) -> dict | None:
    campos = {f.name: f.value for f in embed.fields}

    jugador_raw = campos.get("Jugador", "")
    match_id = DECK_ID_REGEX.search(jugador_raw)
    if not match_id:
        return None

    discord_id = match_id.group(1)

    titulo = embed.title or ""
    nombre_deck = re.sub(r"^🃏\s*Deck (Subido|Actualizado):\s*", "", titulo).strip()
    if not nombre_deck:
        nombre_deck = titulo

    descripcion = embed.description or ""

    # 🔥 Buscar "Código:" con o sin backticks
    codigo_deck = None
    match_codigo = re.search(r"Código:\s*`?([^`\n]+)`?", descripcion)
    if match_codigo:
        codigo_deck = match_codigo.group(1).strip()
    else:
        # Intentar buscar "Código:" sin backticks y hasta el final de línea
        match_codigo = re.search(r"Código:\s*([^\n]+)", descripcion)
        if match_codigo:
            codigo_deck = match_codigo.group(1).strip()

    # 🔥 Buscar "Torneo:" con o sin backticks
    codigo_torneo = None
    match_torneo = re.search(r"Torneo:\s*`?([^`\n]+)`?", descripcion)
    if match_torneo:
        codigo_torneo = match_torneo.group(1).strip()
    else:
        match_torneo = re.search(r"Torneo:\s*([^\n]+)", descripcion)
        if match_torneo:
            codigo_torneo = match_torneo.group(1).strip()

    # Si no se encontró torneo en la descripción, extraerlo del código
    if not codigo_torneo and codigo_deck:
        partes = codigo_deck.split("_")
        if len(partes) >= 2:
            codigo_torneo = partes[0]

    try:
        edited = int(campos.get("Ediciones post-inicio", campos.get("edited", "0")).split("/")[0])
    except (ValueError, AttributeError):
        edited = 0

    return {
        "nombre_deck": nombre_deck,
        "codigo_deck": codigo_deck,
        "codigo_torneo": codigo_torneo,
        "discord_id": discord_id,
        "archetype": campos.get("Archetype", "Desconocido"),
        "decklist": campos.get("Decklist", ""),
        "sideboard": campos.get("Sideboard", ""),
        "edited": edited,
    }

# utils/commons.py

async def obtener_decks_por_usuario(guild, discord_id: str, limite: int = 500, include_message: bool = False):
    canal = discord.utils.get(guild.text_channels, name="submitted-decks")
    if not canal:
        return []

    decks = []
    async for mensaje in canal.history(limit=limite):
        if not mensaje.embeds:
            continue

        for embed in mensaje.embeds:
            deck = _parsear_embed_deck(embed)
            if deck and deck["discord_id"] == discord_id:
                if include_message:
                    deck["_mensaje"] = mensaje
                decks.append(deck)

    return decks

async def editar_deck_web(guild, member: discord.Member, codigo_torneo: str, nombre_deck: str, archetype: str, decklist: str, sideboard: str):
    """
    Versión web (sin DMs) de editar_deck_handle: aplica exactamente las
    mismas reglas de ediciones permitidas que el flujo de Discord.
    """

    codigo_deck = f"{codigo_torneo}_{member.id}"

    decks = await obtener_decks_por_usuario(guild, str(member.id))
    deck_actual = next((d for d in decks if d["codigo_deck"] == codigo_deck), None)

    if not deck_actual:
        return False, "No se encontró tu deck para este torneo. Debes subirlo primero."

    ok_validacion, mensaje_validacion = await validar_torneo_para_edicion(codigo_torneo, member)

    edited_actual = deck_actual["edited"]

    if not ok_validacion:
        if edited_actual >= 1:
            return False, f"No puedes editar tu deck: ya usaste tu única edición disponible. {mensaje_validacion}"
        nuevo_edited = edited_actual + 1
    else:
        nuevo_edited = edited_actual

    color_embed = discord.Color.blue() if nuevo_edited == 0 else discord.Color.orange()

    embed_final = discord.Embed(
        title=f"🃏 Deck Actualizado: {nombre_deck}",
        description=f"**Código:** `{codigo_deck}`\n**Torneo:** `{codigo_torneo}`",
        color=color_embed
    )
    embed_final.add_field(name="Jugador", value=f"{member.mention} (ID: {member.id})", inline=False)
    embed_final.add_field(name="Archetype", value=archetype, inline=False)
    embed_final.add_field(name="Decklist", value=decklist[:1000], inline=False)
    embed_final.add_field(name="Sideboard", value=sideboard[:1000], inline=False)
    embed_final.add_field(name="Ediciones post-inicio", value=f"{nuevo_edited}/1", inline=False)

    fecha_legible = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    embed_final.set_footer(text=f"Última edición: {fecha_legible} (vía web)")

    mensaje = deck_actual["_mensaje"]

    try:
        await mensaje.edit(embed=embed_final)
    except discord.NotFound:
        return False, "No se pudo actualizar el deck (el mensaje original ya no existe). Contacta con un administrador."
    except discord.Forbidden:
        return False, "No tengo permisos para editar el mensaje del deck."

    return True, mensaje_validacion
