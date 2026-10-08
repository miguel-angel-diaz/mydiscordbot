######## cogs/jugadores.py #######
"""Comandos de los jugadores: agenda, eventos, peticiones, inscritos, sorteos, decks, estadísticas y Battle Royale."""
import discord
from discord.ext import commands

from utils import canales
from utils.permisos import CogConRoles

from utils.jugadores import (
    agendar_partida_handle,
    modificar_partida_agendada_handle,
    eventos_hoy_handle,
    nueva_peticion_handle,
    ver_inscritos_handler,
    inscribirse_sorteo_handle,
    submitted_deck_handle,
    editar_deck_handle,
    cartas_mas_jugadas_handle
)
from utils.battle import reportar_resultado_battle_handle
from utils.swiss_handle import swiss_partidos_pendientes_handle
from utils.commons import best_decks_handle


class Jugadores(CogConRoles):
    roles_permitidos = tuple(canales.ROLES_JUGADORES)

    @commands.command(name="agendar-partida",
        aliases=["agendar partida", "agendar_partida"])
    async def agendar_partida(self, ctx, fecha=None, hora=None, jugador1: discord.Member = None, _vs=None, jugador2: discord.Member = None):
        """Agenda una partida entre dos jugadores - !agendar-partida"""
        await agendar_partida_handle(ctx, fecha, hora, jugador1, _vs, jugador2)

    @commands.command(name="modificar-agenda",
        aliases=["modificar agenda", "modificar_agenda"])
    async def modificar_agenda(self, ctx):
        """Permite modificar una partida agendada entre dos jugadores - !modificar-agenda"""
        await modificar_partida_agendada_handle(ctx)

    @commands.command(name="eventos-hoy",
        aliases=["eventos hoy", "eventos_hoy"])
    async def eventos_hoy(self, ctx):
        """Muestra los eventos programados para hoy - !eventos-hoy"""
        await eventos_hoy_handle(ctx)

    @commands.command(name="nueva-peticion",
        aliases=["nueva peticion", "nueva_peticion"])
    async def nueva_peticion(self, ctx, *, descripcion: str = None):
        """Crea una nueva petición - !nueva-peticion"""
        await nueva_peticion_handle(ctx, descripcion)

    @commands.command(name="ver-inscritos",
        aliases=["ver inscritos", "ver_inscritos"])
    async def ver_inscritos(self, ctx, codigo=None):
        """Muestra los inscritos en un torneo - !ver-inscritos"""
        await ver_inscritos_handler(ctx, codigo)

    @commands.command(name="reportar-resultado-battle",
        aliases=["reportar resultado battle", "reportar_resultado_battle"])
    async def reportar_resultado_battle(self, ctx, codigo_torneo: str = None, jugador1: discord.Member = None, resultado: str = None, jugador2: discord.Member = None):
        """Reporta el resultado de un enfrentamiento pendiente de un Battle Royale - !reportar-resultado-battle"""
        await reportar_resultado_battle_handle(ctx, codigo_torneo, jugador1, resultado, jugador2)

    @commands.command(name="partidos-pendientes",
        aliases=["partidos pendientes", "partidos_pendientes"])
    async def partidos_pendientes(self, ctx, codigo_torneo: str = None):
        """Muestra las partidas sin resultado de la ronda actual de un torneo suizo - !partidos-pendientes <código_torneo>"""
        await swiss_partidos_pendientes_handle(ctx, codigo_torneo)

    @commands.command(name="inscribirse-sorteo",
        aliases=["inscribirse sorteo", "inscribirse_sorteo"])
    async def inscribirse_sorteo(self, ctx, codigo: str = None):
        await inscribirse_sorteo_handle(ctx, codigo)

    @commands.command(name="subir-deck",
        aliases=["subir deck", "subir_deck"])
    async def subir_deck(self, ctx, codigo: str = None):
        """Comando para subir la lista que jugaras en un torneo - !subir-deck"""
        await submitted_deck_handle(ctx, codigo)

    @commands.command(name="editar-deck",
        aliases=["editar deck", "editar_deck"])
    async def editar_deck(self, ctx, codigo: str = None):
        """Permite editar la lista que has subido para jugar un torneo - !editar-deck"""
        await editar_deck_handle(ctx, codigo)

    @commands.command(name="cartas-mas-jugadas",
        aliases=["cartas mas jugadas", "cartas_mas_jugadas"])
    async def cartas_mas_jugadas(self, ctx):
        """Muestra las cartas más jugadas en los decks subidos - !cartas-mas-jugadas"""
        await cartas_mas_jugadas_handle(ctx)

    @commands.command(name="best-decks",
        aliases=["best decks", "best_decks"])
    async def best_decks(self, ctx, codigo_torneo: str = None):
        """analiza los mejores decks de un torneo"""
        await best_decks_handle(ctx, codigo_torneo)


async def setup(bot: commands.Bot):
    await bot.add_cog(Jugadores(bot))
