from discord.ext import tasks, commands
from datetime import datetime, timedelta, time
import discord
import re
import asyncio

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

# -------------------------------------------------------------
# INICIO (llamar una vez desde on_ready)
# -------------------------------------------------------------
def cargar_tareas(bot: commands.Bot):
    """Inicia el bucle diario de tareas."""
    ejecutar_tareas_diarias.start(bot)