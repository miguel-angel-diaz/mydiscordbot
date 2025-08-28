import discord
from discord.ext import commands

from utils.admin import (
  aplicar_out, 
  aplicar_strike, 
  eliminar_mensajes, 
  cerrar_peticion_handle, 
  sorteo_torneo_handle, 
  nuevo_sorteo_handle, 
  realizar_sorteo_handle,
  listar_torneos_handle
)

from utils.jugadores import (
    agendar_partida_handle,
    modificar_partida_agendada_handle,
    eventos_hoy_handle,
    nueva_peticion_handle,
    inscribirse_handler,
    desinscribirse_handler,
    ver_inscritos_handler,
    reportar_resultado_handle,
    modificar_resultado_handle,
    inscribirse_sorteo_handle,
    mis_comandos_handle,
    submitted_deck_handle,
    editar_deck_handle
)

from utils.torneos import (
  iniciar_torneo_handle, 
  actualizar_clasificacion_handle, 
  partidos_pendientes_handle, 
  forzar_ronda_handle, 
  new_tournament_assistance_handle
)

from utils.events import (
  registrar_mensaje_borrado_handle, 
  bienvenida_y_comandos_handle, 
  evento_socio_handle, 
  usuario_salio_handle
)

from utils.watchers import cargar_tareas;

import config
import os
import webserver
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')


intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

bot = commands.Bot(command_prefix='!', intents=intents)

def comando_roles_permitidos(*roles):
    def decorator(func):
        setattr(func, "roles_permitidos", roles)
        return func
    return decorator

################################## COMANDOS ADMINISTRADOR ###############################################

@bot.command(name="strike")
@comando_roles_permitidos("admin")
async def strike(ctx, miembro: discord.Member = None):
    """Aplica un strike a un miembro del servidor - !strike <usuario>"""
    await aplicar_strike(ctx, miembro)

@bot.command(name="out")
@comando_roles_permitidos("admin")
async def out(ctx, miembro: discord.Member = None):
    """aplica el rol 'Out' a un miembro del servidor - !out <usuario>"""
    await aplicar_out(ctx, miembro)

@bot.command(name="eliminar-mensajes")
@comando_roles_permitidos("admin")
async def clear(ctx, canal: discord.TextChannel = None, cantidad: int = None):
    """Elimina una cantidad específica de mensajes en un canal - !eliminar-mensajes <canal> <cantidad>"""
    await eliminar_mensajes(ctx, canal, cantidad)

@bot.command(name="cerrar-peticion")
@comando_roles_permitidos("admin")
async def cerrar_peticion(ctx, codigo: str = None, *, respuesta: str = None):
    """Cierra una petición y envía la respuesta al usuario - !cerrar-peticion <código> <respuesta>"""
    await cerrar_peticion_handle(ctx, codigo, respuesta)

@bot.command(name="sorteo-torneo")
@comando_roles_permitidos("admin")
async def sorteo_torneo(ctx, codigo_torneo: str, *, premio: str = "Premio del sorteo"):
    """Realiza un sorteo entre los inscritos de un torneo - !sorteo-torneo <código_torneo> <premio>"""
    await sorteo_torneo_handle(ctx, codigo_torneo, premio)

@bot.command(name="nuevo-sorteo")
@comando_roles_permitidos("admin")
async def nuevo_sorteo(ctx, *, args: str = None):
    await nuevo_sorteo_handle(ctx, args=args)

@bot.command(name="realizar-sorteo")
@comando_roles_permitidos("admin")
async def realizar_sorteo(ctx, codigo: str):
    await realizar_sorteo_handle(ctx, codigo.strip())

#########################################################################################################

######################################### COMANDOS JUGADORES ############################################



@bot.command(name="agendar-partida")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def agendar_partida(ctx, fecha=None, hora=None, jugador1: discord.Member = None, _vs=None, jugador2: discord.Member = None):
    """Agenda una partida entre dos jugadores - !agendar-partida"""
    await agendar_partida_handle(ctx, fecha, hora, jugador1, _vs, jugador2)

@bot.command(name="modificar-agenda")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def agendar_partida(ctx):
    """Permite modificar una partida agendada entre dos jugadores - !modificar-agenda"""
    await modificar_partida_agendada_handle(ctx)

@bot.command(name="eventos-hoy")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def eventos_hoy(ctx):
    """Muestra los eventos programados para hoy - !eventos-hoy"""
    await eventos_hoy_handle(ctx)

@bot.command(name="nueva-peticion")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def nueva_peticion(ctx, *, descripcion: str = None):
    """Crea una nueva petición - !nueva-peticion"""
    await nueva_peticion_handle(ctx, descripcion)

@bot.command(name="inscribirse")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def inscribirse(ctx, codigo: str = None, usuario: discord.Member = None):
    """Inscribe a un usuario en un torneo - !inscribirse"""
    await inscribirse_handler(ctx, codigo, usuario)

@bot.command(name="desinscribirse")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def desinscribirse(ctx, codigo: str = None, usuario: discord.Member = None):
    """Desinscribe a un usuario de un torneo - !desinscribirse"""
    await desinscribirse_handler(ctx, codigo, usuario)

@bot.command(name="ver-inscritos")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def ver_inscritos(ctx, codigo=None):
    """Muestra los inscritos en un torneo - !ver-inscritos"""
    await ver_inscritos_handler(ctx, codigo)

@bot.command(name="reportar-resultado")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def reportar_resultado(ctx, codigo_torneo: str = None, jugador1: discord.Member = None, resultado: str = None, jugador2: discord.Member = None):
    """Reporta el resultado de un partido de un torneo - !reportar-resultado"""
    await reportar_resultado_handle(ctx, codigo_torneo, jugador1, resultado, jugador2)

@bot.command(name="modificar-resultado")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def modificar_resultado(ctx, codigo=None):
    """Permite cambiar el resultado de un encuentro mientras la ronda siga en juego - !modificar-resultado"""
    await modificar_resultado_handle(ctx, codigo)

@bot.command(name="partidos-pendientes")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def partidos_pendientes(ctx, codigo_torneo: str, type='user'):
    """Muestra los partidos pendientes de esa ronda de un torneo - !partidos-pendientes <código_torneo>"""
    await partidos_pendientes_handle(ctx, codigo_torneo, type)

@bot.command(name="inscribirse-sorteo")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def inscribirse_sorteo(ctx, codigo: str):
    await inscribirse_sorteo_handle(ctx, codigo)

@bot.command(name="subir-deck")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def subir_deck(ctx, codigo: str = None):
    """Comando para subir la lista que jugaras en un torneo - !subir-deck"""
    await submitted_deck_handle(ctx, codigo)

@bot.command(name="editar-deck")
@comando_roles_permitidos("socio", "second-chance-socio", "miembro", "second-chance-miembro")
async def editar_deck(ctx, codigo: str = None):
    """Permite editar la lista que has subido para jugar un torneo - !editar-deck"""
    await editar_deck_handle(ctx, codigo)

#########################################################################################################

######################################### COMANDOS TORNEOS ##############################################


@bot.command(name="nuevo-torneo")
@comando_roles_permitidos("admin")
async def new_tournament(ctx, *, args=None):
    """Crea un nuevo torneo en Challonge -!nuevo-torneo Nombre | Formato | tipo | Jugadores | Fecha | Roles_permitidos | DeckURL"""
    await new_tournament_assistance_handle(ctx, args=args)

@bot.command(name="iniciar-torneo")
@comando_roles_permitidos("admin")
async def iniciar_torneo(ctx, codigo_torneo: str):
    """Inicia un torneo con el código proporcionado - !iniciar-torneo <código_torneo>"""
    await iniciar_torneo_handle(ctx, codigo_torneo)

@bot.command(name="actualizar-clasificacion")
@comando_roles_permitidos("admin")
async def actualizar_clasificacion(ctx, codigo_torneo: str):
    """Actualiza la clasificación con criterios estilo MTG y la publica en #clasificaciones-torneos - !actualizar-clasificacion <código_torneo>"""
    await actualizar_clasificacion_handle(ctx, codigo_torneo)


@bot.command(name="forzar-ronda")
@comando_roles_permitidos("admin")
async def forzar_ronda(ctx, codigo_torneo: str):
    """Se termina la rondar actual con empate de las partidas no jugadas y se inicia la siguiente - !forzar-ronda <código_torneo>"""
    await forzar_ronda_handle(ctx, codigo_torneo)

@bot.command(name="eliminar-torneo")
@comando_roles_permitidos("admin")
async def listar_torneos(ctx):
        await listar_torneos_handle(ctx)

#########################################################################################################

@bot.command(name="mis-comandos")
async def mis_comandos(ctx):
  await  mis_comandos_handle(ctx)

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    cargar_tareas(bot)

@bot.event
async def on_message_delete(message):
    await registrar_mensaje_borrado_handle(message)

@bot.event
async def on_message(message: discord.Message):
    await bienvenida_y_comandos_handle(message)
    await bot.process_commands(message)  # Esto es importante para que los comandos funcionen

@bot.event
async def on_member_update(before, after):
    await evento_socio_handle(before, after)

@bot.event
async def on_member_remove(member: discord.Member):
    await usuario_salio_handle(bot, member)
    
    
# webserver.keep_alive()  
# bot.run(DISCORD_TOKEN)

bot.run(config.TOKEN)
