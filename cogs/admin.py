######## cogs/admin.py #######
"""Comandos de administración: sanciones, mensajes, peticiones, sorteos, comunicados, Battle Royale y web."""
import discord
from discord.ext import commands

from utils import canales
from utils.permisos import CogConRoles

from utils.admin import (
    aplicar_out,
    aplicar_strike,
    eliminar_mensajes,
    cerrar_peticion_handle,
    sorteo_torneo_handle,
    nuevo_sorteo_handle,
    realizar_sorteo_handle,
    nuevo_comunicado_handle,
    eliminar_decks_handle,
    actualizar_web_handle
)
from utils.torneos import tournament_report_handle
from utils.battle import (
    nuevo_battle_handle,
    iniciar_battle_handle,
    modificar_resultado_battle_handle,
    actualizar_clasificacion_battle_handle,
    finalizar_battle_handle
)


class Admin(CogConRoles):
    roles_permitidos = (canales.ROL_ADMIN,)

    @commands.command(name="strike")
    async def strike(self, ctx, miembro: discord.Member = None):
        """Aplica un strike a un miembro del servidor - !strike <usuario>"""
        await aplicar_strike(ctx, miembro)

    @commands.command(name="out")
    async def out(self, ctx, miembro: discord.Member = None):
        """aplica el rol 'Out' a un miembro del servidor - !out <usuario>"""
        await aplicar_out(ctx, miembro)

    @commands.command(name="eliminar-mensajes",
        aliases=["eliminar mensajes", "eliminar_mensajes"])
    async def clearMessajes(self, ctx, canal: discord.TextChannel = None, cantidad: int = None):
        """Elimina una cantidad específica de mensajes en un canal - !eliminar-mensajes <canal> <cantidad>"""
        await eliminar_mensajes(ctx, canal, cantidad)

    @commands.command(name="eliminar-decks",
        aliases=["eliminar decks", "eliminar_decks"])
    async def clearDecks(self, ctx, codigo: str = None):
        """Elimina los decks submiteados para un torneo - !eliminar-decks <torneo>"""
        await eliminar_decks_handle(ctx, codigo)

    @commands.command(name="cerrar-peticion",
        aliases=["cerrar peticion", "cerrar_peticion"])
    async def cerrar_peticion(self, ctx, codigo: str = None, *, respuesta: str = None):
        """Cierra una petición y envía la respuesta al usuario - !cerrar-peticion <código> <respuesta>"""
        await cerrar_peticion_handle(ctx, codigo, respuesta)

    @commands.command(name="sorteo-torneo",
        aliases=["sorteo torneo", "sorteo_torneo"])
    async def sorteo_torneo(self, ctx, codigo_torneo: str = None, *, premio: str = "Premio del sorteo"):
        """Realiza un sorteo entre los inscritos de un torneo - !sorteo-torneo <código_torneo> <premio>"""
        await sorteo_torneo_handle(ctx, codigo_torneo, premio)

    @commands.command(name="nuevo-sorteo",
        aliases=["nuevo sorteo", "nuevo_sorteo"])
    async def nuevo_sorteo(self, ctx, *, args: str = None):
        await nuevo_sorteo_handle(ctx, args=args)

    @commands.command(name="realizar-sorteo",
        aliases=["realizar sorteo", "realizar_sorteo"])
    async def realizar_sorteo(self, ctx, codigo: str = None):
        await realizar_sorteo_handle(ctx, codigo)

    @commands.command(name="nuevo-comunicado",
        aliases=["nuevo_comunicado"])
    async def nuevo_comunicado(self, ctx, *, mensaje: str = None):
        """
        Envía un comunicado al canal 📰-tablon‐anuncios
        Uso: !nuevo-comunicado <mensaje>
        """
        await nuevo_comunicado_handle(ctx, mensaje)

    ################################## BATTLE ROYALE ##################################

    @commands.command(name="nuevo-battle",
        aliases=["nuevo battle", "nuevo_battle"])
    async def nuevo_battle(self, ctx, *, nombre: str = None):
        """Crea un Battle Royale (sin Challonge) - !nuevo-battle [nombre]"""
        await nuevo_battle_handle(ctx, nombre)

    @commands.command(name="iniciar-battle",
        aliases=["iniciar battle", "iniciar_battle"])
    async def iniciar_battle(self, ctx, codigo_torneo: str = None, jugador1: discord.Member = None, jugador2: discord.Member = None):
        """Apunta un enfrentamiento en un Battle Royale (máximo 2 por pareja) - !iniciar-battle <código> @j1 @j2"""
        await iniciar_battle_handle(ctx, codigo_torneo, jugador1, jugador2)

    @commands.command(name="modificar-resultado-battle",
        aliases=["modificar resultado battle", "modificar_resultado_battle"])
    async def modificar_resultado_battle(self, ctx, codigo_torneo: str = None):
        """Corrige el resultado de un enfrentamiento de un Battle Royale - !modificar-resultado-battle <código>"""
        await modificar_resultado_battle_handle(ctx, codigo_torneo)

    @commands.command(name="actualizar-clasificacion-battle",
        aliases=["actualizar clasificacion battle", "actualizar_clasificacion_battle"])
    async def actualizar_clasificacion_battle(self, ctx, codigo_torneo: str = None):
        """Vuelve a publicar la clasificación de un battle en #🍺-el‐ranking‐de‐la‐barra - !actualizar-clasificacion-battle <código>"""
        await actualizar_clasificacion_battle_handle(ctx, codigo_torneo)

    @commands.command(name="finalizar-battle",
        aliases=["finalizar battle", "finalizar_battle"])
    async def finalizar_battle(self, ctx, codigo_torneo: str = None):
        """Cierra un Battle Royale y publica la clasificación final - !finalizar-battle <código>"""
        await finalizar_battle_handle(ctx, codigo_torneo)

    ################################## TORNEOS Y WEB ##################################

    @commands.command(name="reportar-torneo",
        aliases=["reportar torneo", "reportar_torneo"])
    async def tournament_report(self, ctx):
        await tournament_report_handle(ctx)

    @commands.command(name="actualizar-web",
        aliases=["actualizar web", "actualizar_web"])
    async def actualizar_web(self, ctx):
        await actualizar_web_handle(ctx)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
