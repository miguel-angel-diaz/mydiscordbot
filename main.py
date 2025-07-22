import discord
from discord.ext import commands

from utils.admin import aplicar_out, aplicar_strike, eliminar_mensajes, cerrar_peticion_handle
from utils.jugadores import agendar_partida_handle, eventos_hoy_handle, nueva_peticion_handle, inscribirse_handler, desinscribirse_handler, ver_inscritos_handler
from utils.torneos import nuevo_torneo

from utils.watchers import cargar_tareas;

import config
# import os
# import webserver
# DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')


intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

bot = commands.Bot(command_prefix='!', intents=intents)

################################## COMANDOS ADMINISTRADOR ###############################################

@bot.command(name="strike")
@commands.has_permissions(manage_roles=True)
async def strike(ctx, miembro: discord.Member = None):
    await aplicar_strike(ctx, miembro)

@bot.command(name="out")
@commands.has_permissions(manage_roles=True)
async def out(ctx, miembro: discord.Member = None):
    await aplicar_out(ctx, miembro)

@bot.command(name="eliminar-mensajes")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, canal: discord.TextChannel = None, cantidad: int = None):
    await eliminar_mensajes(ctx, canal, cantidad)

@bot.command(name="cerrar-peticion")
@commands.has_permissions(manage_messages=True)
async def cerrar_peticion(ctx, codigo: str = None, *, respuesta: str = None):
    await cerrar_peticion_handle(ctx, codigo, respuesta)

#########################################################################################################

@bot.command(name="nuevo-torneo")
async def new_tournament(ctx, *, args=None):
    await nuevo_torneo(ctx, args=args)

######################################### COMANDOS JUGADORES ############################################



@bot.command(name="agendar-partida")
async def agendar_partida(ctx, fecha=None, hora=None, jugador1: discord.Member = None, _vs=None, jugador2: discord.Member = None):
    await agendar_partida_handle(ctx, fecha, hora, jugador1, _vs, jugador2)

@bot.command(name="eventos-hoy")
async def eventos_hoy(ctx):
    await eventos_hoy_handle(ctx)

# @bot.command(name="partidas-pendientes")
# async def partidas_pendientes(ctx):
#     await partidas_pendientes_handle(ctx)

@bot.command(name="nueva-peticion")
async def nueva_peticion(ctx, *, descripcion: str = None):
    await nueva_peticion_handle(ctx, descripcion)

@bot.command(name="inscribirse")
async def inscribirse(ctx, codigo: str = None, usuario: discord.Member = None):
    await inscribirse_handler(ctx, codigo, usuario)

@bot.command(name="desinscribirse")
async def desinscribirse(ctx, codigo: str = None, usuario: discord.Member = None):
    await desinscribirse_handler(ctx, codigo, usuario)

@bot.command(name="ver-inscritos")
async def ver_inscritos(ctx, codigo=None):
    await ver_inscritos_handler(ctx, codigo)


#########################################################################################################

######################################### COMANDOS TORNEOS ##############################################



#########################################################################################################


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    cargar_tareas(bot)

# webserver.keep_alive()  
# bot.run(DISCORD_TOKEN)
bot.run(config.TOKEN)
