######## events.py #######
import logging
import discord
from discord.ext import commands
from datetime import datetime, timezone
import asyncio
import config

from discord.ext.commands.view import StringView

from utils import canales
from utils import dm

log = logging.getLogger(__name__)

PREFIJO = "!"

tiempos_entrada = {}  # { user_id: datetime }


async def registrar_mensaje_borrado_handle(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    if message.channel.name.lower() in config.CANALES_EXCLUIDOS:
        return

    guild = message.guild
    canal_log = canales.get_canal(guild, canales.MENSAJES_BORRADOS)
    if not canal_log:
        return

    try:
        embed = discord.Embed(
            title="🗑️ Mensaje borrado",
            description=f"**Autor:** {message.author.mention}\n"
                        f"**Canal:** {message.channel.mention}\n"
                        f"**Fecha:** <t:{int(message.created_at.timestamp())}:F>",
            color=discord.Color.red(),
        )

        if message.content:
            embed.add_field(
                name="Contenido borrado",
                value=_recortar(discord.utils.escape_markdown(message.content)),
                inline=False
            )

        if message.attachments:
            urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Adjuntos", value=_recortar(urls), inline=False)

        await canal_log.send(embed=embed)

    except Exception as e:
        log.exception(f"registrando mensaje borrado: {e}")

def mapa_alias_con_espacios(bot: commands.Bot) -> dict:
    """
    {"subir deck": comando, ...} generado desde los comandos registrados: sus alias con espacio y su nombre con
    espacios en vez de guiones. Discord.py no puede invocar nombres con espacio ("!subir deck" busca "subir"),
    por eso se reconocen aquí. Antes era una lista a mano, incompleta y con nombres que ya no existían.
    """
    mapa = {}
    for comando in bot.walk_commands():
        for nombre in (comando.qualified_name, *comando.aliases):
            for variante in (nombre, nombre.replace("-", " ").replace("_", " ")):
                if " " in variante:
                    mapa.setdefault(variante.lower(), comando)
    return mapa


def _alias_del_mensaje(mapa: dict, texto: str):
    """(alias, resto) con el alias MÁS LARGO al principio del texto (seguido de espacio o fin), o (None, None)."""
    for alias in sorted(mapa, key=len, reverse=True):
        if texto == alias or texto.startswith(alias + " "):
            return alias, texto[len(alias):].strip()
    return None, None


async def reconocer_comando_handle(bot: commands.Bot, message: discord.Message):
    """
    "!subir deck ..." -> pregunta por DM si se quería "!subir-deck" y, si se confirma, lo ejecuta con bot.invoke:
    pasa los permisos, el bloqueo de Out/Strike y los conversores como cualquier comando (antes ctx.invoke se los
    saltaba y un usuario sancionado podía subir decks, agendar o apuntarse a sorteos así).
    """
    if not message.content.startswith(PREFIJO):
        return False  # No es comando, seguimos

    texto = message.content[len(PREFIJO):].strip()
    alias, resto = _alias_del_mensaje(mapa_alias_con_espacios(bot), texto.lower())
    if alias is None:
        return False  # No es un alias con espacio, seguimos
    comando = mapa_alias_con_espacios(bot)[alias]
    resto = texto[len(texto) - len(resto):] if resto else ""     # los argumentos con sus mayúsculas originales

    ctx = await bot.get_context(message)
    ctx.command, ctx.invoked_with = comando, comando.qualified_name
    ctx.view = StringView(resto)

    # Permisos ANTES de preguntar: antes se ofrecía "¿Querías usar !eliminar-mensajes?" a cualquiera. Sin permiso,
    # lo mismo que al escribir el comando entero: el error va a on_command_error, que avisa y lo registra
    try:
        puede = await comando.can_run(ctx)     # si lo deniega el cog_check devuelve False (ya avisó por DM), no lanza
    except commands.CommandError as error:
        bot.dispatch("command_error", ctx, error)
        return True
    if not puede:
        bot.dispatch("command_error", ctx, commands.CheckFailure(f"Sin permiso para {comando.qualified_name}"))
        return True

    try:
        canal_dm = await message.author.create_dm()
        embed = discord.Embed(
            title="⚡ He detectado tu comando",
            description=f"¿Querías usar `{PREFIJO}{comando.qualified_name}`? (responde con **sí** o **no**)",
            color=0x00ffcc
        )
        await canal_dm.send(embed=embed)

        def check(m):
            return (
                m.author == message.author
                and m.channel == canal_dm
                and m.content.strip().lower() in ["sí", "si", "no"]
            )

        respuesta = await bot.wait_for("message", timeout=30.0, check=check)

        if dm.es_si(respuesta.content):
            await bot.invoke(ctx)          # con comprobaciones; los errores llegan a on_command_error
        else:
            await canal_dm.send("❌ Comando cancelado.")
    except asyncio.TimeoutError:
        await canal_dm.send("⏰ Tiempo agotado. Comando cancelado automáticamente.")
    except discord.Forbidden:
        # DMs cerrados: antes el comando se descartaba sin decir nada
        try:
            await message.channel.send(
                f"{message.author.mention} no puedo escribirte por mensaje directo. Activa los DMs de miembros del "
                f"servidor o usa el comando completo: `{PREFIJO}{comando.qualified_name}`.", delete_after=20)
        except discord.HTTPException:
            pass
    except Exception as e:
        log.exception(f"Error en wizard: {e}")

    return True  # Indicamos que el mensaje fue manejado

async def evento_socio_handle(before: discord.Member, after: discord.Member):
    # Nombre del rol que quieres detectar
    ROL_SOCIO = "socio"

    # Buscar si antes no lo tenía y ahora sí
    roles_antes = {r.name for r in before.roles}
    roles_despues = {r.name for r in after.roles}

    if ROL_SOCIO not in roles_antes and ROL_SOCIO in roles_despues:
        mensaje = (
            "📢 **Información importante para socios**\n\n"
            "La dirección se plantea establecer una cuota para los socios. "
            "Dicha cuota será de **6 euros semestrales** o **10 anuales**, según la suscripción que quiera realizar el socio. "
            "Este dinero tiene como único fin la creación de merchandising para los premios y organizar algún tipo de evento, "
            "a criterio de la dirección.\n\n"
            "Si algún socio desea ver las cuentas, éstas le serán mostradas para que pueda ver exactamente dónde se ha destinado el dinero, "
            "ya que apostamos por la total transparencia y bienestar de nuestros socios.\n\n"
            "Por último, remarcar que el acatamiento de dichas normas es obligatorio y que si no se han leído, no es problema de la dirección. "
            "Estar en The Klub es un privilegio y no un derecho; este servidor pertenece exclusivamente a la dirección. "
            "Cualquier intento de apropiación será sancionado.\n\n"
            "Si estás conforme con todo esto, puedes pasar; si no, ten dignidad y vete tú antes de que te echemos nosotros, "
            "sin problemas ni malos rollos ya que no todo el mundo vale para estar aquí.\n\n"
            "🎉 **Y ahora sí que sí, sean bienvenidos a The Klub.**"
        )

        try:
            await after.send(mensaje)
            log.info(f"Mensaje de socio enviado a {after}")
        except discord.Forbidden:
            log.warning(f"No pude enviar mensaje privado a {after}")
         
async def usuario_salio_handle(bot: commands.Bot, member: discord.Member):
    # Retirarlo de sus torneos (suizos) y borrar sus partidas agendadas
    from utils.abandonos import gestionar_abandono_torneos  # import local: evita ciclos al cargar
    try:
        resumen_torneos = await gestionar_abandono_torneos(bot, member)
    except Exception as e:
        log.exception(f"❌ Error gestionando torneos de {member.id} al salir: {e}")
        resumen_torneos = ["❌ Error al revisar sus torneos, revisar a mano."]

    # Canal donde se detallará la info del usuario que se fue
    canal_info = canales.get_canal(member.guild, canales.USUARIOS_QUE_SE_FUERON)
    if canal_info:
        embed = discord.Embed(
            title="👋 Usuario ha abandonado el servidor",
            color=discord.Color.red()
        )
        embed.add_field(name="Nombre", value=f"{member.name}#{member.discriminator}", inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Fecha de creación", value=member.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed.add_field(name="Fecha de unión", value=member.joined_at.strftime("%d/%m/%Y %H:%M:%S") if member.joined_at else "Desconocida", inline=False)
        if resumen_torneos:
            texto = "\n".join(resumen_torneos)
            embed.add_field(name="Torneos", value=_recortar(texto), inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await canal_info.send(embed=embed)

    # Canal de anuncios
    # canal_anuncios = ctx.guild.get_channel(1387389356464934993)
    # canal_anuncios = canales.canal_anuncios(member.guild)
    # if canal_anuncios:
    #     await canal_anuncios.send(f"📢 El usuario **{member.display_name}** ha abandonado **The Klub**.")

async def entrada_vetado_handle(member: discord.Member):
    """
    La bienvenida, las normas y los roles los gestiona la Incorporación de Discord. El bot solo mira, al entrar,
    si el usuario está vetado: si lo está, se le avisa por DM y recibe 'Out' (bloquea los comandos aunque la
    Incorporación le dé 'miembro').
    """
    if member.bot:
        return
    try:
        vetado = await _esta_vetado(member, member.guild)
    except discord.HTTPException as e:
        log.warning(f"No pude revisar la blacklist para {member}: {e}")
        return
    if vetado:
        log.info(f"Entra un usuario vetado: {member} ({member.id})")
        await castigar_usuario(member)


async def _dm(member, contenido=None, **kwargs) -> bool:
    """Envía un DM sin romper el flujo si el usuario los tiene cerrados. Devuelve si se pudo enviar."""
    try:
        await member.send(contenido, **kwargs)
        return True
    except discord.HTTPException:
        log.info(f"No pude enviar DM a {member}")
        return False


async def _esta_vetado(member, guild) -> bool:
    """
    Solo NO pueden volver los expulsados (decisión del usuario):
      - los de la lista manual config.BLACKLIST_USERS;
      - los expulsados con !out, que quedan registrados en #blacklist (campo "ID" exacto).
    Quien se fue por su cuenta (#usuarios-que-nos-dejaron) puede volver con normalidad.
    """
    if member.id in config.BLACKLIST_USERS:
        return True
    canal_blacklist = canales.get_canal(guild, canales.BLACKLIST)
    if not canal_blacklist:
        return False
    uid = str(member.id)
    async for mensaje in canal_blacklist.history(limit=None):
        for embed in mensaje.embeds:
            if any((f.name or "").strip().upper() == "ID" and str(f.value).strip() == uid for f in embed.fields):
                return True
    return False


async def castigar_usuario(member: discord.Member):
    await _dm(
        member,
        "🚫 Estás vetado en **The Klub**: fuiste expulsado y no puedes volver a participar en el servidor.\n\n"
        "Lo siento, pero no eres el perfil que buscamos. Agradecemos tu interés, pero no todo el mundo vale para "
        "The Klub: estar aquí no es un derecho, es un privilegio. Buena suerte en tu camino."
    )

    # Asignar rol Out (sin dejar escapar el error si faltan permisos)
    rol_out = canales.get_rol(member.guild, canales.ROL_OUT)
    if rol_out:
        try:
            await member.add_roles(rol_out, reason="Usuario en blacklist o expulsado previamente")
        except discord.HTTPException as e:
            log.warning(f"No pude asignar el rol 'Out' a {member}: {e}")

async def log_comando_handle(bot, usuario, comando, tipo, error=None, fecha=None):
    canal_log = bot.get_channel(canales.LOG_COMANDOS_ID)
    if not canal_log:
        return

    # Definir título y color según tipo
    if tipo == "correcto":
        titulo = "✅ Comando ejecutado"
        color = discord.Color.green()
    elif tipo == "no_encontrado":
        titulo = "❌ Comando no encontrado"
        color = discord.Color.red()
    elif tipo == "argumento_faltante":
        titulo = "⚠️ Falta argumento"
        color = discord.Color.orange()
    else:  # error genérico
        titulo = "⚠️ Error en comando"
        color = discord.Color.dark_orange()

    embed = discord.Embed(
        title=titulo,
        color=color,
        timestamp=fecha
    )
    embed.add_field(name="Usuario", value=_recortar(f"{usuario} (ID: {usuario.id})"), inline=False)
    embed.add_field(name="Comando", value=_recortar(comando), inline=False)
    if error:
        embed.add_field(name="Error", value=_recortar(f"{type(error).__name__}: {error}"), inline=False)

    try:
        await canal_log.send(embed=embed)
    except discord.HTTPException as e:
        log.warning(f"⚠️ No se pudo enviar el log del comando: {e}")


def _recortar(texto, limite: int = 1024) -> str:
    """Valor apto para un campo de embed: nunca vacío y como máximo `limite` caracteres."""
    texto = str(texto) if texto not in (None, "") else "—"
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"

MIN_SEGUNDOS_SALIDA = 60     # al salir de voz se registra si estuvo al menos 1 minuto (y no estaba solo)
MIN_SEGUNDOS_CAMBIO = 300    # al cambiar de canal, si estuvo al menos 5 minutos en el anterior


async def member_join_handle(member, before, after):
    """Registro de voz (on_voice_state_update): cuánto estuvo alguien en un canal y con quién."""
    ahora = datetime.now(timezone.utc)
    if before.channel is None and after.channel is not None:          # entra en voz
        tiempos_entrada[member.id] = ahora
        return
    if before.channel is None or before.channel == after.channel:      # silenciar, ensordecer...: nada
        return

    inicio = tiempos_entrada.pop(member.id, None)
    if after.channel is not None:                                      # cambia de canal: empieza a contar en el nuevo
        tiempos_entrada[member.id] = ahora
    if inicio is None:
        return
    duracion = (ahora - inicio).total_seconds()
    companeros = [m.display_name for m in before.channel.members if m.id != member.id]

    if after.channel is None:                                          # sale de voz
        if duracion >= MIN_SEGUNDOS_SALIDA and companeros:
            await _registrar_voz(member, canales.OYENTES, "estuvo en un canal de voz.", discord.Color.blue(),
                                 before.channel, ("Canal", "Duración"), duracion, ", ".join(companeros))
    elif duracion >= MIN_SEGUNDOS_CAMBIO:
        await _registrar_voz(member, canales.REGISTRO_VOZ, "cambió de canal de voz.", discord.Color.green(),
                             before.channel, ("Canal anterior", "Tiempo en canal"), duracion,
                             ", ".join(companeros) or "Estuvo solo 🗿")


async def _registrar_voz(member, nombre_canal: str, accion: str, color, canal_voz, etiquetas, duracion: float,
                         companeros_txt: str):
    canal_registro = canales.get_canal(member.guild, nombre_canal)
    if not canal_registro:
        return
    embed = discord.Embed(title="📋 Registro de voz", description=f"**{member.display_name}** {accion}",
                          color=color, timestamp=datetime.now(timezone.utc))
    embed.add_field(name=etiquetas[0], value=canal_voz.name, inline=True)
    embed.add_field(name=etiquetas[1], value=f"{int(duracion // 60)}m {int(duracion % 60)}s", inline=True)
    embed.add_field(name="Con quién estuvo", value=_recortar(companeros_txt), inline=False)
    embed.set_footer(text=f"ID Usuario: {member.id}", icon_url=member.display_avatar.url)
    try:
        await canal_registro.send(embed=embed)
    except discord.HTTPException as e:
        log.warning(f"No pude enviar el registro de voz de {member}: {e}")
