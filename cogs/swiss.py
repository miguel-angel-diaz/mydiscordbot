######## cogs/swiss.py #######
"""
Comandos del torneo suizo. Inscribirse, reportar y ver la clasificación son para los jugadores (cog_check);
los de gestión exigen el permiso de administrador de Discord (has_permissions) y van marcados con SOLO_ADMIN.
"""
from discord.ext import commands

from utils import canales
from utils.permisos import CogConRoles, SOLO_ADMIN

from utils.swiss_handle import (
    swiss_nuevo_asistente_handle,
    swiss_inscribir_asistente_handle,
    swiss_desinscribir_asistente_handle,
    swiss_iniciar_asistente_handle,
    swiss_reportar_asistente_handle,
    swiss_modificar_resultado_asistente_handle,
    swiss_clasificacion_asistente_handle,
    swiss_siguiente_ronda_asistente_handle,
    swiss_eliminar_asistente_handle,
    swiss_reiniciar_asistente_handle,
    swiss_eliminar_ronda_asistente_handle,
    swiss_finalizar_asistente_handle
)

solo_admin = commands.has_permissions(administrator=True)


class Swiss(CogConRoles):
    roles_permitidos = tuple(canales.ROLES_JUGADORES)

    ################################## JUGADORES ##################################

    @commands.command(name="inscribir-swiss", aliases=["inscribir swiss", "inscribir_swiss", "inscribirse", "inscribir"])
    async def inscribir_swiss(self, ctx):
        await swiss_inscribir_asistente_handle(ctx)

    @commands.command(name="desinscribir-swiss", aliases=["desinscribir swiss", "desinscribir_swiss", "desinscribirse", "desinscribir"])
    async def desinscribir_swiss(self, ctx):
        await swiss_desinscribir_asistente_handle(ctx)

    @commands.command(name="reportar-swiss", aliases=["reportar resultado", "reportar_resultado", "reportar-resultado"])
    async def reportar_swiss(self, ctx):
        await swiss_reportar_asistente_handle(ctx)

    @commands.command(name="clasificacion-swiss")
    async def clasificacion_swiss(self, ctx):
        await swiss_clasificacion_asistente_handle(ctx)

    ################################## ADMINISTRADOR ##################################

    @commands.command(name="nuevo-swiss", aliases=["nuevo torneo", "nuevo_torneo", "nuevo-torneo"], extras=SOLO_ADMIN)
    @solo_admin
    async def nuevo_swiss(self, ctx):
        await swiss_nuevo_asistente_handle(ctx)

    @commands.command(name="iniciar-swiss", aliases=["iniciar torneo", "iniciar_torneo", "iniciar-torneo"], extras=SOLO_ADMIN)
    @solo_admin
    async def iniciar_swiss(self, ctx):
        await swiss_iniciar_asistente_handle(ctx)

    @commands.command(name="reiniciar-swiss", aliases=["reiniciar torneo", "reiniciar_torneo", "reiniciar-torneo"], extras=SOLO_ADMIN)
    @solo_admin
    async def reiniciar_swiss(self, ctx):
        await swiss_reiniciar_asistente_handle(ctx)

    @commands.command(name="modificar-resultado-swiss",
        aliases=["modificar resultado swiss", "modificar_resultado_swiss", "modificar-resultado", "modificar resultado", "modificar_resultado"],
        extras=SOLO_ADMIN)
    @solo_admin
    async def modificar_resultado_swiss(self, ctx):
        await swiss_modificar_resultado_asistente_handle(ctx)

    @commands.command(name="siguiente-ronda-swiss", extras=SOLO_ADMIN)
    @solo_admin
    async def siguiente_ronda_swiss(self, ctx):
        await swiss_siguiente_ronda_asistente_handle(ctx)

    @commands.command(name="eliminar-swiss", aliases=["eliminar torneo", "eliminar_torneo", "eliminar-torneo"], extras=SOLO_ADMIN)
    @solo_admin
    async def eliminar_swiss(self, ctx):
        await swiss_eliminar_asistente_handle(ctx)

    @commands.command(name="eliminar-ronda-swiss", extras=SOLO_ADMIN)
    @solo_admin
    async def eliminar_ronda_swiss(self, ctx):
        await swiss_eliminar_ronda_asistente_handle(ctx)

    @commands.command(name="finalizar-swiss", extras=SOLO_ADMIN)
    @solo_admin
    async def finalizar_swiss(self, ctx):
        await swiss_finalizar_asistente_handle(ctx)


async def setup(bot: commands.Bot):
    await bot.add_cog(Swiss(bot))
