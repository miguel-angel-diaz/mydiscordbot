# utils/commons.py
import logging
import asyncio
import aiohttp
import config
import discord
import json
from functools import wraps
from collections import Counter
import io
import re
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional
from types import SimpleNamespace

from difflib import get_close_matches

# ============================================================
# IMPORTACIONES DESDE torneos_estado (evitar duplicación)
# ============================================================
from utils import dm
from utils import canales
from utils.torneos_estado import leer_estado
from utils import challonge

log = logging.getLogger(__name__)

# ============================================================
# FUNCIONES DE UTILIDAD GENERAL
# ============================================================

async def borrar_mensaje_seguro(ctx):
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    except Exception as e:
        log.exception(f"Error al borrar mensaje: {e}")

async def validar_canal_correcto(ctx, canal_valido: str, comando: str):
    """
    Verifica si el comando fue usado en el canal correcto. Si no lo fue:
    - Manda un mensaje privado al autor.
    - Elimina el mensaje del canal si es posible.
    - Retorna False para indicar que no se debe continuar.
    """
    # Nombre real del comando ejecutado (el texto fijo de cada llamada a veces era incorrecto)
    if getattr(ctx, "command", None):
        comando = f"!{ctx.command.qualified_name}"

    # Por DM no hay canal con nombre: el comando debe usarse en el servidor
    nombre_canal = getattr(ctx.channel, "name", None) if ctx.guild else None
    if nombre_canal == canal_valido:
        return True

    try:
        await ctx.author.send(
            f"❌ El comando `{comando}` solo se puede usar en el canal `#{canal_valido}` del servidor.\n"
            f"Usa el comando allí para que funcione correctamente."
        )
    except discord.HTTPException:
        pass  # Usuario con DMs cerrados

    if ctx.guild:
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass  # ya borrado por borrar_mensaje_seguro (NotFound) o sin permisos

    return False

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

# ============================================================
# MIEMBROS: caché del bot primero, API solo si hace falta
# ============================================================

NO_ENCONTRADO_TTL = 600            # segundos que se recuerda que un ID no está en el servidor
_no_encontrados: Dict[int, float] = {}


async def resolver_miembro(guild, user_id) -> Optional[discord.Member]:
    """
    Miembro del servidor por ID, o None. Con el intent de miembros, get_member (sin llamar a la API) ya tiene a
    todos los presentes; fetch_member solo se intenta si no está, y un 404 se recuerda NO_ENCONTRADO_TTL segundos
    (antes, cada nombre de cada clasificación era una llamada a la API, y las de quien ya se fue fallaban siempre).
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    if guild is None:
        return None
    miembro = guild.get_member(uid)
    if miembro is not None:
        return miembro
    if _no_encontrados.get(uid, 0) > time.monotonic():
        return None
    try:
        return await guild.fetch_member(uid)
    except discord.NotFound:
        _no_encontrados[uid] = time.monotonic() + NO_ENCONTRADO_TTL
    except discord.HTTPException:
        pass                       # error puntual de Discord: no se recuerda
    return None


async def nombre_miembro(guild, user_id, por_defecto: str = None) -> str:
    """Nombre visible del miembro, o `por_defecto` ("Usuario <id>" si no se indica)."""
    miembro = await resolver_miembro(guild, user_id)
    if miembro is not None:
        return miembro.display_name
    return por_defecto if por_defecto is not None else f"Usuario {user_id}"


def buscar_usuario_en_servidor(guild, nombre_busqueda):
    """
    - Si recibe un ID numérico (llega como string del chat) → lo usa directamente.
    - Si recibe un nombre → busca en los miembros del servidor.
    - Si no encuentra nada → None.
    """
    texto = str(nombre_busqueda).strip()

    # Si son solo dígitos → es un ID de Discord
    if texto.isdigit():
        miembro = guild.get_member(int(texto))
        if miembro:
            return miembro
        # No está en el servidor → objeto ligero con id como STRING
        return SimpleNamespace(
            id=texto,
            display_name=f"Usuario {texto}",
            name=f"Usuario {texto}",
            mention=f"<@{texto}>",
            roles=[],
            bot=False,
        )

    # Búsqueda por nombre
    t = texto.lower()
    for m in guild.members:
        if m.display_name.lower() == t or m.name.lower() == t:
            return m
    for m in guild.members:
        if t in m.display_name.lower() or t in m.name.lower():
            return m

    return None
# ============================================================
# TORNEOS (Challonge legacy) - obtener torneo usuario
# ============================================================

async def obtener_torneo_usuario(ctx, mensaje_inicial: str = None, complete=False):
    """
    Devuelve el código del torneo elegido (o una lista si elige 'todos', solo con complete=True).
      - complete=False: torneos suizos activos del estado.
      - complete=True: suizos finalizados + históricos de Challonge leídos del caché de la web (sin llamar a Challonge).
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
    solo_inscritos = comando_actual not in ("ver-inscritos", "iniciar-torneo", "partidos-pendientes")

    # --- TORNEOS HISTÓRICOS DE CHALLONGE (solo consulta de resultados) ---
    # Ya no se llama a Challonge en cada comando: los torneos terminados de Challonge se leen del caché
    # de la web (cache/torneos.json, generado con !actualizar-web). Los torneos activos son solo los suizos.
    torneos_challonge = []
    if complete:
        from utils.torneos_api import leer_cache   # import local: evita ciclos
        for t in (leer_cache() or {}).get("torneos", []):
            if solo_inscritos and not any(str(p.get("discord_id")) == str(ctx.author.id) for p in t.get("clasificacion", [])):
                continue
            torneos_challonge.append((t["codigo"], t.get("nombre") or t["codigo"], "challonge"))

    # --- OBTENER TORNEOS SWISS DEL ESTADO ---
    torneos_swiss = []
    try:
        estado_swiss = await leer_estado(ctx.bot)
        for t in estado_swiss.get("torneos", []):
            if t.get("tipo") != "swiss":
                continue
            estado_t = t.get("estado")
            # Si complete=True, solo torneos finalizados
            if complete and estado_t != "finalizado":
                continue
            if not complete and estado_t == "finalizado":
                continue
            
            codigo = t.get("codigo")
            nombre = t.get("nombre", "Torneo Swiss sin nombre")
            
            # Si solo queremos torneos donde el usuario está inscrito
            if solo_inscritos:
                inscritos_ids = t.get("inscritos_ids", [])
                if str(ctx.author.id) not in inscritos_ids:
                    continue
            
            torneos_swiss.append((codigo, nombre, "swiss"))
    except Exception as e:
        log.warning(f"⚠️ Error al leer torneos Swiss en obtener_torneo_usuario: {e}")

    # --- UNIR AMBAS LISTAS ---
    torneos = torneos_challonge + torneos_swiss  # cada elemento: (codigo, nombre, tipo)

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
        for idx, (tid, nombre, tipo) in enumerate(chunk, start=start):
            emoji = numeros_emoji[idx] if idx < len(numeros_emoji) else f"{idx+1}."
            texto += f"{emoji} `{tid}` → {nombre} (tipo: {tipo.capitalize()})\n"

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

    try:
        respuesta = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=90)
        contenido = respuesta.content.strip().lower()

        # ✅ Solo aceptar "todos" si complete=True
        if complete and contenido == "todos":
            return [tid for tid, _, _ in torneos]

        # ✅ Aceptar número de torneo
        seleccion = int(contenido)
        if seleccion < 1 or seleccion > total:
            await ctx.author.send("❌ Opción no válida. Cancelo la operación.")
            return None

        elegido = torneos[seleccion - 1][0]  # devolvemos solo el código
        return elegido

    except ValueError:
        await ctx.author.send("❌ Respuesta no válida. Cancelo la operación.")
        return None
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo.")
        return None

# ============================================================
# ARQUETIPOS Y SUGERENCIAS
# ============================================================

def obtener_sugerencias_arquetipos(nombre_usuario: str, formato: str = "Premodern", max_sugerencias: int = 5):
    """
    Devuelve una lista de arquetipos similares al texto ingresado.
    El formato determina qué array de arquetipos usar (Premodern o Pauper).
    """
    formato_lower = formato.lower()
    if "pauper" in formato_lower:
        lista = config.ARQUETIPOS_PAUPER
    else:
        lista = config.ARQUETIPOS_PREMODERN

    nombres_validos = [a["nombre"] for a in lista]
    nombre_usuario = nombre_usuario.strip().lower()

    # Buscar coincidencias aproximadas
    sugerencias = get_close_matches(nombre_usuario, nombres_validos, n=max_sugerencias, cutoff=0.4)

    # Buscar coincidencias que contengan la palabra directamente
    sugerencias_extra = [n for n in nombres_validos if nombre_usuario in n.lower()]
    for s in sugerencias_extra:
        if s not in sugerencias:
            sugerencias.append(s)

    return sugerencias[:max_sugerencias]


def obtener_lista_arquetipos(formato: str = "Premodern"):
    """Lista completa de arquetipos para el formato indicado."""
    formato_lower = formato.lower()
    if "pauper" in formato_lower:
        return [a["nombre"] for a in config.ARQUETIPOS_PAUPER]
    return [a["nombre"] for a in config.ARQUETIPOS_PREMODERN]
# ============================================================
# CARTAS MÁS JUGADAS
# ============================================================

TOP_CARTAS = 20
CARTAS_BASICAS = {"mountain", "swamp", "plains", "island", "forest", "wastes"}


def torneo_de_embed_deck(embed) -> Optional[str]:
    """Código EXACTO del torneo de un embed de deck, o None si no es un deck (lector común: utils/decks.py)."""
    from utils import decks   # import local: decks importa commons
    datos = decks.leer_embed(embed)
    return datos["codigo_torneo"] if datos else None


async def ids_con_deck(guild, codigo_torneo: str) -> set:
    """IDs (str) de los jugadores con deck subido en ESE torneo (código exacto)."""
    from utils import decks
    return {d["discord_id"] for d in await decks.listar(guild, codigo_torneo=codigo_torneo) if d["discord_id"]}


async def leer_inscritos_sorteo(canal_inscritos, codigo: str) -> List[int]:
    """
    IDs inscritos en un sorteo, en orden de inscripción, a partir de las líneas "N | CÓDIGO | ID <@ID>"
    de #inscritos-sorteos. Código exacto y sin repetidos; se lee el canal entero.
    """
    ids = []
    async for msg in canal_inscritos.history(limit=None, oldest_first=True):
        partes = [p.strip() for p in msg.content.split("|")]
        if len(partes) >= 3 and partes[1] == codigo:
            uid = partes[2].split()[0] if partes[2] else ""
            if uid.isdigit() and int(uid) not in ids:
                ids.append(int(uid))
    return ids


async def sorteo_esta_activo(canal_activos, codigo: str) -> bool:
    """El sorteo figura en #sorteos-activos con su código EXACTO ("🎉 **Sorteo activo:** `S1`")."""
    async for mensaje in canal_activos.history(limit=None):
        if mensaje.content.startswith("🎉") and f"`{codigo}`" in mensaje.content:
            return True
    return False


async def enviar_en_trozos(destino, texto: str, limite: int = 1900):
    """Envía un texto largo en varios mensajes (Discord admite 2000 caracteres por mensaje), cortando entre líneas."""
    for trozo in trocear_lista(texto, limite):
        await destino.send(trozo)


async def _contar_cartas_torneo(canal, torneo: str) -> Counter:
    """Suma las cartas (sin tierras básicas) de los decks de ESE torneo (código exacto, no subcadena)."""
    contador = Counter()
    async for mensaje in canal.history(limit=None):
        for embed in mensaje.embeds:
            if torneo_de_embed_deck(embed) != torneo:
                continue
            campos = {field.name.lower(): field.value for field in embed.fields}
            for linea in leer_campo_lista(campos, "decklist").splitlines():
                try:
                    cantidad, carta = linea.strip().split(" ", 1)
                    if carta.strip().lower() in CARTAS_BASICAS:
                        continue
                    contador[carta.strip()] += int(cantidad.lower().rstrip("x"))
                except ValueError:
                    continue
    return contador


def _grafico_cartas(top: list, torneo: str) -> bytes:
    """Gráfico donut en PNG. Usa Figure (no pyplot) para poder ejecutarse en un hilo sin bloquear el bot."""
    from matplotlib.figure import Figure
    fig = Figure(figsize=(6, 6))
    ax = fig.subplots()
    ax.pie([c for _, c in top], labels=[n for n, _ in top], autopct="%1.1f%%", startangle=90,
           pctdistance=0.85, textprops={"fontsize": 10})
    ax.add_artist(matplotlib_circle((0, 0), 0.70, fc="white"))
    ax.axis("equal")
    ax.set_title(f"Top {len(top)} cartas más jugadas\nTorneo: {torneo}", fontsize=12)
    buf = io.BytesIO()
    fig.savefig(buf, format="PNG")
    return buf.getvalue()


def matplotlib_circle(*args, **kwargs):
    from matplotlib.patches import Circle
    return Circle(*args, **kwargs)


async def cartas_mas_jugadas(ctx, codigo_torneo: str = None, channel: str = None):
    """
    Top de cartas más jugadas de uno o varios torneos. Con `channel` publica el gráfico en ese canal
    (informe de !reportar-torneo) y devuelve los datos del primer torneo; si no, todo va por DM.
    """
    await borrar_mensaje_seguro(ctx)
    canal_destino = canales.get_canal(ctx.guild, channel) if channel else None
    canal = canales.get_canal(ctx.guild, canales.DECKS)
    if not canal:
        await ctx.send("❌ No encontré el canal `submitted-decks` en este servidor.")
        return None

    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📋 Por favor selecciona un torneo o 'todos' para analizarlos todos:",
            complete=True
        )
        if not codigo_torneo:
            await ctx.send("❌ No se seleccionó ningún torneo. Operación cancelada.")
            return None

    torneos_a_analizar = codigo_torneo if isinstance(codigo_torneo, list) else [codigo_torneo]
    datos_informe = None

    for torneo in torneos_a_analizar:
        contador = await _contar_cartas_torneo(canal, torneo)
        if not contador:
            await ctx.author.send(f"📭 No se encontraron decks válidos para el torneo `{torneo}`.")
            continue

        top = contador.most_common(TOP_CARTAS)
        texto = f"📊 **Cartas más jugadas en {torneo} (sin tierras básicas):**\n"
        texto += "\n".join(f"{i}. {carta} → {cant} veces" for i, (carta, cant) in enumerate(top, start=1))
        await ctx.author.send(texto)

        png = await asyncio.to_thread(_grafico_cartas, top, torneo)
        archivo = discord.File(fp=io.BytesIO(png), filename=f"cartas_mas_jugadas_{torneo}.png")
        await (canal_destino or ctx.author).send(file=archivo)

        if datos_informe is None:
            datos_informe = {"torneo": torneo, "top_cartas": top}

    return datos_informe

# ============================================================
# BEST DECKS
# ============================================================

async def _ids_clasificacion(bot, guild, codigo_torneo: str) -> List[str]:
    """
    IDs de Discord en orden de clasificación, desde los DATOS (no leyendo el texto del canal):
      - suizo: la clasificación guardada en el estado (o calculada si aún no existe);
      - Challonge (histórico): la del caché de la web o, si no está, calculada desde Challonge.
    """
    from utils.torneos_estado import leer_clasificacion, obtener_torneo_estado
    guardada = await leer_clasificacion(bot, codigo_torneo)
    if guardada and guardada.get("clasificacion"):
        return [str(p["id"]) for p in guardada["clasificacion"]]

    torneo = await obtener_torneo_estado(bot, codigo_torneo)
    if torneo and torneo.get("tipo") == "swiss":
        from utils.swiss_core import calcular_clasificacion
        return [str(p["id"]) for p in await calcular_clasificacion(bot, codigo_torneo)]
    if torneo and torneo.get("tipo") == "battle":
        from utils.battle import calcular_clasificacion_battle, leer_enfrentamientos
        return [p["id"] for p in calcular_clasificacion_battle(codigo_torneo, await leer_enfrentamientos(bot, codigo_torneo))]

    from utils.torneos_api import leer_cache
    cache = leer_cache() or {}
    torneo_cache = next((t for t in cache.get("torneos", []) if t.get("codigo") == codigo_torneo), None)
    clasificacion = (torneo_cache or {}).get("clasificacion") or await calcular_clasificacion_torneo(guild, codigo_torneo)
    return [str(p["discord_id"]) for p in clasificacion if p.get("discord_id")]


async def best_decks_handle(ctx, codigo_torneo: str = None, channel: str = None):
    """
    Decks del TOP 4 y del último clasificado ("cuchara de palo") de un torneo. Con `channel` se publican en
    ese canal (informe de !reportar-torneo) y se devuelven los datos para la IA; si no, van por DM.
    """
    await borrar_mensaje_seguro(ctx)
    author = ctx.author
    canal_destino = canales.get_canal(ctx.guild, channel) if channel else None

    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 No escribiste el código del torneo.\n"
                            "Elige uno de los torneos en los que estás inscrito:",
            complete=True
        )
        if not codigo_torneo:
            return None
    if isinstance(codigo_torneo, list):
        await author.send("❌ Elige un torneo concreto para ver sus mejores decks.")
        return None

    try:
        ids = await _ids_clasificacion(ctx.bot, ctx.guild, codigo_torneo)
    except Exception as e:
        log.warning(f"⚠️ No se pudo obtener la clasificación de {codigo_torneo}: {e}")
        ids = []
    if not ids:
        await author.send(f"❌ No encontré clasificación para `{codigo_torneo}`.")
        return None

    hay_cuchara = len(ids) > 4
    seleccionados = ids[:4] + ([ids[-1]] if hay_cuchara else [])

    await author.send(f"📊 **Best Decks – `{codigo_torneo}`**\nTOP 4" + (" + último clasificado" if hay_cuchara else ""))
    ranking = []
    for idx, jugador_id in enumerate(seleccionados):
        deck = await obtener_deck_en_canal(ctx.guild, f"{codigo_torneo}_{jugador_id}")
        if not deck:
            await author.send(f"⚠️ No encontré deck para <@{jugador_id}>.")
            continue

        pos = "cuchara de palo" if hay_cuchara and idx == len(seleccionados) - 1 else idx + 1
        ranking.append({"pos": pos, "archetype": deck["archetype"] or "Desconocido"})

        miembro = ctx.guild.get_member(int(jugador_id))
        nombre = miembro.display_name if miembro else str(jugador_id)
        embed_final = discord.Embed(title=f"🃏 Deck – {nombre}", color=discord.Color.blue())
        embed_final.add_field(name="Jugador", value=f"{nombre} (ID: {jugador_id})", inline=False)
        embed_final.add_field(name="Archetype", value=deck["archetype"] or "No especificado", inline=False)
        anadir_campos_lista(embed_final, "Decklist", deck["decklist"], vacio="Vacío")
        anadir_campos_lista(embed_final, "Sideboard", deck["sideboard"])
        embed_final.set_footer(text=f"Torneo {codigo_torneo} • Best Decks • Puesto: {pos}")
        await (canal_destino or author).send(embed=embed_final)

    if not ranking:
        return None
    if not canal_destino:
        await author.send("✅ Análisis de mejores decks completado.")
    return {"torneo": codigo_torneo, "ranking": ranking}

# ============================================================
# OBTENER DECK EN CANAL
# ============================================================
# ============================================================
# LISTAS DE CARTAS EN EMBEDS (límite de Discord: 1024 caracteres por campo)
# ============================================================
LIMITE_CAMPO_EMBED = 1024


def trocear_lista(texto: str, limite: int = LIMITE_CAMPO_EMBED) -> List[str]:
    """Parte una lista en trozos de como máximo `limite` caracteres, cortando siempre entre líneas."""
    trozos, actual = [], ""
    for linea in (texto or "").splitlines():
        while len(linea) > limite:                      # una línea imposible de encajar: se corta a la fuerza
            trozos.append(linea[:limite]); linea = linea[limite:]
        candidato = f"{actual}\n{linea}" if actual else linea
        if len(candidato) > limite:
            trozos.append(actual); actual = linea
        else:
            actual = candidato
    if actual:
        trozos.append(actual)
    return trozos


def anadir_campos_lista(embed: discord.Embed, nombre: str, texto: str, vacio: str = "N/A"):
    """Añade la lista completa al embed, en varios campos ("Decklist", "Decklist (2)"...) si no cabe en uno."""
    trozos = trocear_lista(texto) or [vacio]
    for i, trozo in enumerate(trozos):
        embed.add_field(name=nombre if i == 0 else f"{nombre} ({i + 1})", value=trozo, inline=False)


def leer_campo_lista(campos: dict, nombre: str) -> str:
    """Une los trozos de una lista ("Decklist", "Decklist (2)"...) a partir de {nombre_campo: valor}, sin importar mayúsculas."""
    patron = re.compile(rf"^{re.escape(nombre)}(?: \((\d+)\))?$", re.IGNORECASE)
    trozos = []
    for clave, valor in campos.items():
        m = patron.match(str(clave).strip())
        if m:
            trozos.append((int(m.group(1) or 1), valor))
    return "\n".join(v for _, v in sorted(trozos, key=lambda t: t[0]))


# Nombre único del contador de ediciones en el embed del deck. Al leer se aceptan también los nombres
# antiguos ("edited", "Ediciones post-inicio") para que los decks ya subidos sigan funcionando.
CAMPO_EDICIONES = "Ediciones"
_NOMBRES_CAMPO_EDICIONES = ("ediciones", "ediciones post-inicio", "edited")


def leer_ediciones(campos: dict) -> int:
    """Número de ediciones usadas a partir de los campos del embed ({nombre: valor}); acepta "1" y "1/1"."""
    por_nombre = {str(k).strip().lower(): v for k, v in campos.items()}
    for nombre in _NOMBRES_CAMPO_EDICIONES:
        if nombre in por_nombre:
            try:
                return int(str(por_nombre[nombre]).split("/")[0].strip())
            except ValueError:
                return 0
    return 0


async def obtener_deck_en_canal(guild: discord.Guild, codigo_deck: str):
    """
    El deck con ese código exacto ("torneo_idjugador") en #submitted-decks, con su "mensaje", o None.
    Recorre el canal entero (antes solo los últimos 500 mensajes: un deck más antiguo "no existía").
    """
    from utils import decks
    return await decks.buscar(guild, codigo_deck)

# ============================================================
# IA Y ANÁLISIS
# ============================================================

async def analizar_torneo_con_ia(ctx, cartas_data, decks_data):
    if not config.OPENROUTER_API_KEY:
        await ctx.send("⚠️ El análisis con IA no está configurado (falta OPENROUTER_API_KEY). "
                       "Las cartas y los mejores decks ya se han publicado.")
        return
    memoria = await cargar_memoria_ia(ctx.guild, limite=10)
    analisis = await generar_analisis_ia(cartas_data, decks_data, memoria)
    if not analisis or analisis.strip() == "":
        await ctx.send("⚠️ La IA no devolvió contenido.")
        return
    await publicar_en_discord(ctx, analisis)
    await guardar_memoria_ia(ctx.guild, "ANALYSIS", analisis)

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

async def llamar_a_openrouter(prompt: str):
    if not config.OPENROUTER_API_KEY:
        log.warning("⚠️ Análisis con IA pedido sin OPENROUTER_API_KEY configurada.")
        return None
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
                log.error(f"❌ OpenRouter respondió {resp.status}: {(await resp.text())[:500]}")
                return None
            data = await resp.json()
            try:
                return data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, TypeError, AttributeError):
                log.error(f"❌ Respuesta inesperada de OpenRouter: {str(data)[:500]}")
                return None

async def publicar_en_discord(ctx, texto):
    canal = canales.get_canal(ctx.guild, canales.ANALISIS_TORNEOS)
    destino = canal or ctx
    bloques = dividir_texto_inteligente(texto, 1000)
    for bloque in bloques:
        await destino.send(bloque)

async def guardar_memoria_ia(guild, tipo, contenido):
    canal = canales.get_canal(guild, canales.IA_CONTEXTO)
    if not canal:
        return
    texto = f"[{tipo}]\n{contenido}\n" + "-"*50
    bloques = dividir_texto_inteligente(texto, 1000)
    for bloque in bloques:
        await canal.send(bloque)

async def cargar_memoria_ia(guild, limite=10):
    canal = canales.get_canal(guild, canales.IA_CONTEXTO)
    if not canal:
        return []
    recuerdos = []
    async for msg in canal.history(limit=limite):
        recuerdos.append(msg.content)
    recuerdos.reverse()
    return recuerdos

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

# ============================================================
# CLASIFICACIÓN (Challonge legacy)
# ============================================================


def _resultado_challonge(scores_csv: str):
    """'2-1' -> (2, 1); varias partidas '1-0,0-1,1-0' -> (2, 1). None si no se puede leer."""
    a = b = 0
    try:
        for parte in (scores_csv or "").replace(" ", "").split(","):
            s1, s2 = parte.split("-")
            a, b = a + int(s1), b + int(s2)
    except ValueError:
        return None
    return a, b


def rondas_desde_challonge(matches_raw: list) -> List[dict]:
    """Convierte los partidos completados de Challonge al formato de rondas del suizo."""
    por_ronda = {}
    for m in matches_raw:
        match = m.get("match", {})
        if match.get("state") != "complete":
            continue
        p1, p2 = match.get("player1_id"), match.get("player2_id")
        emps = por_ronda.setdefault(match.get("round"), [])
        if p1 and not p2 or p2 and not p1:                       # BYE
            emps.append({"j1": str(p1 or p2), "j2": None, "resultado": "BYE"})
            continue
        res = _resultado_challonge(match.get("scores_csv"))
        if res is None:
            continue
        emps.append({"j1": str(p1), "j2": str(p2), "resultado": f"{res[0]}-{res[1]}"})
    return [{"numero": r, "emparejamientos": e} for r, e in sorted(por_ronda.items(), key=lambda x: (x[0] is None, x[0]))]


async def calcular_clasificacion_torneo(guild, codigo_torneo: str):
    """
    Clasificación de un torneo de Challonge (solo consulta de resultados), con las MISMAS reglas que el
    suizo propio (calcular_estadisticas: MTR, mínimo 33 %, BYE como ronda y no como rival) para que la web
    muestre todas las clasificaciones igual. El nombre de cada participante en Challonge es su ID de Discord.
    Lanza challonge.ErrorChallonge si Challonge no responde.
    """
    participantes_raw, matches_raw = await challonge.participantes_y_partidos(codigo_torneo)
    return clasificacion_desde_challonge(guild, codigo_torneo, participantes_raw, matches_raw)


def clasificacion_desde_challonge(guild, codigo_torneo: str, participantes_raw: list, matches_raw: list):
    """Clasificación a partir de los datos ya descargados de Challonge (sin llamadas a la API)."""
    from utils.swiss_core import calcular_estadisticas, _desempate_final   # import local: evita ciclos

    nombres = {str(p["participant"]["id"]): p["participant"].get("name", "") for p in participantes_raw}
    stats = calcular_estadisticas(rondas_desde_challonge(matches_raw), list(nombres))

    clasificacion = []
    for pid, datos in stats.items():
        if pid not in nombres:
            continue
        nombre_challonge = nombres[pid]
        miembro = guild.get_member(int(nombre_challonge)) if str(nombre_challonge).isdigit() else None
        clasificacion.append({
            "nombre": miembro.display_name if miembro else nombre_challonge,
            "avatar": str(miembro.display_avatar.url) if miembro else None,
            "discord_id": str(miembro.id) if miembro else None,     # nunca se arrastra el de otro jugador
            "mp": datos["mp"],
            "omw": round(datos["omw"], 3),
            "buchholz": round(datos["bch"], 5),
            "diff": datos["dif"],
            "wins": datos["w"],
            "losses": datos["l"],
            "draws": datos["dw"],
            "_pid": pid,
        })

    clasificacion.sort(key=lambda x: (-x["mp"], -x["omw"], -x["diff"], -x["buchholz"],
                                      _desempate_final(codigo_torneo, x["_pid"])))
    for i, p in enumerate(clasificacion, 1):
        p["rank"] = i
        del p["_pid"]
    return clasificacion

# ============================================================
# CÓDIGOS DE TORNEO EN TEXTO (un único parser para todo el bot)
# ============================================================

# "🏷️ **Código:** `abc`" (anuncios de #torneos-activos, decks...). Los códigos son [A-Za-z0-9] (ver validacion_web).
PATRON_CODIGO_ETIQUETADO = re.compile(r"Código:\**\s*`([^`]+)`", re.IGNORECASE)
_PATRON_EMPAREJAMIENTOS = re.compile(r"Emparejamientos Ronda (\d+) - Torneo ([A-Za-z0-9]+)")


def codigo_etiquetado(texto: str) -> Optional[str]:
    """Código que sigue a "Código:" entre backticks, o None."""
    m = PATRON_CODIGO_ETIQUETADO.search(texto or "")
    return m.group(1).strip() if m else None


def cabecera_emparejamientos(codigo: str, ronda: int) -> str:
    """Primera línea del mensaje de emparejamientos de una ronda en #🍸-citas‐a‐ciegas."""
    return f"📢 **Emparejamientos Ronda {ronda} - Torneo {codigo}**"


def es_mensaje_emparejamientos(texto: str, codigo: str, ronda: int = None) -> bool:
    """
    ¿Es el mensaje de emparejamientos de ESE torneo (y de esa ronda, si se indica)? Compara el código EXACTO:
    antes se buscaba "Torneo abc" como subcadena y también casaba con el torneo "abc1".
    """
    m = _PATRON_EMPAREJAMIENTOS.search((texto or "").split("\n", 1)[0])
    return bool(m) and m.group(2) == codigo and (ronda is None or int(m.group(1)) == int(ronda))


# ============================================================
# VALIDACIÓN DE TORNEO PARA EDICIÓN DE DECK
# ============================================================

def _inicio_torneo(fecha_str: str):
    """Medianoche (hora de Madrid) del día de inicio, o None si la fecha no es válida."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Madrid")
    except Exception:
        tz = timezone.utc
    try:
        return datetime.strptime(fecha_str.strip(), "%d/%m/%Y").replace(tzinfo=tz)
    except (ValueError, AttributeError):
        return None


# Motivos que devuelve comprobar_edicion_deck
EDICION_NO_EXISTE = "no_existe"
EDICION_NO_INSCRITO = "no_inscrito"
EDICION_FINALIZADO = "finalizado"
EDICION_EMPEZADO = "empezado"
EDICION_ABIERTO = "abierto"


async def comprobar_edicion_deck(codigo_torneo: str, author: discord.Member, bot=None):
    """
    Situación del torneo para subir/editar un deck. Devuelve (motivo, mensaje), con motivo uno de
    EDICION_NO_EXISTE, EDICION_NO_INSCRITO, EDICION_FINALIZADO, EDICION_EMPEZADO o EDICION_ABIERTO.
    Fuente: el estado del bot (estado y fecha_inicio).
    """
    if bot is None:
        bot = author._state._get_client()

    estado = await leer_estado(bot)
    torneo_estado = next((t for t in estado.get("torneos", []) if t.get("codigo") == codigo_torneo), None)
    if not torneo_estado:
        return EDICION_NO_EXISTE, f"❌ El torneo `{codigo_torneo}` no está activo o no existe en el estado."

    if str(author.id) not in torneo_estado.get("inscritos_ids", []):
        return EDICION_NO_INSCRITO, f"❌ No estás inscrito en el torneo `{codigo_torneo}`."

    if torneo_estado.get("estado") == "finalizado":
        return EDICION_FINALIZADO, "❌ El torneo ya ha finalizado."
    if torneo_estado.get("estado") == "en desarrollo":
        return EDICION_EMPEZADO, "❌ El torneo ya comenzó."

    fecha_inicio_str = torneo_estado.get("fecha_inicio")
    if not fecha_inicio_str:
        return EDICION_ABIERTO, "✅ Sin fecha de inicio configurada. Edición permitida."

    inicio = _inicio_torneo(fecha_inicio_str)
    if inicio is None:
        log.warning(f"⚠️ Fecha de inicio no válida en {codigo_torneo}: {fecha_inicio_str!r}")
        return EDICION_ABIERTO, "⚠️ No se pudo verificar la fecha de inicio. Edición permitida con precaución."

    segundos_restantes = inicio.timestamp() - time.time()
    if segundos_restantes <= 0:
        return EDICION_EMPEZADO, f"❌ El torneo ya comenzó (inicio: {fecha_inicio_str})."
    return EDICION_ABIERTO, f"✅ El torneo comienza en {segundos_restantes / 3600:.1f} horas."


async def validar_torneo_para_edicion(codigo_torneo: str, author: discord.Member, bot=None):
    """(True, mensaje) solo si está inscrito y el torneo aún no ha empezado; si no, (False, mensaje)."""
    motivo, mensaje = await comprobar_edicion_deck(codigo_torneo, author, bot)
    return motivo == EDICION_ABIERTO, mensaje

# ============================================================
# DECKS: LIMPIEZA Y CONTEO
# ============================================================

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

# ============================================================
# ESTADO DE TORNEOS PARA USUARIO (web)
# ============================================================
async def obtener_estado_torneos_usuario(guild, member: discord.Member):
    bot = guild._state._get_client()
    estado = await leer_estado(bot) 
    torneos_estado = estado.get("torneos", []) 

    hoy = datetime.now().date()
    resultado = []

    decks_usuario = await obtener_decks_por_usuario(guild, str(member.id), include_message=False)
    decks_por_torneo = {d["codigo_torneo"]: d for d in decks_usuario if d.get("codigo_torneo")}

    for t in torneos_estado:
        codigo = t.get("codigo")
        if not codigo:
            continue

        # --- FILTROS ---
        # 1. Estado: solo 'abierto'
        estado_torneo = t.get("estado", "abierto")
        if estado_torneo != "abierto":
            continue

        # 2. Fecha: si tiene fecha, debe ser >= hoy
        fecha_str = t.get("fecha_inicio")
        if fecha_str:
            try:
                fecha_inicio = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                if fecha_inicio < hoy:
                    continue  # Si la fecha ya pasó, no se muestra
            except ValueError:
                # Si no se puede parsear, asumimos que es hoy (no filtrar)
                pass

        # --- Obtener datos ---
        nivel = t.get("nivel", "todos")
        if not isinstance(nivel, str):
            nivel = str(nivel)
        nivel = nivel.lower()

        roles_permitidos = config.ROLES_SOCIOS if nivel == "socios" else config.ROLES_TODOS
        if not tiene_rol_permitido(member, roles_permitidos):
            continue

        inscritos_ids = t.get("inscritos_ids", [])
        total_inscritos = len(inscritos_ids)

        total_maximo = t.get("total_maximo")
        if total_maximo is not None:
            try:
                total_maximo = int(total_maximo)
            except (ValueError, TypeError):
                total_maximo = None

        plazas_restantes = total_maximo - total_inscritos if total_maximo is not None else None

        deck = decks_por_torneo.get(codigo)

        resultado.append({
            "codigo": codigo,
            "nivel": nivel.capitalize(),
            "inscrito": str(member.id) in inscritos_ids,
            "total_inscritos": total_inscritos,
            "total_maximo": total_maximo,
            "plazas_restantes": plazas_restantes,
            "deck_subido": bool(deck),
            "deck_nombre": deck["nombre_deck"] if deck else None,
            "estado": estado_torneo,
            "fecha_inicio": fecha_str if fecha_str else "Sin fecha"
        })

    return resultado

async def obtener_decks_por_usuario(guild, discord_id: str, limite: int = None, include_message: bool = False):
    """Decks de un jugador (canal entero). Sin include_message se quita el mensaje (la web los serializa a JSON)."""
    from utils import decks
    lista = await decks.listar(guild, jugador_id=discord_id)
    if not include_message:
        for d in lista:
            d.pop("mensaje", None)
            d.pop("_mensaje", None)
    return lista

# ============================================================
# INSCRIPCIÓN WEB (soporta Swiss y Challonge)
# ============================================================

async def inscribir_usuario_web(guild, member: discord.Member, codigo_torneo: str):
    """Inscribe al usuario desde la web en un torneo suizo (la gestión por Challonge ya no existe)."""
    from utils.swiss_core import inscribir_jugador  # Import local para evitar ciclo

    bot = guild._state._get_client()
    estado = await leer_estado(bot)
    torneo = next((t for t in estado.get("torneos", []) if t.get("codigo") == codigo_torneo), None)

    if not torneo:
        return False, "Ese torneo no está activo o no se encontró en el estado."
    if torneo.get("tipo") != "swiss":
        return False, "Las inscripciones de este torneo no se gestionan desde la web."

    return await inscribir_jugador(bot, codigo_torneo, member.id, miembro=member)

def tiene_rol_permitido(member: discord.Member, roles_permitidos: set):
    return any(role.name in roles_permitidos for role in member.roles)


_locks_edicion_deck = {}   # codigo_deck -> asyncio.Lock (evita dos ediciones simultáneas del mismo deck)


def lock_edicion_deck(codigo_deck: str) -> asyncio.Lock:
    """Lock compartido por la web y por !editar-deck: la regla de una sola edición se comprueba y aplica dentro."""
    return _locks_edicion_deck.setdefault(codigo_deck, asyncio.Lock())


async def editar_deck_web(guild, member: discord.Member, codigo_torneo: str, formato: str,
                          nombre_deck: str, archetype: str, decklist: str, sideboard: str):
    codigo_deck = f"{codigo_torneo}_{member.id}"
    async with lock_edicion_deck(codigo_deck):
        return await _editar_deck_web(guild, member, codigo_torneo, codigo_deck, formato,
                                      nombre_deck, archetype, decklist, sideboard)


async def _editar_deck_web(guild, member, codigo_torneo, codigo_deck, formato,
                           nombre_deck, archetype, decklist, sideboard):
    from utils import decks
    # Misma regla que !editar-deck: una única edición, también con el torneo empezado,
    # pero nunca sin estar inscrito ni en un torneo inexistente o finalizado
    motivo, mensaje_validacion = await comprobar_edicion_deck(codigo_torneo, member)
    if motivo in (EDICION_NO_EXISTE, EDICION_NO_INSCRITO, EDICION_FINALIZADO):
        return False, mensaje_validacion.lstrip("❌ ")

    deck_actual = await obtener_deck_en_canal(guild, codigo_deck)
    if not deck_actual:
        return False, "No se encontró tu deck para este torneo. Debes subirlo primero."

    edited_actual = deck_actual.get("edited", 0)

    # 🔒 BLOQUEO GLOBAL: Si ya editó una vez, no puede volver a editar (sin importar el estado)
    if edited_actual >= 1:
        return False, (
            "No puedes editar tu deck: ya usaste tu única edición disponible (1/1).\n"
            f"{mensaje_validacion}"
        )

    embed_final = decks.construir_embed(codigo_torneo, member, nombre_deck, formato, archetype, decklist, sideboard,
                                        ediciones=edited_actual + 1, actualizado=True, via_web=True)
    try:
        await deck_actual["mensaje"].edit(embed=embed_final)
    except discord.NotFound:
        return False, "No se pudo actualizar el deck (el mensaje original ya no existe). Contacta con un administrador."
    except discord.Forbidden:
        return False, "No tengo permisos para editar el mensaje del deck."

    return True, "✅ Deck actualizado correctamente. Has usado tu única edición disponible."

def tiene_rol_permitido(member: discord.Member, roles_permitidos: set):
    return any(role.name in roles_permitidos for role in member.roles)
