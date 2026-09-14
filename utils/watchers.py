from discord.ext import tasks, commands
from datetime import datetime, timedelta, time
import discord
import re
import asyncio

from utils.torneos_estado import leer_estado, actualizar_torneo_estado, obtener_torneo_estado

from utils.torneos_api import regenerar_cache

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = None

def now():
    return datetime.now(TZ) if TZ else datetime.now()

def hoy():
    return now().date()

def log(msg: str):
    print(f"[TAREAS {now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

# -------------------------------------------------------------
# TAREAS INDIVIDUALES (sin comprobaciones de fecha)
# -------------------------------------------------------------
async def limpiar_canal_diario(bot: commands.Bot):
    guild = bot.get_guild(1381551388907016252)
    if not guild:
        return
    canal = discord.utils.get(guild.text_channels, name="preguntale-a-el-barbas")
    if not canal:
        return
    borrados = 0
    try:
        async for mensaje in canal.history(limit=None):
            if not mensaje.pinned:
                await mensaje.delete()
                borrados += 1
                await asyncio.sleep(0.3)
        log(f"limpiar_canal_diario: {borrados} mensajes borrados")
    except Exception as e:
        log(f"limpiar_canal_diario: error: {e}")

async def limpiar_partidos_pasados(bot: commands.Bot):
    total_borrados = 0
    for guild in bot.guilds:
        canal = discord.utils.get(guild.text_channels, name="partidos-agendados")
        if not canal:
            continue
        patron_fecha = re.compile(r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})")
        borrados = 0
        async for mensaje in canal.history(limit=300):
            match = patron_fecha.search(mensaje.content)
            if not match:
                continue
            try:
                fecha = datetime.strptime(match.group(1), "%d/%m/%Y").date()
                if fecha < hoy():
                    await mensaje.delete()
                    borrados += 1
                    await asyncio.sleep(0.3)
            except:
                continue
        total_borrados += borrados
    log(f"limpiar_partidos_pasados: {total_borrados} partidos eliminados")

async def limpiar_torneos_vencidos(bot: commands.Bot):
    total_borrados = 0
    for guild in bot.guilds:
        canal = discord.utils.get(guild.text_channels, name="torneos-activos")
        if not canal:
            continue
        borrados = 0
        async for mensaje in canal.history(limit=300):
            if mensaje.pinned:
                continue
            for linea in mensaje.content.splitlines():
                match = re.search(r"\d{2}/\d{2}/\d{4}", linea)
                if match:
                    try:
                        fecha = datetime.strptime(match.group(), "%d/%m/%Y").date()
                        if fecha <= hoy() - timedelta(days=2):
                            await mensaje.delete()
                            borrados += 1
                            await asyncio.sleep(0.3)
                            break
                    except:
                        continue
        total_borrados += borrados
    log(f"limpiar_torneos_vencidos: {total_borrados} torneos vencidos eliminados")

async def publicar_eventos_semanales(bot: commands.Bot):
    for guild in bot.guilds:
        canal_origen = discord.utils.get(guild.text_channels, name="partidos-agendados")
        canal_proximas = discord.utils.get(guild.text_channels, name="🎭-cartelera‐proximas-partidas")
        if not canal_origen or not canal_proximas:
            continue
        hoy_date = hoy()
        inicio_semana = hoy_date - timedelta(days=hoy_date.weekday())
        fin_semana = inicio_semana + timedelta(days=6)
        eventos = []
        patron = re.compile(r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|")
        async for mensaje in canal_origen.history(limit=300):
            if not mensaje.content.startswith("📅 [EVENTO]"):
                continue
            match = patron.search(mensaje.content)
            if not match:
                continue
            fecha_str, hora_str, j1, j2 = match.groups()
            try:
                fecha = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                if inicio_semana <= fecha <= fin_semana:
                    eventos.append((fecha, hora_str, j1.strip(), j2.strip()))
            except:
                continue
        # Buscar mensaje existente
        mensaje_existente = None
        async for msg in canal_proximas.history(limit=50):
            if msg.author == bot.user and msg.embeds:
                if msg.embeds[0].title == "📅 Partidas programadas esta semana":
                    mensaje_existente = msg
                    break
        # Crear o actualizar embed
        if not eventos:
            embed = discord.Embed(
                title="📅 Partidas programadas esta semana",
                description="⏳ No hay futuras partidas programadas por ahora.",
                color=discord.Color.dark_grey()
            )
        else:
            embed = discord.Embed(title="📅 Partidas programadas esta semana", color=discord.Color.blue())
            for fecha_ev, hora_ev, j1, j2 in sorted(eventos):
                embed.add_field(
                    name=f"{fecha_ev.strftime('%d/%m/%Y')} {hora_ev}",
                    value=f"{j1} vs {j2}",
                    inline=False
                )
        if mensaje_existente:
            await mensaje_existente.edit(embed=embed)
        else:
            await canal_proximas.send(embed=embed)
        log(f"publicar_eventos_semanales: {len(eventos)} eventos en {guild.name}")

# ============================================================
#   RECORDATORIOS DE DECK (3 días y 24h antes del torneo)
# ============================================================

async def _obtener_decks_subidos(guild):
    """Devuelve un set con los códigos de deck ya subidos (codigo_torneo_id)."""
    canal_decks = discord.utils.get(guild.text_channels, name="submitted-decks")
    decks_subidos = set()
    if not canal_decks:
        return decks_subidos

    async for msg in canal_decks.history(limit=500):
        for embed in msg.embeds:
            if embed.title and "🃏 Deck" in embed.title:
                contenido = ""
                if embed.description:
                    contenido += embed.description + "\n"
                for field in embed.fields:
                    contenido += f"{field.name}: {field.value}\n"

                for linea in contenido.splitlines():
                    if "Código:" in linea:
                        match = re.search(r'`(.+?)`', linea)
                        if match:
                            decks_subidos.add(match.group(1))
    return decks_subidos


async def _enviar_recordatorio_a_inscritos(bot, guild, codigo, nombre, dias_restantes, decks_subidos):
    """Envía el recordatorio a todos los inscritos que no hayan subido deck."""
    torneo = await obtener_torneo_estado(bot, codigo)
    if not torneo:
        return 0

    inscritos_ids = torneo.get("inscritos_ids", [])
    if not inscritos_ids:
        return 0

    if dias_restantes == 3:
        mensaje = (
            f"⏰ **¡Faltan 3 días para el torneo `{nombre}`!**\n\n"
            f"🏷️ Código: `{codigo}`\n"
            f"📅 Inicio: en 3 días\n\n"
            f"Recuerda subir tu deck antes del inicio con el comando:\n"
            f"`!subir-deck {codigo}`"
        )
    else:  # 1 día
        mensaje = (
            f"⏰ **¡Últimas 24 horas para subir tu deck!**\n\n"
            f"🏷️ Torneo: **{nombre}**\n"
            f"🆔 Código: `{codigo}`\n\n"
            f"⚠️ Todavía no has subido tu deck. Hazlo antes de que empiece con:\n"
            f"`!subir-deck {codigo}`"
        )

    enviados = 0
    for uid in inscritos_ids:
        codigo_deck = f"{codigo}_{uid}"
        if codigo_deck in decks_subidos:
            continue  # ya subió el deck

        try:
            miembro = guild.get_member(int(uid))
            if not miembro:
                miembro = await guild.fetch_member(int(uid))
            await miembro.send(mensaje)
            enviados += 1
        except discord.Forbidden:
            print(f"⚠️ No se pudo enviar recordatorio a {uid} (DMs cerrados).")
        except Exception as e:
            print(f"⚠️ Error enviando recordatorio a {uid}: {e}")

    return enviados


async def enviar_recordatorios_deck(bot: commands.Bot):
    """
    Revisa todos los torneos abiertos y envía recordatorios:
      - 3 días antes del inicio
      - 24 horas antes (1 día antes, ya que es tarea diaria)
    Solo envía a quien NO haya subido deck y no lo haya recibido ya.
    """
    guild = bot.get_guild(1381551388907016252)  # GUILD_ID_ADMISION
    if not guild:
        return

    estado = await leer_estado(bot)
    hoy = hoy()

    for torneo in estado.get("torneos", []):
        # Solo torneos en estado "abierto"
        if torneo.get("estado") != "abierto":
            continue

        fecha_str = torneo.get("fecha_inicio")
        if not fecha_str:
            continue

        try:
            fecha_inicio = datetime.strptime(fecha_str, "%d/%m/%Y").date()
        except ValueError:
            continue

        dias_restantes = (fecha_inicio - hoy).days
        codigo = torneo.get("codigo")
        nombre = torneo.get("nombre", "Torneo")

        if dias_restantes not in (3, 1):
            continue

        # Verificar flag para no reenviar
        flag = f"recordatorio_{dias_restantes}d_enviado"
        if torneo.get(flag):
            continue

        # Obtener decks ya subidos
        decks_subidos = await _obtener_decks_subidos(guild)

        # Enviar recordatorios
        enviados = await _enviar_recordatorio_a_inscritos(
            bot, guild, codigo, nombre, dias_restantes, decks_subidos
        )

        # Marcar flag
        await actualizar_torneo_estado(bot, codigo, {flag: True})

        log(f"Recordatorio {dias_restantes}d para '{nombre}' ({codigo}): enviado a {enviados} usuario(s).")

# -------------------------------------------------------------
# LOOP DIARIO (ejecución exacta a las 10:15)
# -------------------------------------------------------------
@tasks.loop(time=time(hour=10, minute=15))
async def ejecutar_tareas_diarias(bot: commands.Bot):
    await bot.wait_until_ready()
    await limpiar_canal_diario(bot)
    await limpiar_torneos_vencidos(bot)
    await limpiar_partidos_pasados(bot)
    await publicar_eventos_semanales(bot)
    await enviar_recordatorios_deck(bot)

# -------------------------------------------------------------
# INICIO (llamar una vez desde on_ready)
# -------------------------------------------------------------
def cargar_tareas(bot: commands.Bot):
    """Inicia el bucle diario de tareas."""
    ejecutar_tareas_diarias.start(bot)