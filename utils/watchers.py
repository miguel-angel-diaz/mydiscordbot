import asyncio
import logging
import re
import traceback
from datetime import date, datetime, time, timedelta
from typing import Optional

import discord
from discord.ext import commands, tasks

import config
from utils import canales
from utils import decks
from utils.commons import resolver_miembro
from utils.torneos_estado import leer_estado, actualizar_torneo_estado, obtener_torneo_estado

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = None
    logging.getLogger(__name__).warning("⚠️ No se pudo cargar la zona horaria Europe/Madrid; se usará UTC/hora local.")

# -------------------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------------------
GUILD_ID_ADMISION = config.GUILD_ID_ADMISION      # el de la variable de entorno, como el resto del bot
HORA_TAREAS_DIARIAS = time(hour=10, minute=15, tzinfo=TZ)

CANAL_PREGUNTAS = canales.COMANDOS
CANAL_PARTIDOS = canales.AGENDA
CANAL_TORNEOS_ACTIVOS = canales.TORNEOS_ACTIVOS
CANAL_CARTELERA_PARTIDAS = canales.CARTELERA_PARTIDAS  # ojo: el guion de "cartelera‐" es U+2010
CANAL_DECKS = canales.DECKS

TITULO_EMBED_SEMANAL = "📅 Partidas programadas esta semana"
MAX_CAMPOS_EMBED = 25          # límite de Discord
DIAS_GRACIA_TORNEO = 2         # días tras el inicio antes de borrar el torneo de #torneos-activos
DIAS_RECORDATORIO = (3, 1)
PAUSA_BORRADO = 0.3            # segundos entre borrados para no saturar la API

PATRON_FECHA = re.compile(r"\d{2}/\d{2}/\d{4}")
PATRON_FECHA_EVENTO = re.compile(r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})")
PATRON_EVENTO = re.compile(
    r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
)


# -------------------------------------------------------------
# UTILIDADES
# -------------------------------------------------------------
def now() -> datetime:
    return datetime.now(TZ) if TZ else datetime.now()


def hoy() -> date:
    return now().date()


def log(msg: str):
    """Registro de las tareas diarias (la hora la pone el formato de logging de main.py)."""
    logging.getLogger(__name__).info(f"[TAREAS] {msg}")


def _parsear_fecha(texto: str) -> Optional[date]:
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None


def _canal(guild: discord.Guild, nombre: str) -> Optional[discord.TextChannel]:
    return canales.get_canal(guild, nombre)


async def _borrar(mensaje: discord.Message) -> bool:
    """Borra un mensaje sin propagar errores de Discord. Devuelve True si se borró."""
    try:
        await mensaje.delete()
        await asyncio.sleep(PAUSA_BORRADO)
        return True
    except discord.NotFound:
        return False  # ya estaba borrado
    except discord.Forbidden:
        log(f"Sin permisos para borrar mensajes en #{mensaje.channel}")
        return False
    except discord.HTTPException as e:
        log(f"Error borrando mensaje {mensaje.id} en #{mensaje.channel}: {e}")
        return False


# -------------------------------------------------------------
# TAREAS INDIVIDUALES
# -------------------------------------------------------------
async def limpiar_canal_diario(bot: commands.Bot):
    """Vacía #preguntale-a-el-barbas, respetando los mensajes fijados."""
    guild = bot.get_guild(GUILD_ID_ADMISION)
    canal = _canal(guild, CANAL_PREGUNTAS) if guild else None
    if not canal:
        return
    # purge borra en bloque los mensajes de <14 días y uno a uno los más antiguos
    borrados = await canal.purge(limit=None, check=lambda m: not m.pinned)
    log(f"limpiar_canal_diario: {len(borrados)} mensajes borrados")


async def limpiar_partidos_pasados(bot: commands.Bot):
    """Borra de #partidos-agendados los eventos con fecha anterior a hoy."""
    hoy_date = hoy()
    total = 0
    for guild in bot.guilds:
        canal = _canal(guild, CANAL_PARTIDOS)
        if not canal:
            continue
        async for mensaje in canal.history(limit=300):
            match = PATRON_FECHA_EVENTO.search(mensaje.content)
            fecha = _parsear_fecha(match.group(1)) if match else None
            if fecha and fecha < hoy_date and await _borrar(mensaje):
                total += 1
    log(f"limpiar_partidos_pasados: {total} partidos eliminados")


def _fecha_inicio_torneo(contenido: str) -> Optional[date]:
    """Fecha de inicio de un mensaje de #torneos-activos (línea 'Inicio'; si no, la primera fecha)."""
    primera = None
    for linea in contenido.splitlines():
        match = PATRON_FECHA.search(linea)
        if not match:
            continue
        fecha = _parsear_fecha(match.group())
        if not fecha:
            continue
        if "Inicio" in linea:
            return fecha
        primera = primera or fecha
    return primera


async def limpiar_torneos_vencidos(bot: commands.Bot):
    """Borra de #torneos-activos los torneos que empezaron hace DIAS_GRACIA_TORNEO días o más."""
    limite = hoy() - timedelta(days=DIAS_GRACIA_TORNEO)
    total = 0
    for guild in bot.guilds:
        canal = _canal(guild, CANAL_TORNEOS_ACTIVOS)
        if not canal:
            continue
        async for mensaje in canal.history(limit=300):
            if mensaje.pinned:
                continue
            fecha = _fecha_inicio_torneo(mensaje.content)
            if fecha and fecha <= limite and await _borrar(mensaje):
                total += 1
    log(f"limpiar_torneos_vencidos: {total} torneos vencidos eliminados")


async def _eventos_de_la_semana(canal: discord.TextChannel, inicio: date, fin: date):
    eventos = []
    async for mensaje in canal.history(limit=300):
        if not mensaje.content.startswith("📅 [EVENTO]"):
            continue
        match = PATRON_EVENTO.search(mensaje.content)
        if not match:
            continue
        fecha_str, hora, j1, j2 = match.groups()
        fecha = _parsear_fecha(fecha_str)
        if fecha and inicio <= fecha <= fin:
            eventos.append((fecha, hora, j1.strip(), j2.strip()))
    return sorted(eventos)


def _embed_semanal(eventos) -> discord.Embed:
    if not eventos:
        return discord.Embed(
            title=TITULO_EMBED_SEMANAL,
            description="⏳ No hay futuras partidas programadas por ahora.",
            color=discord.Color.dark_grey(),
        )

    embed = discord.Embed(title=TITULO_EMBED_SEMANAL, color=discord.Color.blue())
    # Si hay más eventos que campos permitidos, se reserva el último para el resumen
    visibles = eventos if len(eventos) <= MAX_CAMPOS_EMBED else eventos[:MAX_CAMPOS_EMBED - 1]
    for fecha, hora, j1, j2 in visibles:
        embed.add_field(name=f"{fecha.strftime('%d/%m/%Y')} {hora}", value=f"{j1} vs {j2}", inline=False)
    restantes = len(eventos) - len(visibles)
    if restantes:
        embed.add_field(
            name="…",
            value=f"Y {restantes} partida(s) más en `#{CANAL_PARTIDOS}`.",
            inline=False,
        )
    return embed


async def publicar_eventos_semanales(bot: commands.Bot):
    """Crea o actualiza en la cartelera el embed con las partidas de la semana actual."""
    hoy_date = hoy()
    inicio_semana = hoy_date - timedelta(days=hoy_date.weekday())
    fin_semana = inicio_semana + timedelta(days=6)

    for guild in bot.guilds:
        canal_origen = _canal(guild, CANAL_PARTIDOS)
        canal_cartelera = _canal(guild, CANAL_CARTELERA_PARTIDAS)
        if not canal_origen or not canal_cartelera:
            log(
                f"publicar_eventos_semanales: faltan canales en {guild.name} "
                f"(origen={bool(canal_origen)}, cartelera={bool(canal_cartelera)})"
            )
            continue

        eventos = await _eventos_de_la_semana(canal_origen, inicio_semana, fin_semana)
        embed = _embed_semanal(eventos)

        existente = None
        async for msg in canal_cartelera.history(limit=50):
            if msg.author == bot.user and msg.embeds and msg.embeds[0].title == TITULO_EMBED_SEMANAL:
                existente = msg
                break

        if existente:
            await existente.edit(embed=embed)
        else:
            await canal_cartelera.send(embed=embed)
        log(f"publicar_eventos_semanales: {len(eventos)} eventos en {guild.name}")


# ============================================================
#   RECORDATORIOS DE DECK (3 días y 24h antes del torneo)
# ============================================================
async def _obtener_decks_subidos(guild: discord.Guild) -> set:
    """Códigos de deck ya subidos (codigo_torneo_id), del canal entero."""
    return await decks.codigos_subidos(guild)


def _mensaje_recordatorio(codigo: str, nombre: str, dias_restantes: int) -> str:
    if dias_restantes == 3:
        return (
            f"⏰ **¡Faltan 3 días para el torneo `{nombre}`!**\n\n"
            f"🏷️ Código: `{codigo}`\n"
            f"📅 Inicio: en 3 días\n\n"
            f"Recuerda subir tu deck antes del inicio con el comando:\n"
            f"`!subir-deck {codigo}`"
        )
    return (
        f"⏰ **¡Últimas 24 horas para subir tu deck!**\n\n"
        f"🏷️ Torneo: **{nombre}**\n"
        f"🆔 Código: `{codigo}`\n\n"
        f"⚠️ Todavía no has subido tu deck. Hazlo antes de que empiece con:\n"
        f"`!subir-deck {codigo}`"
    )


async def _enviar_recordatorio_a_inscritos(bot, guild, codigo, nombre, dias_restantes, decks_subidos) -> int:
    """Envía el recordatorio por DM a los inscritos que no hayan subido deck."""
    torneo = await obtener_torneo_estado(bot, codigo)
    inscritos_ids = (torneo or {}).get("inscritos_ids", [])
    if not inscritos_ids:
        return 0

    mensaje = _mensaje_recordatorio(codigo, nombre, dias_restantes)
    enviados = 0
    for uid in inscritos_ids:
        if f"{codigo}_{uid}" in decks_subidos:
            continue  # ya subió el deck
        try:
            miembro = await resolver_miembro(guild, uid)
            if miembro is None:
                log(f"No se pudo enviar recordatorio a {uid} (ya no está en el servidor).")
                continue
            await miembro.send(mensaje)
            enviados += 1
        except discord.Forbidden:
            log(f"No se pudo enviar recordatorio a {uid} (DMs cerrados).")
        except discord.NotFound:
            log(f"No se pudo enviar recordatorio a {uid} (ya no está en el servidor).")
        except (discord.HTTPException, ValueError) as e:
            log(f"Error enviando recordatorio a {uid}: {e}")
    return enviados


async def enviar_recordatorios_deck(bot: commands.Bot):
    """
    Revisa los torneos abiertos y envía recordatorios 3 días y 1 día antes del inicio.
    Solo a quien NO haya subido deck, y una única vez por torneo y aviso (flag en el estado).
    """
    guild = bot.get_guild(GUILD_ID_ADMISION)
    if not guild:
        return

    estado = await leer_estado(bot)
    hoy_date = hoy()
    decks_subidos = None  # se carga solo si algún torneo necesita recordatorio

    for torneo in estado.get("torneos", []):
        codigo = torneo.get("codigo")
        if not codigo or torneo.get("estado") != "abierto":
            continue

        fecha_inicio = _parsear_fecha(torneo.get("fecha_inicio"))
        if not fecha_inicio:
            continue

        dias_restantes = (fecha_inicio - hoy_date).days
        if dias_restantes not in DIAS_RECORDATORIO:
            continue

        flag = f"recordatorio_{dias_restantes}d_enviado"
        if torneo.get(flag):
            continue

        if decks_subidos is None:
            decks_subidos = await _obtener_decks_subidos(guild)

        nombre = torneo.get("nombre", "Torneo")
        enviados = await _enviar_recordatorio_a_inscritos(
            bot, guild, codigo, nombre, dias_restantes, decks_subidos
        )
        await actualizar_torneo_estado(bot, codigo, {flag: True})
        log(f"Recordatorio {dias_restantes}d para '{nombre}' ({codigo}): enviado a {enviados} usuario(s).")


# -------------------------------------------------------------
# LOOP DIARIO (10:15 hora de Madrid)
# -------------------------------------------------------------
TAREAS_DIARIAS = (
    limpiar_canal_diario,
    limpiar_torneos_vencidos,
    limpiar_partidos_pasados,
    publicar_eventos_semanales,
    enviar_recordatorios_deck,
)


async def ejecutar_todas(bot: commands.Bot):
    """Ejecuta cada tarea de forma aislada: si una falla, las demás siguen y el loop no muere."""
    for tarea in TAREAS_DIARIAS:
        try:
            await tarea(bot)
        except Exception:
            log(f"❌ {tarea.__name__} falló:\n{traceback.format_exc()}")


@tasks.loop(time=HORA_TAREAS_DIARIAS)
async def ejecutar_tareas_diarias(bot: commands.Bot):
    await ejecutar_todas(bot)


@ejecutar_tareas_diarias.before_loop
async def _antes_de_tareas_diarias():
    # before_loop no recibe los argumentos de start(), así que se usa el bot guardado en cargar_tareas
    await _bot_tareas.wait_until_ready()


_bot_tareas: Optional[commands.Bot] = None


# -------------------------------------------------------------
# INICIO (seguro de llamar desde on_ready, que se repite al reconectar)
# -------------------------------------------------------------
def cargar_tareas(bot: commands.Bot):
    """Inicia el bucle diario de tareas (solo la primera vez)."""
    global _bot_tareas
    if ejecutar_tareas_diarias.is_running():
        return
    _bot_tareas = bot
    ejecutar_tareas_diarias.start(bot)
    log(f"Tareas diarias programadas a las {HORA_TAREAS_DIARIAS.strftime('%H:%M')} ({TZ or 'hora local'})")
