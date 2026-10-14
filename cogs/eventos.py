######## cogs/eventos.py #######
"""Eventos del servidor (bienvenida, mensajes borrados, socios, salidas, voz), registro y errores de comandos, y la ayuda."""
import logging

import discord
from discord.ext import commands

from utils import barbas, canales
from utils.permisos import CogConRoles
from utils.jugadores import mis_comandos_handle
from utils.events import (
    registrar_mensaje_borrado_handle,
    bienvenida_y_comandos_handle,
    evento_socio_handle,
    usuario_salio_handle,
    log_comando_handle,
    member_join_handle,
    PREFIJO
)

logger = logging.getLogger(__name__)


def _en_el_barbas(message: discord.Message) -> bool:
    """Mensaje de alguien que no es admin en #preguntale-a-el-barbas (los admins pueden escribir avisos ahí)."""
    return (message.guild is not None and getattr(message.channel, "name", None) == canales.COMANDOS
            and isinstance(message.author, discord.Member) and not message.author.guild_permissions.administrator)


def _es_texto_libre_en_el_barbas(message: discord.Message) -> bool:
    return _en_el_barbas(message) and not message.content.lstrip().startswith(PREFIJO)


async def _avisar_usuario(ctx, texto: str):
    try:
        await ctx.author.send(texto)
    except discord.HTTPException:
        pass


class Eventos(CogConRoles):
    roles_permitidos = None     # la ayuda la puede pedir cualquiera

    @commands.command(name="mis-comandos",
        aliases=["mis comandos", "mis_comandos", "comandos", "comandios", "comandiox"])
    async def mis_comandos(self, ctx):
        await mis_comandos_handle(ctx)

    ################################## EVENTOS DEL SERVIDOR ##################################

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Los comandos los enruta Bot.on_message (main.py); aquí solo la presentación en el vestíbulo
        if message.author.bot:
            return
        if _es_texto_libre_en_el_barbas(message):
            await barbas.atender(self.bot, message)
            return
        await bienvenida_y_comandos_handle(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        await registrar_mensaje_borrado_handle(message)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        await evento_socio_handle(before, after)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await usuario_salio_handle(self.bot, member)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await member_join_handle(member, before, after)

    ################################## REGISTRO DE COMANDOS ##################################

    @commands.Cog.listener()
    async def on_command(self, ctx):
        await log_comando_handle(
            self.bot,
            usuario=ctx.author,
            comando=ctx.command.name if ctx.command else "desconocido",
            tipo="correcto",
            fecha=ctx.message.created_at
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        original = getattr(error, "original", error)
        uso = f"`!{ctx.command.qualified_name} {ctx.command.signature}`".replace(" `", "`") if ctx.command else ""

        if isinstance(error, commands.CommandNotFound):
            tipo = "no_encontrado"
            if _en_el_barbas(ctx.message):
                await barbas.atender(self.bot, ctx.message)     # "!agendar" → "¿querías !agendar-partida?"
        elif isinstance(error, commands.UserInputError):
            # Faltan o fallan argumentos, comillas sin cerrar, argumentos de más...: error de quien escribe, no del bot
            tipo = "argumento_faltante"
            await _avisar_usuario(ctx, f"⚠️ Faltan datos o no son válidos ({error}).\nUso: {uso}")
        elif isinstance(error, commands.NoPrivateMessage):
            tipo = "error"
            await _avisar_usuario(ctx, "❌ Este comando solo se puede usar en el servidor.")
        elif isinstance(error, commands.MissingPermissions):
            tipo = "error"
            await _avisar_usuario(ctx, "❌ Necesitas permisos de administrador para usar este comando.")
        elif isinstance(error, commands.CheckFailure):
            tipo = "error"   # el cog_check (utils/permisos.py) ya avisó al usuario por DM
        else:
            tipo = "error"
            nombre = ctx.command.qualified_name if ctx.command else ctx.message.content
            logger.error("Error ejecutando %s", nombre, exc_info=(type(original), original, original.__traceback__))
            await _avisar_usuario(ctx, "❌ Ha ocurrido un error inesperado al ejecutar el comando. Ya ha quedado registrado.")

        try:
            await log_comando_handle(
                self.bot,
                usuario=ctx.author,
                comando=ctx.message.content,
                tipo=tipo,
                error=original,
                fecha=ctx.message.created_at
            )
        except Exception:
            logger.exception("No se pudo registrar el error del comando en el canal de logs")


async def setup(bot: commands.Bot):
    await bot.add_cog(Eventos(bot))
