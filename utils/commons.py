import asyncio
import aiohttp
import config
import discord
from functools import wraps
from collections import Counter
import io
import matplotlib.pyplot as plt

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
                 # ✅ Edited: si no existe, es 0
                try:
                    edited = int(campos.get("edited", 0))
                except ValueError:
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
    """
    Flujo completo para generar análisis de torneo con IA.
    1️⃣ Cargar memoria previa
    2️⃣ Generar narrativa
    3️⃣ Publicar análisis
    4️⃣ Extraer aprendizaje y guardar
    """
    # 1️⃣ Cargar memoria previa
    memoria = await cargar_memoria_ia(ctx.guild, limite=15)

    # 2️⃣ Generar análisis narrativo
    analisis = await generar_analisis_ia(cartas_data, decks_data, memoria)

    # 3️⃣ Publicar análisis
    canal = discord.utils.get(ctx.guild.text_channels, name="🧠📈analisis-torneos")
    if canal:
        await canal.send(analisis)
    else:
        await ctx.send(analisis)

    # 4️⃣ Extraer aprendizaje
    resumen = await extraer_memoria_desde_analisis(analisis)

    # 5️⃣ Guardar aprendizaje
    await guardar_memoria_ia(ctx.guild, "SUMMARY", resumen)

async def extraer_memoria_desde_analisis(texto):
    """
    Extrae la narrativa completa y las tendencias del análisis
    para ir alimentando la memoria del bot.
    """
    prompt = f"""
A partir del siguiente análisis de torneo, genera un resumen completo
de las tendencias de metajuego y la narrativa general,
incluyendo cartas clave, estrategias y eventos interesantes,
sin mencionar nombres de jugadores:

{texto}
"""
    return await llamar_a_chatgpt(prompt)

async def llamar_a_chatgpt(prompt: str, debug=False) -> str:
    """
    Llamada al modelo gratuito de OpenRouter para generar análisis.
    Completamente asíncrona con aiohttp.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "openrouter/free",  # modelo gratuito
        "messages": [
            {"role": "system", "content": "Eres un analista experto de torneos de Magic. Usa humor ligero y narrativa continua."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 500
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            texto = data["choices"][0]["message"]["content"].strip()

    return texto

async def generar_analisis_ia(cartas_data, decks_data, memoria):
    """
    Genera un análisis narrativo de torneo, usando la memoria histórica.
    """
    memoria_texto = "\n".join(memoria)

    prompt = f"""
eres un analista escribe como si narrara un torneo en una taberna de Magic.
Usa humor ligero, ironía elegante con un toque spicy y referencias recurrentes.
Nunca menciona nombres de jugadores.
Al último clasificado lo llama "cuchara de palo".
Burn suele sufrir.
Control siempre sobrevive.
El metajuego se analiza como una historia continua.

MEMORIA DEL ANALISTA:
{memoria_texto}

TORNEO ACTUAL:

Cartas más jugadas:
{', '.join([f"{carta} ({cant})" for carta, cant in cartas_data['top_cartas'][:10]])}

Ranking de decks:
{', '.join([f"Pos {r['pos']}: {r['archetype']}" for r in decks_data['ranking']])}

INSTRUCCIONES:
- Construye una narrativa coherente con torneos anteriores
- Usa humor ligero y referencias al metajuego
- No menciones personas
- Máximo 3–4 párrafos
"""

    return await llamar_a_chatgpt(prompt)

async def cargar_memoria_ia(guild: discord.Guild, limite=15):
    """
    Carga la memoria histórica de análisis previos desde el canal ia-context.
    """
    canal = obtener_canal_ia(guild)
    if not canal:
        return []

    recuerdos = []
    async for msg in canal.history(limit=limite):
        recuerdos.append(msg.content)

    recuerdos.reverse()  # orden cronológico
    return recuerdos

async def guardar_memoria_ia(guild: discord.Guild, tipo: str, contenido: str):
    """
    Guarda un bloque de texto en el canal ia-context con un tipo de memoria.
    """
    canal = obtener_canal_ia(guild)
    if not canal:
        return

    texto = f"[{tipo.upper()}]\n{contenido}"
    await canal.send(texto)

def obtener_canal_ia(guild: discord.Guild):
    """
    Devuelve el canal de Discord ia-context para almacenar memoria de IA.
    """
    return discord.utils.get(guild.text_channels, name="ia-context")