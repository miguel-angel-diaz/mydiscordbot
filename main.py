######## main.py #######

import asyncio
import discord
from discord.ext import commands
import logging
import os
import unicodedata

from utils import canales

from utils.torneos_api import iniciar_servidor_web, set_bot_instance

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

from utils.jugadores import (
    agendar_partida_handle,
    modificar_partida_agendada_handle,
    eventos_hoy_handle,
    nueva_peticion_handle,
    ver_inscritos_handler,
    inscribirse_sorteo_handle,
    mis_comandos_handle,
    submitted_deck_handle,
    editar_deck_handle,
    cartas_mas_jugadas_handle
)

from utils.torneos import tournament_report_handle

from utils.battle import (
    nuevo_battle_handle,
    iniciar_battle_handle,
    reportar_resultado_battle_handle,
    modificar_resultado_battle_handle,
    actualizar_clasificacion_battle_handle,
    finalizar_battle_handle
)

from utils.events import (
  registrar_mensaje_borrado_handle, 
  bienvenida_y_comandos_handle, 
  evento_socio_handle, 
  usuario_salio_handle,
  reconocer_comando_handle,
  log_comando_handle,
  member_join_handle
)

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
    swiss_lista_inscritos_asistente_handle,
    swiss_reiniciar_asistente_handle,
    swiss_eliminar_ronda_asistente_handle,
    swiss_finalizar_asistente_handle,
    swiss_partidos_pendientes_handle
)

from utils.watchers import cargar_tareas;

from utils.commons import best_decks_handle;

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Configurar logging: un único formato para el bot y discord.py (bot.run usa log_handler=None para no duplicar)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

bot = commands.Bot(
    command_prefix='!', 
    intents=intents,
    case_insensitive=True 
)
set_bot_instance(bot)

def normalize_string(s: str) -> str:
    """Convierte a minúsculas y elimina acentos"""
    s = s.lower()
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return s

ROL_ADMIN = canales.ROL_ADMIN
ROLES_SANCIONADOS = {canales.ROL_OUT.lower(), canales.ROL_STRIKE.lower()}  # bloquean los comandos aunque se tenga un rol permitido


async def _denegar_comando(ctx, mensaje: str) -> bool:
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass
    try:
        await ctx.author.send(mensaje)
    except discord.Forbidden:
        pass
    return False


def comando_roles_permitidos(*roles):
    """
    Restringe el comando a los roles indicados (sin distinguir mayúsculas ni tildes).
    El dueño del servidor y los admins siempre pueden usarlo; quien tenga un rol
    de sanción (Out/Strike) no puede, aunque tenga un rol permitido.
    """
    roles_normalizados = {normalize_string(r) for r in roles}

    async def predicate(ctx):
        comando = f"!{ctx.command.qualified_name}"
        if ctx.guild is None:
            return await _denegar_comando(ctx, f"❌ El comando `{comando}` solo se puede usar en el servidor.")

        autor = ctx.author
        roles_autor = {normalize_string(r.name) for r in getattr(autor, "roles", [])}

        es_admin = (
            autor == ctx.guild.owner
            or ROL_ADMIN in roles_autor
            or autor.guild_permissions.administrator
        )
        if es_admin:
            return True

        if roles_autor & ROLES_SANCIONADOS:
            return await _denegar_comando(ctx, f"🚫 No puedes usar `{comando}` mientras tengas una sanción activa.")

        if roles_autor & roles_normalizados:
            return True

        return await _denegar_comando(
            ctx,
            f"❌ Necesitas uno de estos roles para usar `{comando}`: {', '.join(sorted(roles))}."
        )

    return commands.check(predicate)

################################## COMANDOS ADMINISTRADOR ###############################################

@bot.command(name="strike")
@comando_roles_permitidos(canales.ROL_ADMIN)
async def strike(ctx, miembro: discord.Member = None):
    """Aplica un strike a un miembro del servidor - !strike <usuario>"""
    await aplicar_strike(ctx, miembro)

@bot.command(name="out")
@comando_roles_permitidos(canales.ROL_ADMIN)
async def out(ctx, miembro: discord.Member = None):
    """aplica el rol 'Out' a un miembro del servidor - !out <usuario>"""
    await aplicar_out(ctx, miembro)

@bot.command(name="eliminar-mensajes",
    aliases=["eliminar mensajes", "eliminar_mensajes"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def clearMessajes(ctx, canal: discord.TextChannel = None, cantidad: int = None):
    """Elimina una cantidad específica de mensajes en un canal - !eliminar-mensajes <canal> <cantidad>"""
    await eliminar_mensajes(ctx, canal, cantidad)

@bot.command(name="eliminar-decks",
    aliases=["eliminar decks", "eliminar_decks"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def clearDecks(ctx, codigo: str = None):
    """Elimina los decks submiteados para un torneo - !eliminar-decks <torneo>"""
    await eliminar_decks_handle(ctx,codigo)

@bot.command(name="cerrar-peticion",
    aliases=["cerrar peticion", "cerrar_peticion"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def cerrar_peticion(ctx, codigo: str = None, *, respuesta: str = None):
    """Cierra una petición y envía la respuesta al usuario - !cerrar-peticion <código> <respuesta>"""
    await cerrar_peticion_handle(ctx, codigo, respuesta)

@bot.command(name="sorteo-torneo",
    aliases=["sorteo torneo", "sorteo_torneo"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def sorteo_torneo(ctx, codigo_torneo: str = None, *, premio: str = "Premio del sorteo"):
    """Realiza un sorteo entre los inscritos de un torneo - !sorteo-torneo <código_torneo> <premio>"""
    await sorteo_torneo_handle(ctx, codigo_torneo, premio)

@bot.command(name="nuevo-sorteo",
    aliases=["nuevo sorteo", "nuevo_sorteo"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def nuevo_sorteo(ctx, *, args: str = None):
    await nuevo_sorteo_handle(ctx, args=args)

@bot.command(name="realizar-sorteo",
    aliases=["realizar sorteo", "realizar_sorteo"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def realizar_sorteo(ctx, codigo: str = None):
    await realizar_sorteo_handle(ctx, codigo)

@bot.command(
    name="nuevo-comunicado",
    aliases=["nuevo_comunicado"]
)
@comando_roles_permitidos(canales.ROL_ADMIN)
async def nuevo_comunicado(ctx, *, mensaje: str = None):
    """
    Envía un comunicado al canal 📰-tablon‐anuncios
    Uso: !nuevo-comunicado <mensaje>
    """
    await nuevo_comunicado_handle(ctx, mensaje)


#########################################################################################################

######################################### COMANDOS JUGADORES ############################################


@bot.command(name="agendar-partida",
    aliases=["agendar partida", "agendar_partida"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def agendar_partida(ctx, fecha=None, hora=None, jugador1: discord.Member = None, _vs=None, jugador2: discord.Member = None):
    """Agenda una partida entre dos jugadores - !agendar-partida"""
    await agendar_partida_handle(ctx, fecha, hora, jugador1, _vs, jugador2)

@bot.command(name="modificar-agenda",
    aliases=["modificar agenda", "modificar_agenda"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def agendar_partida(ctx):
    """Permite modificar una partida agendada entre dos jugadores - !modificar-agenda"""
    await modificar_partida_agendada_handle(ctx)

@bot.command(name="eventos-hoy",
    aliases=["eventos hoy", "eventos_hoy"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def eventos_hoy(ctx):
    """Muestra los eventos programados para hoy - !eventos-hoy"""
    await eventos_hoy_handle(ctx)

@bot.command(name="nueva-peticion",
    aliases=["nueva peticion", "nueva_peticion"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def nueva_peticion(ctx, *, descripcion: str = None):
    """Crea una nueva petición - !nueva-peticion"""
    await nueva_peticion_handle(ctx, descripcion)


@bot.command(name="ver-inscritos",
    aliases=["ver inscritos", "ver_inscritos"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def ver_inscritos(ctx, codigo=None):
    """Muestra los inscritos en un torneo - !ver-inscritos"""
    await ver_inscritos_handler(ctx, codigo)


@bot.command(name="iniciar-battle",
    aliases=["iniciar battle", "iniciar_battle"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def iniciar_battle(ctx, codigo_torneo: str = None, jugador1: discord.Member = None, jugador2: discord.Member = None):
    """Apunta un enfrentamiento en un Battle Royale (máximo 2 por pareja) - !iniciar-battle <código> @j1 @j2"""
    await iniciar_battle_handle(ctx, codigo_torneo, jugador1, jugador2)

@bot.command(name="reportar-resultado-battle",
    aliases=["reportar resultado battle", "reportar_resultado_battle"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def reportar_resultado_battle(ctx, codigo_torneo: str = None, jugador1: discord.Member = None, resultado: str = None, jugador2: discord.Member = None):
    """Reporta el resultado de un enfrentamiento pendiente de un Battle Royale - !reportar-resultado-battle"""
    await reportar_resultado_battle_handle(ctx, codigo_torneo, jugador1, resultado, jugador2)

@bot.command(name="partidos-pendientes",
    aliases=["partidos pendientes", "partidos_pendientes"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def partidos_pendientes(ctx, codigo_torneo: str = None):
    """Muestra las partidas sin resultado de la ronda actual de un torneo suizo - !partidos-pendientes <código_torneo>"""
    await swiss_partidos_pendientes_handle(ctx, codigo_torneo)

@bot.command(name="inscribirse-sorteo",
    aliases=["inscribirse sorteo", "inscribirse_sorteo"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def inscribirse_sorteo(ctx, codigo: str = None):
    await inscribirse_sorteo_handle(ctx, codigo)

@bot.command(name="subir-deck",
    aliases=["subir deck", "subir_deck"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def subir_deck(ctx, codigo: str = None):
    """Comando para subir la lista que jugaras en un torneo - !subir-deck"""
    await submitted_deck_handle(ctx, codigo)

@bot.command(name="editar-deck",
    aliases=["editar deck", "editar_deck"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def editar_deck(ctx, codigo: str = None):
    """Permite editar la lista que has subido para jugar un torneo - !editar-deck"""
    await editar_deck_handle(ctx, codigo)

@bot.command(name="cartas-mas-jugadas", 
    aliases=["cartas mas jugadas","cartas_mas_jugadas"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def cartas_mas_jugadas(ctx):
    """Inicia el wizard de estadísticas - !stats"""
    await cartas_mas_jugadas_handle(ctx)

@bot.command(name="best-decks", 
    aliases=["best decks", "best_decks"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def best_decks(ctx, codigo_torneo: str = None):
    """analiza los mejores decks de un torneo"""
    await best_decks_handle(ctx, codigo_torneo)

#########################################################################################################

######################################### COMANDOS TORNEOS ##############################################


@bot.command(name="actualizar-clasificacion-battle",
    aliases=["actualizar clasificacion battle", "actualizar_clasificacion_battle"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def actualizar_clasificacion_battle(ctx, codigo_torneo: str = None):
    """Vuelve a publicar la clasificación de un battle en #🍺-el‐ranking‐de‐la‐barra - !actualizar-clasificacion-battle <código>"""
    await actualizar_clasificacion_battle_handle(ctx, codigo_torneo)


@bot.command(name="nuevo-battle",
    aliases=["nuevo battle", "nuevo_battle"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def nuevo_battle(ctx, *, nombre: str = None):
    """Crea un Battle Royale (sin Challonge) - !nuevo-battle [nombre]"""
    await nuevo_battle_handle(ctx, nombre)


@bot.command(name="finalizar-battle",
    aliases=["finalizar battle", "finalizar_battle"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def finalizar_battle(ctx, codigo_torneo: str = None):
    """Cierra un Battle Royale y publica la clasificación final - !finalizar-battle <código>"""
    await finalizar_battle_handle(ctx, codigo_torneo)


@bot.command(name="modificar-resultado-battle",
    aliases=["modificar resultado battle", "modificar_resultado_battle"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def modificar_resultado_battle(ctx, codigo_torneo: str = None):
    """Corrige el resultado de un enfrentamiento de un Battle Royale - !modificar-resultado-battle <código>"""
    await modificar_resultado_battle_handle(ctx, codigo_torneo)


@bot.command(name="reportar-torneo",
    aliases=["reportar torneo", "reportar_torneo"])
@comando_roles_permitidos(canales.ROL_ADMIN)
async def tournament_report(ctx):
        await tournament_report_handle(ctx)

@bot.command(name="actualizar-web",
    aliases=["actualizar web", "actualizar_web"])
async def actualizar_web(ctx):
    await actualizar_web_handle(ctx)


#####################################################################################################

@bot.command(name="nuevo-swiss", aliases=["nuevo torneo", "nuevo_torneo", "nuevo-torneo"])
@commands.has_permissions(administrator=True)
async def nuevo_swiss(ctx):
    await swiss_nuevo_asistente_handle(ctx)

@bot.command(name="inscribir-swiss", aliases=["inscribir swiss", "inscribir_swiss", "inscribirse", "inscribir"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def inscribir_swiss(ctx):
    await swiss_inscribir_asistente_handle(ctx)

@bot.command(name="desinscribir-swiss", aliases=["desinscribir swiss", "desinscribir_swiss", "desinscribirse", "desinscribir"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def desinscribir_swiss(ctx):
    await swiss_desinscribir_asistente_handle(ctx)

@bot.command(name="iniciar-swiss", aliases=["iniciar torneo", "iniciar_torneo", "iniciar-torneo"])
@commands.has_permissions(administrator=True)
async def iniciar_swiss(ctx):
    await swiss_iniciar_asistente_handle(ctx)

@bot.command(name="reiniciar-swiss", aliases=["reiniciar torneo", "reiniciar_torneo", "reiniciar-torneo"])
@commands.has_permissions(administrator=True)
async def reiniciar_swiss(ctx):
    await swiss_reiniciar_asistente_handle(ctx)

@bot.command(name="reportar-swiss", aliases=["reportar resultado", "reportar_resultado", "reportar-resultado"])
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def reportar_swiss(ctx):
    await swiss_reportar_asistente_handle(ctx)

@bot.command(name="modificar-resultado-swiss",
    aliases=["modificar resultado swiss", "modificar_resultado_swiss", "modificar-resultado", "modificar resultado", "modificar_resultado"])
@commands.has_permissions(administrator=True)
async def modificar_resultado_swiss(ctx):
    await swiss_modificar_resultado_asistente_handle(ctx)

@bot.command(name="clasificacion-swiss")
@comando_roles_permitidos(*canales.ROLES_JUGADORES)
async def clasificacion_swiss(ctx):
    await swiss_clasificacion_asistente_handle(ctx)

@bot.command(name="siguiente-ronda-swiss")
@commands.has_permissions(administrator=True)
async def siguiente_ronda_swiss(ctx):
    await swiss_siguiente_ronda_asistente_handle(ctx)

@bot.command(name="eliminar-swiss", aliases=["eliminar torneo", "eliminar_torneo", "eliminar-torneo"])
@commands.has_permissions(administrator=True)
async def eliminar_swiss(ctx):
    await swiss_eliminar_asistente_handle(ctx)

@bot.command(name="eliminar-ronda-swiss")
@commands.has_permissions(administrator=True)
async def eliminar_ronda_swiss(ctx):
    await swiss_eliminar_ronda_asistente_handle(ctx)

@bot.command(name="finalizar-swiss")
@commands.has_permissions(administrator=True)
async def finalizar_swiss(ctx):
    await swiss_finalizar_asistente_handle(ctx)


#####################################################################################################


@bot.command(name="mis-comandos",
    aliases=["mis comandos", "mis_comandos", "comandos", "comandios", "comandiox"])
async def mis_comandos(ctx):
  await  mis_comandos_handle(ctx)

@bot.event
async def on_ready():
    # Se repite en cada reconexión a Discord: aquí no se arranca nada (eso va en setup_hook)
    logger.info(f"✅ Bot conectado como {bot.user}")


async def _arranque_unico():
    """setup_hook: se ejecuta UNA sola vez al arrancar, antes de conectar (on_ready se repite al reconectar)."""
    await iniciar_servidor_web()          # con await: si falla (p. ej. puerto ocupado) se ve en el arranque
    cargar_tareas(bot)                    # el bucle espera a wait_until_ready antes de su primera ejecución

    # Caché de la web a memoria; si falta o es antigua (p. ej. tras un deploy) se regenera en segundo plano
    from utils import cache_web
    from utils.torneos_api import refrescar_cache_al_arrancar
    cache = await cache_web.cargar()
    if cache:
        logger.info(f"✅ Caché de torneos cargada: {len(cache.get('torneos', []))} torneos")
    else:
        logger.warning("⚠️ No hay caché de torneos: se generará en cuanto el bot esté listo.")
    bot._tarea_cache_web = asyncio.create_task(refrescar_cache_al_arrancar(bot))   # referencia: que no la recoja el GC

bot.setup_hook = _arranque_unico


@bot.event
async def on_message_delete(message):
    await registrar_mensaje_borrado_handle(message)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bienvenida_y_comandos_handle(message)
    manejado = await reconocer_comando_handle(bot, message)
    if not manejado:
        await bot.process_commands(message)

@bot.event
async def on_member_update(before, after):
    await evento_socio_handle(before, after)

@bot.event
async def on_member_remove(member: discord.Member):
    await usuario_salio_handle(bot, member)

@bot.event
async def on_command(ctx):
    await log_comando_handle( 
        bot, 
        usuario=ctx.author,
        comando=ctx.command.name if ctx.command else "desconocido",
        tipo="correcto",
        fecha=ctx.message.created_at
    )

@bot.event
async def on_command_error(ctx, error):
    original = getattr(error, "original", error)
    uso = f"`!{ctx.command.qualified_name} {ctx.command.signature}`".replace(" `", "`") if ctx.command else ""

    if isinstance(error, commands.CommandNotFound):
        tipo = "no_encontrado"
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        tipo = "argumento_faltante"
        await _avisar_usuario(ctx, f"⚠️ Faltan datos o no son válidos ({error}).\nUso: {uso}")
    elif isinstance(error, commands.NoPrivateMessage):
        tipo = "error"
        await _avisar_usuario(ctx, "❌ Este comando solo se puede usar en el servidor.")
    elif isinstance(error, commands.MissingPermissions):
        tipo = "error"
        await _avisar_usuario(ctx, "❌ Necesitas permisos de administrador para usar este comando.")
    elif isinstance(error, commands.CheckFailure):
        tipo = "error"   # comando_roles_permitidos ya avisó al usuario por DM
    else:
        tipo = "error"
        nombre = ctx.command.qualified_name if ctx.command else ctx.message.content
        logger.error("Error ejecutando %s", nombre, exc_info=(type(original), original, original.__traceback__))
        await _avisar_usuario(ctx, "❌ Ha ocurrido un error inesperado al ejecutar el comando. Ya ha quedado registrado.")

    try:
        await log_comando_handle(
            bot,
            usuario=ctx.author,
            comando=ctx.message.content,
            tipo=tipo,
            error=original,
            fecha=ctx.message.created_at
        )
    except Exception:
        logger.exception("No se pudo registrar el error del comando en el canal de logs")


async def _avisar_usuario(ctx, texto: str):
    try:
        await ctx.author.send(texto)
    except discord.HTTPException:
        pass

@bot.event
async def on_voice_state_update(member, before, after):
    await member_join_handle(member, before, after)

    
    
# webserver.keep_alive()  
# bot.run(DISCORD_TOKEN)
if __name__ == "__main__":
    import os

    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

    # Si no existe en el entorno (Railway), usa token.py local
    if not DISCORD_TOKEN:
        try:
            from config_token import DISCORD_TOKEN
            logger.info("🔹 Usando token local desde config_token.py")
        except ImportError:
            raise ValueError("❌ No se encontró el token del bot. Configura la variable DISCORD_TOKEN o crea token.py.")

    bot.run(DISCORD_TOKEN, log_handler=None)


