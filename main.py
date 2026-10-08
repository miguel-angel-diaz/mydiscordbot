######## main.py #######
"""
Arranque del bot. Los comandos y eventos están en los Cogs de cogs/ (Admin, Jugadores, Swiss, Eventos), cada uno con
sus permisos en cog_check (utils/permisos.py); se cargan una sola vez en setup_hook, junto al servidor web y las tareas.
"""
import asyncio
import discord
from discord.ext import commands
import logging
import os

from utils import ayuda
from utils.torneos_api import iniciar_servidor_web, set_bot_instance
from utils.events import reconocer_comando_handle
from utils.watchers import cargar_tareas

# Configurar logging: un único formato para el bot y discord.py (bot.run usa log_handler=None para no duplicar)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

EXTENSIONES = ("cogs.admin", "cogs.jugadores", "cogs.swiss", "cogs.eventos")


class Bot(commands.Bot):

    async def setup_hook(self):
        """Se ejecuta UNA sola vez al arrancar, antes de conectar (on_ready se repite al reconectar)."""
        for extension in EXTENSIONES:
            await self.load_extension(extension)      # si una falla, el bot no arranca a medias
        logger.info(f"✅ {len(self.commands)} comandos cargados de {len(EXTENSIONES)} cogs")

        await iniciar_servidor_web()          # con await: si falla (p. ej. puerto ocupado) se ve en el arranque
        cargar_tareas(self)                   # el bucle espera a wait_until_ready antes de su primera ejecución

        # Caché de la web a memoria; si falta o es antigua (p. ej. tras un deploy) se regenera en segundo plano
        from utils import cache_web
        from utils.torneos_api import refrescar_cache_al_arrancar
        cache = await cache_web.cargar()
        if cache:
            logger.info(f"✅ Caché de torneos cargada: {len(cache.get('torneos', []))} torneos")
        else:
            logger.warning("⚠️ No hay caché de torneos: se generará en cuanto el bot esté listo.")
        self._tarea_cache_web = asyncio.create_task(refrescar_cache_al_arrancar(self))   # referencia: que no la recoja el GC

    async def on_ready(self):
        # Se repite en cada reconexión a Discord: aquí no se arranca nada (eso va en setup_hook)
        logger.info(f"✅ Bot conectado como {self.user}")

    async def on_message(self, message: discord.Message):
        # Sustituye al on_message por defecto: primero los atajos con espacio ("!subir deck"), luego los comandos.
        # La bienvenida del vestíbulo es un listener del cog Eventos.
        if message.author.bot:
            return
        manejado = await reconocer_comando_handle(self, message)
        if not manejado:
            await self.process_commands(message)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = Bot(
    command_prefix='!',
    intents=intents,
    case_insensitive=True
)
set_bot_instance(bot)
ayuda.registrar_bot(bot)          # la ayuda se genera desde los comandos registrados


if __name__ == "__main__":
    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

    # Si no existe en el entorno (Railway), usa config_token.py local
    if not DISCORD_TOKEN:
        try:
            from config_token import DISCORD_TOKEN
            logger.info("🔹 Usando token local desde config_token.py")
        except ImportError:
            raise ValueError("❌ No se encontró el token del bot. Configura la variable DISCORD_TOKEN o crea config_token.py.")

    bot.run(DISCORD_TOKEN, log_handler=None)
