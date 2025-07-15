import discord
from discord.ext import commands

from utils.admin import aplicar_out, aplicar_strike, eliminar_mensajes, cerrar_peticion_handle
from utils.jugadores import agendar_partida_handle, eventos_hoy_handle, inscribirse_handler, ver_inscritos_handler, desinscribirse_handler, torneos_activos_handle, reportar_resultado_handle, partidas_pendientes_handle, nueva_peticion_handle
from utils.torneos import nuevo_torneo_handle, comenzar_evento_handle, mostrar_clasificacion_handle, nueva_ronda_handle
from utils.watchers import cargar_tareas;

import config


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

######################################### COMANDOS JUGADORES ############################################

@bot.command(name="inscribirse")
async def inscribirse(ctx, codigo=None):
    await inscribirse_handler(ctx, codigo)

@bot.command(name="desinscribirse")
async def desinscribirse(ctx, codigo=None):
    await desinscribirse_handler(ctx, codigo)

@bot.command(name="ver-inscritos")
async def ver_inscritos(ctx, codigo=None):
    await ver_inscritos_handler(ctx, codigo)

@bot.command(name="agendar-partida")
async def agendar_partida(ctx, fecha=None, hora=None, jugador1: discord.Member = None, _vs=None, jugador2: discord.Member = None):
    await agendar_partida_handle(ctx, fecha, hora, jugador1, _vs, jugador2)

@bot.command(name="eventos-hoy")
async def eventos_hoy(ctx):
    await eventos_hoy_handle(ctx)

@bot.command(name="partidas-pendientes")
async def partidas_pendientes(ctx):
    await partidas_pendientes_handle(ctx)

# Torneos admin
@bot.command(name="torneos-activos")
async def torneos_activos(ctx):
    await torneos_activos_handle(ctx)

@bot.command(name="reportar-resultado")
async def reportar_resultado(ctx, jugador1: discord.Member = None, resultado: str = None, jugador2: discord.Member = None, codigo=None):
    await reportar_resultado_handle(ctx, jugador1, resultado, jugador2, codigo)

@bot.command(name="nueva-peticion")
async def nueva_peticion(ctx, *, descripcion: str = None):
    await nueva_peticion_handle(ctx, descripcion)


#########################################################################################################

######################################### COMANDOS TORNEOS ##############################################

@bot.command(name="nuevo-torneo")
async def new_tournament(ctx, *, datos=None):
    await nuevo_torneo_handle(ctx, datos)

@bot.command(name="empezar-torneo")
async def start_event(ctx, codigo=None):
    await comenzar_evento_handle(ctx, codigo)

@bot.command(name="mostrar-clasificacion")
async def mostrar_clasificacion(ctx, codigo=None):
    await mostrar_clasificacion_handle(ctx, codigo)

@bot.command(name="nueva-ronda")
async def nueva_ronda(ctx, codigo=None, empatar_faltantes: int = 0):
    await nueva_ronda_handle(ctx, codigo, empatar_faltantes)


#########################################################################################################


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    cargar_tareas(bot)

# webserver.keep_alive()  
bot.run(config.TOKEN)
