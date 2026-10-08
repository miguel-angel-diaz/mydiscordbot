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
from utils import ayuda
from utils.jugadores import enviar_comandos_a_miembro

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

async def bienvenida_y_comandos_handle(message: discord.Message):
    """Presentación en el vestíbulo con las reglas aceptadas -> pasa a miembro, recibe la bienvenida y se registra."""
    if message.author.bot or not message.guild:
        return
    canal_presentaciones = canales.get_canal(message.guild, canales.VESTIBULO)
    if not canal_presentaciones or message.channel.id != canal_presentaciones.id:
        return

    member = message.author
    roles_usuario = {role.name for role in member.roles}
    if not set(canales.ROLES_BIENVENIDA).issubset(roles_usuario):
        return  # sin los dos roles de bienvenida no sigue

    if not await _pasar_a_miembro(member):
        return
    dms_abiertos = await _enviar_bienvenida(member, roles_usuario | {canales.ROL_MIEMBRO})
    await _registrar_nuevo_miembro(message, member, roles_usuario, dms_abiertos)


async def _pasar_a_miembro(member) -> bool:
    """
    Veto -> rol 'miembro' -> quitar los de bienvenida. Devuelve False si no debe seguir (vetado o sin poder dar el rol).
    'miembro' se asigna ANTES de quitar los de bienvenida: si falla, el usuario no se queda sin roles.
    """
    guild = member.guild
    roles_bienvenida = [r for r in (canales.get_rol(guild, canales.ROL_ACEPTA_BIENVENIDA),
                                    canales.get_rol(guild, canales.ROL_ACEPTA_REGLAS)) if r in member.roles]

    # Blacklist / expulsados: se comprueba ANTES de tocar ningún rol
    if await _esta_vetado(member, guild):
        await castigar_usuario(member)
        await _quitar_roles(member, roles_bienvenida, "Vetado: no pasa a miembro")
        return False

    rol_miembro = canales.get_rol(guild, canales.ROL_MIEMBRO)
    if rol_miembro and rol_miembro not in member.roles:
        try:
            await member.add_roles(rol_miembro, reason="Aceptó reglas y bienvenida")
            log.info(f"Rol 'miembro' asignado a {member.display_name}")
        except discord.HTTPException as e:
            log.warning(f"No pude asignar el rol 'miembro' a {member.display_name}: {e}")
            return False

    await _quitar_roles(member, roles_bienvenida, "Ya obtuvo el rol 'miembro'")
    return True


async def _enviar_bienvenida(member, roles_simulados: set) -> bool:
    """DMs de bienvenida: comandos disponibles, torneos y sorteos. Devuelve si tiene los DMs abiertos."""
    comandos_disponibles = [f"!{c['comando']} - {c['descripcion']}" for c in ayuda.comandos_info()
                            if any(rol in roles_simulados for rol in c["roles_permitidos"])]
    torneos_activos = await _torneos_para_nuevo_miembro(member.guild)
    sorteos_activos = []
    canal_sorteos = canales.get_canal(member.guild, canales.SORTEOS_ACTIVOS)
    if canal_sorteos:
        async for msg in canal_sorteos.history(limit=50):
            if not msg.pinned:
                sorteos_activos.append(msg.content)

    # Si tiene los DMs cerrados se sigue: el registro se hace igualmente
    dms_abiertos = await _dm(member, f"👋 ¡Bienvenido/a al servidor, {member.display_name}! 🎉")
    if not dms_abiertos:
        return False
    for titulo, lineas, separador, color in (
        ("📋 Tus comandos disponibles", comandos_disponibles, "\n", discord.Color.green()),
        ("🎮 Torneos activos", torneos_activos[:5], "\n\n", discord.Color.blue()),       # los primeros 5
        ("🎁 Sorteos activos", sorteos_activos[:5], "\n\n", discord.Color.purple()),
    ):
        if lineas:
            await _dm(member, embed=discord.Embed(title=titulo, description=_recortar(separador.join(lineas), 4096),
                                                  color=color))
    return True


async def _registrar_nuevo_miembro(message, member, roles_usuario: set, dms_abiertos: bool):
    """Ficha en #registro-de-usuarios."""
    canal_registro = canales.get_canal(message.guild, canales.REGISTRO_USUARIOS)
    if not canal_registro:
        return
    embed = discord.Embed(title="📥 Nuevo miembro registrado", color=discord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Usuario", value=f"{member} (ID: {member.id})", inline=False)
    embed.add_field(name="Apodo en servidor", value=member.display_name, inline=False)
    embed.add_field(name="Roles asignados", value=_recortar(", ".join(roles_usuario) or "Sin roles"), inline=False)
    embed.add_field(name="Cuenta creada", value=member.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
    embed.add_field(name="Se unió al servidor", value=member.joined_at.strftime("%d/%m/%Y %H:%M:%S") if member.joined_at else "Desconocida", inline=False)
    embed.add_field(name="DMs", value="✅ Bienvenida enviada" if dms_abiertos else "⚠️ DMs cerrados: no recibió la bienvenida", inline=False)
    embed.add_field(name="Mensaje de presentación", value=_recortar(message.content or "(sin texto: solo adjuntos)"), inline=False)
    try:
        await canal_registro.send(embed=embed)
    except discord.HTTPException as e:
        log.warning(f"No pude registrar a {member} en #registro-de-usuarios: {e}")


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
            ctx = await bot.get_context(message)
            ctx.command, ctx.invoked_with = comando, comando.qualified_name
            ctx.view = StringView(resto)
            await bot.invoke(ctx)          # con comprobaciones; los errores llegan a on_command_error
        else:
            await canal_dm.send("❌ Comando cancelado.")
    except asyncio.TimeoutError:
        await canal_dm.send("⏰ Tiempo agotado. Comando cancelado automáticamente.")
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

async def _torneos_para_nuevo_miembro(guild) -> list:
    """Torneos suizos abiertos y de nivel "todos" (un miembro nuevo no es socio), por fecha de inicio."""
    from utils.torneos_estado import leer_estado   # import local: evita ciclos al cargar
    try:
        estado = await leer_estado(guild._state._get_client())
    except Exception as e:
        log.warning(f"No pude leer los torneos para la bienvenida: {e}")
        return []

    def fecha(t):
        try:
            return datetime.strptime(t.get("fecha_inicio", ""), "%d/%m/%Y")
        except ValueError:
            return datetime.max

    abiertos = [t for t in estado.get("torneos", []) if t.get("tipo") == "swiss" and t.get("estado") == "abierto"
                and str(t.get("nivel", "todos")).lower() != "socios"]
    return [f"🎮 **{t.get('nombre', 'Torneo')}** — `{t['codigo']}`\n"
            f"📋 {t.get('formato', '?')} · 📅 {t.get('fecha_inicio', 'sin fecha')}\n"
            f"👉 `!inscribir-swiss {t['codigo']}`" for t in sorted(abiertos, key=fecha)]


async def _dm(member, contenido=None, **kwargs) -> bool:
    """Envía un DM sin romper el flujo si el usuario los tiene cerrados. Devuelve si se pudo enviar."""
    try:
        await member.send(contenido, **kwargs)
        return True
    except discord.HTTPException:
        log.info(f"No pude enviar DM a {member}")
        return False


async def _quitar_roles(member, roles, motivo: str):
    if not roles:
        return
    try:
        await member.remove_roles(*roles, reason=motivo)
    except discord.HTTPException as e:
        log.warning(f"No pude quitar roles a {member.display_name}: {e}")


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
        "Lo siento pero no eres el perfil que buscamos, agradecemos tú interés pero no todo el mundo vale para The Klub,"
        "estar aquí no es un derecho, es un privilegio."
        "Buena suerte en tu camino y que vaya bien."
    )

    # Asignar rol Out (sin dejar escapar el error si faltan permisos)
    rol_out = canales.get_rol(member.guild, canales.ROL_OUT)
    if rol_out:
        try:
            await member.add_roles(rol_out, reason="Usuario en blacklist o expulsado previamente")
        except discord.HTTPException as e:
            log.warning(f"No pude asignar el rol 'Out' a {member}: {e}")

async def log_comando_handle(bot, usuario, comando, tipo, error=None, fecha=None):
    canal_log = bot.get_channel(1413079518440198206)
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

async def _esta_registrado_en_canal(guild: discord.Guild, member_id: int) -> bool:
    """Comprueba si el miembro tiene una entrada en #registro-de-usuarios."""
    canal_registro = canales.get_canal(guild, canales.REGISTRO_USUARIOS)
    if not canal_registro:
        return False

    async for msg in canal_registro.history(limit=500):
        for embed in msg.embeds:
            # Buscar en fields
            for field in embed.fields:
                if str(member_id) in (field.value or ""):
                    return True
            # Buscar en description y footer
            if embed.description and str(member_id) in embed.description:
                return True
            if embed.footer and embed.footer.text and str(member_id) in embed.footer.text:
                return True
    return False


async def member_update_handle(before: discord.Member, after: discord.Member):
    """Detecta cambios de rol y actúa en consecuencia."""
    roles_antes = {r.name for r in before.roles}
    roles_despues = {r.name for r in after.roles}

    # Si acaba de obtener el rol "miembro"
    if canales.ROL_MIEMBRO not in roles_antes and canales.ROL_MIEMBRO in roles_despues:
        await comprobar_registro_y_enviar_comandos(after)

    # Aquí puedes añadir el resto de lógica de evento_socio_handle
    await evento_socio_handle(before, after)

async def comprobar_registro_y_enviar_comandos(member: discord.Member):
    """
    Si el miembro NO está registrado en #registro-de-usuarios, le envía
    los comandos disponibles por DM.
    """
    if member.bot or not member.guild:
        return

    registrado = await _esta_registrado_en_canal(member.guild, member.id)
    if not registrado:
        log.info(f"{member.display_name} no está registrado → enviando comandos.")
        await enviar_comandos_a_miembro(member)
