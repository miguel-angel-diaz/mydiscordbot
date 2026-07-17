######## watchers.py #######

from discord.ext import tasks, commands
from datetime import datetime, timedelta, date, time as dtime
import discord
import re
import asyncio

from utils.torneos_api import iniciar_servidor_web, regenerar_cache

try:
    # Ajusta a tu zona horaria si quieres control exacto
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = None  # usa hora local del sistema

# ==============================
#   ESTADO / GUARDAS DIARIAS
# ==============================
ultima_ejecucion_eventos: date | None = None
ultima_ejecucion_partidos: date | None = None
ultima_ejecucion_torneos_vencidos: date | None = None
ultima_ejecucion_canal_diario: date | None = None
ultima_ejecucion_global: date | None = None  # guarda global para el disparo único

_scheduler_started = False  # evitar dobles inicios

# ==============================
#   UTILIDADES
# ==============================
def now():
    return datetime.now(TZ) if TZ else datetime.now()

def hoy():
    return now().date()

def log(msg: str):
    print(f"[TAREAS {now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

async def contar_historial(canal: discord.TextChannel, limite=None):
    """Itera para contar sin borrar: útil para traza previa."""
    n = 0
    async for _ in canal.history(limit=limite):
        n += 1
    return n

# ==============================
#   TAREAS INDIVIDUALES
# ==============================
async def limpiar_canal_diario(bot: commands.Bot):
    global ultima_ejecucion_canal_diario
    if ultima_ejecucion_canal_diario == hoy():
        return
    
    guild = bot.get_guild(1381551388907016252)
    if not guild:
        return

    canal = discord.utils.get(guild.text_channels, name="preguntale-a-el-barbas")
    if not canal:
      
        return

    borrados = 0
    vistos = 0
    try:
        async for mensaje in canal.history(limit=None):
            vistos += 1
            if not mensaje.pinned:
                try:
                    await mensaje.delete()
                    borrados += 1
                    await asyncio.sleep(0.3)  # evitar rate limits
                except Exception as e:
                    log(f"limpiar_canal_diario: error borrando mensaje {mensaje.id}: {e}")
        ultima_ejecucion_canal_diario = hoy()
    except Exception as e:
        log(f"limpiar_canal_diario: error general: {e}")


async def publicar_eventos_semanales(bot: commands.Bot):
    global ultima_ejecucion_eventos
    if ultima_ejecucion_eventos == hoy():
        return

    dia_hoy = hoy()
    ejecutados_guilds = 0

    for guild in bot.guilds:
        canal_origen = discord.utils.get(guild.text_channels, name="partidos-agendados")
        canal_proximas = discord.utils.get(guild.text_channels, name="🎭-cartelera‐proximas-partidas")

        if not canal_origen or not canal_proximas:
            continue

        inicio_semana = dia_hoy - timedelta(days=dia_hoy.weekday())
        fin_semana = inicio_semana + timedelta(days=6)

        eventos_semana = []
        patron = re.compile(
            r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
        )

        async for mensaje in canal_origen.history(limit=300):
            if not mensaje.content.startswith("📅 [EVENTO]"):
                continue
            match = patron.search(mensaje.content)
            if not match:
                continue
            fecha_str, hora_str, jugador1, jugador2 = match.groups()
            try:
                fecha_obj = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                if inicio_semana <= fecha_obj <= fin_semana:
                    eventos_semana.append((fecha_obj, hora_str, jugador1.strip(), jugador2.strip()))
            except Exception:
                continue

        # 🔹 Buscar mensaje existente (para editarlo si ya existe)
        mensaje_existente = None
        async for msg in canal_proximas.history(limit=50):
            if msg.author == bot.user and msg.embeds:
                emb = msg.embeds[0]
                if emb.title == "📅 Partidas programadas esta semana":
                    mensaje_existente = msg
                    break

        # 🔹 Si no hay eventos → mostrar mensaje informativo
        if not eventos_semana:
            embed_vacio = discord.Embed(
                title="📅 Partidas programadas esta semana",
                description="⏳ No hay futuras partidas programadas por ahora.",
                color=discord.Color.dark_grey()
            )
            if mensaje_existente:
                await mensaje_existente.edit(embed=embed_vacio)
            else:
                await canal_proximas.send(embed=embed_vacio)
            continue

        # 🔹 Crear embed con los eventos encontrados
        embed = discord.Embed(
            title="📅 Partidas programadas esta semana",
            color=discord.Color.blue()
        )
        for fecha_ev, hora_ev, j1, j2 in sorted(eventos_semana):
            embed.add_field(
                name=f"{fecha_ev.strftime('%d/%m/%Y')} {hora_ev}",
                value=f"{j1} vs {j2}",
                inline=False
            )

        # 🔹 Actualizar o crear mensaje
        if mensaje_existente:
            await mensaje_existente.edit(embed=embed)
        else:
            await canal_proximas.send(embed=embed)

        ejecutados_guilds += 1

    if ejecutados_guilds > 0:
        ultima_ejecucion_eventos = hoy()
        
async def limpiar_partidos_pasados(bot: commands.Bot):
    global ultima_ejecucion_partidos
    if ultima_ejecucion_partidos == hoy():
        return

    total_borrados = 0
    for guild in bot.guilds:
        canal_partidos = discord.utils.get(guild.text_channels, name="partidos-agendados")
        if not canal_partidos:
            continue

        patron_fecha = re.compile(r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})")
        borrados_guild = 0

        async for mensaje in canal_partidos.history(limit=300):
            match = patron_fecha.search(mensaje.content)
            if not match:
                continue
            fecha_str = match.group(1)
            try:
                fecha_mensaje = datetime.strptime(fecha_str, "%d/%m/%Y").date()
            except ValueError:
                continue

            if fecha_mensaje < hoy():
                try:
                    await mensaje.delete()
                    borrados_guild += 1
                    await asyncio.sleep(0.3)
                except (discord.Forbidden, discord.NotFound):
                    pass
                except Exception:
                    pass

        total_borrados += borrados_guild

    ultima_ejecucion_partidos = hoy()
    
async def limpiar_torneos_vencidos(bot: commands.Bot):
    global ultima_ejecucion_torneos_vencidos
    if ultima_ejecucion_torneos_vencidos == hoy():
        return

    total_borrados = 0
    for guild in bot.guilds:
        canal = discord.utils.get(guild.text_channels, name="torneos-activos")
        if not canal:
            continue

        borrados_guild = 0

        async for mensaje in canal.history(limit=300):
            if mensaje.pinned:
                continue

            for linea in mensaje.content.splitlines():
                if "Inicio" not in linea:
                    continue

                match = re.search(r"\d{2}/\d{2}/\d{4}", linea)
                if not match:
                    continue

                fecha_str = match.group()
                try:
                    fecha_torneo = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                except ValueError:
                    continue

                limite = hoy() - timedelta(days=2)
                if fecha_torneo <= limite:
                    try:
                        await mensaje.delete()
                        borrados_guild += 1
                        await asyncio.sleep(0.3)
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    except Exception:
                        pass
                    break  # ya no necesitamos mirar más líneas de este mensaje

        total_borrados += borrados_guild
    ultima_ejecucion_torneos_vencidos = hoy()

# ==============================
#   LOOP PRINCIPAL: 10:15
# ==============================
TARGET_HOUR = 10
TARGET_MINUTE = 15

@tasks.loop(minutes=1)
async def ejecutar_tareas(bot: commands.Bot):
    """
    Corre cada minuto, pero sólo ejecuta las tareas cuando
    son las 10:15 y aún no se han ejecutado hoy.
    """
    await bot.wait_until_ready()
    ahora = now()
    if ahora.hour == TARGET_HOUR and ahora.minute == TARGET_MINUTE:
        global ultima_ejecucion_global
        if ultima_ejecucion_global == hoy():
            return

        await limpiar_canal_diario(bot)
        await limpiar_torneos_vencidos(bot)
        await limpiar_partidos_pasados(bot)
        await publicar_eventos_semanales(bot)
        
        ultima_ejecucion_global = hoy()

def cargar_tareas(bot: commands.Bot):
    """
    Llamar una sola vez (ej. on_ready).
    Arranca el loop cada minuto con guardas anti-doble-ejecución.
    """
    global _scheduler_started
    if _scheduler_started:
        return
    ejecutar_tareas.start(bot)
    _scheduler_started = True
