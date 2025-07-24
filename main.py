import discord
from discord.ext import commands

from utils.admin import aplicar_out, aplicar_strike, eliminar_mensajes, cerrar_peticion_handle, sorteo_torneo_handle, moderador_permisos_handle
from utils.jugadores import agendar_partida_handle, eventos_hoy_handle, nueva_peticion_handle, inscribirse_handler, desinscribirse_handler, ver_inscritos_handler, reportar_resultado_handle
from utils.torneos import nuevo_torneo, iniciar_torneo_handle, actualizar_clasificacion_handle, partidos_pendientes_handle, forzar_ronda_handle

from utils.watchers import cargar_tareas;
from utils.commons import validar_canal_correcto, borrar_mensaje_seguro

import config
import os
import webserver
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')


intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

bot = commands.Bot(command_prefix='!', intents=intents)

def comando_roles_permitidos(*roles):
    def decorador(func):
        func.roles_permitidos = roles
        return func
    return decorador

################################## COMANDOS ADMINISTRADOR ###############################################

@bot.command(name="strike")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def strike(ctx, miembro: discord.Member = None):
    """Aplica un strike a un miembro del servidor - !strike <usuario>"""
    await aplicar_strike(ctx, miembro)

@bot.command(name="out")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def out(ctx, miembro: discord.Member = None):
    """aplica el rol 'Out' a un miembro del servidor - !out <usuario>"""
    await aplicar_out(ctx, miembro)

@bot.command(name="eliminar-mensajes")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def clear(ctx, canal: discord.TextChannel = None, cantidad: int = None):
    """Elimina una cantidad específica de mensajes en un canal - !eliminar-mensajes <canal> <cantidad>"""
    await eliminar_mensajes(ctx, canal, cantidad)

@bot.command(name="cerrar-peticion")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def cerrar_peticion(ctx, codigo: str = None, *, respuesta: str = None):
    """Cierra una petición y envía la respuesta al usuario - !cerrar-peticion <código> <respuesta>"""
    await cerrar_peticion_handle(ctx, codigo, respuesta)

@bot.command(name="sorteo-torneo")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def sorteo_torneo(ctx, codigo_torneo: str, *, premio: str = "Premio del sorteo"):
    """Realiza un sorteo entre los inscritos de un torneo - !sorteo-torneo <código_torneo> <premio>"""
    await sorteo_torneo_handle(ctx, codigo_torneo, premio)

#########################################################################################################

######################################### COMANDOS JUGADORES ############################################



@bot.command(name="agendar-partida")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def agendar_partida(ctx, fecha=None, hora=None, jugador1: discord.Member = None, _vs=None, jugador2: discord.Member = None):
    """Agenda una partida entre dos jugadores - !agendar-partida <fecha> <hora> <jugador1> vs <jugador2>"""
    await agendar_partida_handle(ctx, fecha, hora, jugador1, _vs, jugador2)

@bot.command(name="eventos-hoy")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def eventos_hoy(ctx):
    """Muestra los eventos programados para hoy - !eventos-hoy"""
    await eventos_hoy_handle(ctx)

@bot.command(name="nueva-peticion")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def nueva_peticion(ctx, *, descripcion: str = None):
    """Crea una nueva petición - !nueva-peticion <descripción>"""
    await nueva_peticion_handle(ctx, descripcion)

@bot.command(name="inscribirse")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def inscribirse(ctx, codigo: str = None, usuario: discord.Member = None):
    """Inscribe a un usuario en un torneo - !inscribirse <código> (<usuario> solo Administradores)"""
    await inscribirse_handler(ctx, codigo, usuario)

@bot.command(name="desinscribirse")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def desinscribirse(ctx, codigo: str = None, usuario: discord.Member = None):
    """Desinscribe a un usuario de un torneo - !desinscribirse <código> (<usuario> solo Administradores)"""
    await desinscribirse_handler(ctx, codigo, usuario)

@bot.command(name="ver-inscritos")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def ver_inscritos(ctx, codigo=None):
    """Muestra los inscritos en un torneo - !ver-inscritos <código>"""
    await ver_inscritos_handler(ctx, codigo)

@bot.command(name="reportar-resultado")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def reportar_resultado(ctx, codigo_torneo: str, jugador1: discord.Member, resultado: str, jugador2: discord.Member):
    """Reporta el resultado de un partido de un torneo - !reportar-resultado <código_torneo> <jugador1> <resultado> <jugador2>"""
    await reportar_resultado_handle(ctx, codigo_torneo, jugador1, resultado, jugador2)

@bot.command(name="partidos-pendientes")
@comando_roles_permitidos("socio", "second-chance-socio", "Miembro", "second-chance-miembro")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def partidos_pendientes(ctx, codigo_torneo: str):
    """Muestra los partidos pendientes de esa ronda de un torneo - !partidos-pendientes <código_torneo>"""
    await partidos_pendientes_handle(ctx, codigo_torneo)


#########################################################################################################

######################################### COMANDOS TORNEOS ##############################################


@bot.command(name="nuevo-torneo")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def new_tournament(ctx, *, args=None):
    """Crea un nuevo torneo en Challonge -!nuevo-torneo Nombre | Formato | tipo | Jugadores | Fecha | Roles_permitidos | DeckURL"""
    await nuevo_torneo(ctx, args=args)

@bot.command(name="iniciar-torneo")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def iniciar_torneo(ctx, codigo_torneo: str):
    """Inicia un torneo con el código proporcionado - !iniciar-torneo <código_torneo>"""
    await iniciar_torneo_handle(ctx, codigo_torneo)

@bot.command(name="actualizar-clasificacion")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def actualizar_clasificacion(ctx, codigo_torneo: str):
    """Actualiza la clasificación con criterios estilo MTG y la publica en #clasificaciones-torneos - !actualizar-clasificacion <código_torneo>"""
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!nuevo-torneo"):
        return
    if not await moderador_permisos_handle(ctx):
        return
    await actualizar_clasificacion_handle(ctx, codigo_torneo)


@bot.command(name="forzar-ronda")
@comando_roles_permitidos("admin")
@commands.has_permissions(manage_messages=True)
@commands.has_permissions(manage_roles=True)
async def forzar_ronda(ctx, codigo_torneo: str):
    """Se termina la rondar actual con empate de las partidas no jugadas y se inicia la siguiente - !forzar-ronda <código_torneo>"""
    await forzar_ronda_handle(ctx, codigo_torneo)

#########################################################################################################

@bot.command(name="mis-comandos")
async def mis_comandos(ctx):
    """Muestra los comandos disponibles según tus permisos y roles - !mis-comandos"""
    if not await validar_canal_correcto(ctx, "preguntale-a-el-barbas", "!mis-comandos"):
        return
    usuario_roles = [r.name for r in ctx.author.roles]
    comandos_por_rol = {}

    for comando in bot.commands:
        if comando.hidden:
            continue

        roles_permitidos = getattr(comando, "roles_permitidos", None)

        try:
            if await comando.can_run(ctx):
                nombre = f"!{comando.name}"
                descripcion = comando.help or "Sin descripción disponible"
                linea = f"**{nombre}** — {descripcion}"

                if roles_permitidos:
                    for rol in roles_permitidos:
                        if rol in usuario_roles:
                            comandos_por_rol.setdefault(rol, []).append(linea)
                else:
                    comandos_por_rol.setdefault("Todos", []).append(linea)
        except commands.CheckFailure:
            continue

    if not comandos_por_rol:
        await ctx.author.send("❌ No tienes acceso a ningún comando.")
        return

    embed = discord.Embed(
        title="📋 Comandos disponibles según tu rol",
        color=discord.Color.blue()
    )

    # Añadir campos, dividiendo si se pasa del límite de 1024 caracteres
    for rol, comandos in comandos_por_rol.items():
        contenido = ""
        for linea in comandos:
            if len(contenido) + len(linea) + 1 > 1024:
                embed.add_field(name=f"🔹 {rol}", value=contenido, inline=False)
                contenido = linea + "\n"
            else:
                contenido += linea + "\n"

        if contenido:
            embed.add_field(name=f"🔹 {rol}", value=contenido, inline=False)

    try:
        await ctx.author.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte un mensaje privado. Revisa tus ajustes de privacidad.")

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    cargar_tareas(bot)

webserver.keep_alive()  
bot.run(DISCORD_TOKEN)
# bot.run(config.TOKEN)
