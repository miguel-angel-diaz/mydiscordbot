######## admin.py #######
import discord
from datetime import datetime
import asyncio
import random
import re

from utils import dm
from utils import canales
from utils import decks
from utils.commons import borrar_mensaje_seguro, validar_canal_correcto, buscar_usuario_en_servidor, obtener_torneo_usuario, enviar_en_trozos, leer_inscritos_sorteo

# Tablón de anuncios: por ID y, si no, por nombre (ver utils/canales.py)
obtener_canal_anuncios = canales.canal_anuncios


async def _obtener_objetivo_sancion(ctx, miembro, accion: str):
    """
    Devuelve el miembro a sancionar (pidiéndolo por DM si no viene) o None si no se debe continuar.
    Nunca se puede sancionar a bots, al dueño del servidor, a admins ni a uno mismo.
    """
    author = ctx.author

    if miembro is None:
        try:
            await author.send(
                f"⚠️ Vamos a aplicar un **{accion}**.\n"
                f"¿A quién? Escribe su nombre, apodo, ID o mención tal como aparece en el servidor:"
            )
            respuesta = await dm.esperar_respuesta(ctx.bot, author, timeout=60)
        except asyncio.TimeoutError:
            await author.send(f"⏰ Tiempo agotado. Vuelve a intentarlo con `!{accion}`.")
            return None
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los mensajes en tu configuración de privacidad.")
            return None
        texto = re.sub(r"^<@!?(\d+)>$", r"\1", respuesta.content.strip())
        miembro = buscar_usuario_en_servidor(ctx.guild, texto)

    motivo = None
    if not isinstance(miembro, discord.Member):
        motivo = "No encontré a ese usuario en el servidor."
    elif miembro.bot:
        motivo = "No se puede sancionar a un bot."
    elif miembro == author:
        motivo = "No puedes sancionarte a ti mismo."
    elif miembro == ctx.guild.owner:
        motivo = "No se puede sancionar al dueño del servidor."
    elif miembro.guild_permissions.administrator or any(r.name.lower() == canales.ROL_ADMIN for r in miembro.roles):
        motivo = "No se puede sancionar a un admin."

    if motivo:
        try:
            await author.send(f"❌ {motivo}")
        except discord.Forbidden:
            pass
        return None
    return miembro


MENSAJE_OUT = (
    "Escúchame bien, campeón. No fue solo la pinta, ni que vinieras en grupo, ni que te colaras en la fila. Fue todo. "
    "La energía, la actitud, el rollo. Este sitio tiene su código, su vibra... y tú no venías ni en la misma frecuencia.\n\n"
    "Así que no, no vas a entrar. No hoy, no mañana, no el próximo eclipse lunar. "
    "Puedes venir disfrazado de unicornio o vestido en látex con lentejuelas bendecidas por los dioses del techno… "
    "pero ya cruzaste la línea.\n\n"
    "Este club no es para todos. Es para los que son. Y tú... tú simplemente no eres."
)

# !strike y !out son la misma operación con distinto rol, mensaje y registro (antes, dos copias que divergían)
SANCIONES = {
    "strike": {"rol": canales.ROL_STRIKE, "mensaje": lambda: get_mensaje_strike(),
               "motivo": "Strike manual asignado por moderador.", "hecho": "ha recibido un **Strike**", "registrar_en_blacklist": False},
    "out": {"rol": canales.ROL_OUT, "mensaje": lambda: MENSAJE_OUT,
            "motivo": "Out manual asignado por moderador.", "hecho": "ha sido expulsado de la comunidad", "registrar_en_blacklist": True},
}


async def _aplicar_sancion(ctx, miembro, accion: str):
    """Asigna el rol de la sanción, avisa al sancionado por DM y, si es un Out, lo registra en #blacklist."""
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, canales.COMANDOS, f"!{accion}"):
        return
    if not await moderador_permisos_handle(ctx):
        return
    miembro = await _obtener_objetivo_sancion(ctx, miembro, accion)
    if miembro is None:
        return

    sancion = SANCIONES[accion]
    autor = ctx.author
    rol = canales.get_rol(ctx.guild, sancion["rol"])
    if not rol:
        await autor.send(f"⚠️ El rol `{sancion['rol']}` no existe en el servidor.")    # por DM, no en el canal
        return
    if rol in miembro.roles:
        await autor.send(f"ℹ️ {miembro.mention} ya tiene el rol `{sancion['rol']}`.")
        return

    try:
        await miembro.add_roles(rol, reason=sancion["motivo"])
    except discord.Forbidden:
        await autor.send(f"❌ No tengo permisos para asignar el rol `{sancion['rol']}`. Revisa la jerarquía de roles.")
        return

    # El DM va aparte: si el sancionado tiene los DMs cerrados, la sanción ya está aplicada igualmente
    try:
        await miembro.send(sancion["mensaje"]())
    except discord.HTTPException:
        await autor.send(f"⚠️ {miembro.mention} no tiene los mensajes privados habilitados (la sanción se ha aplicado).")

    await autor.send(f"✅ {miembro.mention} {sancion['hecho']}.")
    if sancion["registrar_en_blacklist"]:
        await _registrar_en_blacklist(ctx, miembro)


async def _registrar_en_blacklist(ctx, miembro):
    """Ficha en #blacklist. El campo "ID" es el que usa la bienvenida para no dejar volver a quien recibió !out."""
    canal_info = canales.get_canal(ctx.guild, canales.BLACKLIST)
    if not canal_info:
        return
    embed = discord.Embed(title="👋 Usuario expulsado del servidor", color=discord.Color.red())
    embed.add_field(name="Nombre", value=str(miembro), inline=True)                  # antes "nombre#0" con los usuarios nuevos
    embed.add_field(name="ID", value=miembro.id, inline=True)
    embed.add_field(name="Aplicado por", value=ctx.author.mention, inline=True)
    embed.add_field(name="Fecha de creación", value=miembro.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
    embed.add_field(name="Fecha de unión", value=miembro.joined_at.strftime("%d/%m/%Y %H:%M:%S") if miembro.joined_at else "Desconocida", inline=False)
    embed.set_thumbnail(url=miembro.display_avatar.url)
    await canal_info.send(embed=embed)


async def aplicar_strike(ctx, miembro: discord.Member):
    await _aplicar_sancion(ctx, miembro, "strike")


async def aplicar_out(ctx, miembro: discord.Member):
    await _aplicar_sancion(ctx, miembro, "out")


async def eliminar_mensajes(ctx, canal: discord.TextChannel = None, cantidad: int = None, orden: str = None, incluir_fijados: bool = None):
    await borrar_mensaje_seguro(ctx)
    if not await moderador_permisos_handle(ctx):
        return

    author = ctx.author

    try:
        # Preguntas por DM si faltan datos
        if canal is None or cantidad is None or orden is None or incluir_fijados is None:
            await author.send("🧹 Vamos a eliminar mensajes. Responde a las siguientes preguntas:")

            if canal is None:
                await author.send("1️⃣ ¿En qué canal quieres borrar mensajes? Escribe el nombre exacto del canal (sin `#`):")
                respuesta_canal = await dm.esperar_respuesta(ctx.bot, author, timeout=60)
                canal_nombre = respuesta_canal.content.strip().lower()
                canal = canales.get_canal(ctx.guild, canal_nombre)
                if not canal:
                    await author.send("❌ No encontré ese canal. Asegúrate de escribir el nombre exacto.")
                    return

            if cantidad is None:
                await author.send("2️⃣ ¿Cuántos mensajes quieres eliminar? (entre 1 y 1000):")
                respuesta_cantidad = await dm.esperar_respuesta(ctx.bot, author, timeout=60)
                try:
                    cantidad = int(respuesta_cantidad.content.strip())
                except ValueError:
                    await author.send("❌ La cantidad debe ser un número entero.")
                    return

            if orden is None:
                await author.send("3️⃣ ¿Cómo quieres borrar los mensajes? Escribe `recientes` o `antiguos`:")
                respuesta_orden = await dm.esperar_respuesta(ctx.bot, author, timeout=60)
                orden = respuesta_orden.content.strip().lower()
                if orden not in ("recientes", "antiguos"):
                    await author.send("❌ Opción no válida. Usa `recientes` o `antiguos`.")
                    return

            if incluir_fijados is None:
                await author.send("4️⃣ ¿Quieres borrar también los mensajes fijados? Responde `sí` o `no`:")
                respuesta_fijados = await dm.esperar_respuesta(ctx.bot, author, timeout=60)
                incluir_fijados = dm.es_si(respuesta_fijados.content)

        if cantidad <= 0 or cantidad > 1000:
            await author.send("⚠️ La cantidad debe estar entre 1 y 1000.")
            return
        if orden not in ("recientes", "antiguos"):
            orden = "recientes"

        # Confirmación antes de borrar (es irreversible)
        await author.send(
            f"⚠️ Vas a borrar hasta **{cantidad}** mensajes de {canal.mention} "
            f"({'los más recientes' if orden == 'recientes' else 'los más antiguos'}, "
            f"{'incluidos' if incluir_fijados else 'sin'} los fijados). Esta acción no se puede deshacer. ¿Confirmas? (sí/no)"
        )
        confirmacion = await dm.esperar_respuesta(ctx.bot, author, timeout=60)
        if not dm.es_si(confirmacion.content):
            await author.send("❌ Operación cancelada. No se ha borrado nada.")
            return

        # purge borra en bloques de 100 los mensajes de menos de 14 días (y uno a uno los más antiguos);
        # con oldest_first también vale para "antiguos" (antes: uno a uno con 0,5 s de pausa, ~8 min para 1000)
        mensajes_borrados = await canal.purge(
            limit=cantidad,
            check=lambda m: incluir_fijados or not m.pinned,
            oldest_first=(orden == "antiguos"),
        )

        # ✅ Confirmación en el canal donde se lanzó el comando
        await ctx.send(
            f"✅ Se han eliminado {len(mensajes_borrados)} mensajes de {canal.mention}.",
            delete_after=5
        )

        # 🔔 Logs en #mensajes-borrados
        log_channel = canales.get_canal(ctx.guild, canales.MENSAJES_BORRADOS)
        if log_channel:
            embed = discord.Embed(
                title="🧹 Mensajes eliminados",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderador", value=f"{author.mention}", inline=True)
            embed.add_field(name="Canal", value=f"{canal.mention}", inline=True)
            embed.add_field(name="Cantidad", value=f"{len(mensajes_borrados)}", inline=True)
            embed.add_field(name="Orden", value="Recientes primero" if orden=="recientes" else "Antiguos primero", inline=True)
            embed.add_field(name="Incluye fijados", value="✅ Sí" if incluir_fijados else "❌ No", inline=True)

            # Mostrar una vista previa (máx 5 para no saturar)
            if mensajes_borrados:
                preview = "\n".join(
                    f"**{m.author}**: {m.content[:40]}{'...' if len(m.content) > 40 else ''}"
                    for m in mensajes_borrados[:5]
                )
                embed.add_field(name="Ejemplo de mensajes borrados", value=preview, inline=False)

            await log_channel.send(embed=embed)

    except asyncio.TimeoutError:
        await _avisar_admin(ctx, "⏰ Tiempo agotado. Vuelve a intentar con `!eliminar-mensajes`.")
    except discord.Forbidden:
        # Puede ser falta de permisos en el canal o DMs del admin cerrados: se avisa por donde se pueda
        await _avisar_admin(ctx, "❌ No tengo permisos para borrar mensajes en ese canal, o no puedo escribirte por DM.")
    except discord.HTTPException as e:
        await _avisar_admin(ctx, f"⚠️ Ocurrió un error al intentar borrar mensajes: {e}")


async def _avisar_admin(ctx, texto: str):
    """Avisa al admin por DM y, si tiene los DMs cerrados, en el canal (se borra a los 15 s)."""
    try:
        await ctx.author.send(texto)
    except discord.HTTPException:
        try:
            await ctx.send(texto, delete_after=15)
        except discord.HTTPException:
            pass

async def asignar_strike_automatico(ctx):
    autor = ctx.author
    servidor = ctx.guild
    rol_strike = canales.get_rol(servidor, canales.ROL_STRIKE)

    if not rol_strike:
        await ctx.send("⚠️ El rol `Strike` no existe.")
        return

    if rol_strike in autor.roles:
        await ctx.send(f"⛔ Ya tienes un strike, {autor.mention}. No puedes usar este comando.")
        return

    try:
        await autor.add_roles(rol_strike, reason="Intentó usar comando sin permiso.")
        await ctx.author.send(f"🚫 {autor.mention}, no puedes usar este comando. Has recibido un **Strike**.")
        await autor.send(get_mensaje_strike())
    except discord.Forbidden:
        await ctx.send("⚠️ No tengo permisos para asignar el rol.")
    
    
    # canal_anuncios = ctx.guild.get_channel(1387389356464934993)
    # await canal_anuncios.send(f"⚠️ Hemos decidido que {autor.mention} Permanezca una semana en el Hielo, la proxima vez le invitaremos a que abandone The Klub")

def get_mensaje_strike():
    return (
        "Oye... te lo voy a decir solo una vez.\n\n"
        "Lo que hiciste, no va con las reglas de The Klub. Aquí se viene a respetar la energía, la gente y el espacio. "
        "No te echamos hoy... pero la próxima, estás fuera sin saludo ni explicación.\n\n"
        "Este sitio no es un “vale todo”. Es un “vale lo que yo diga”.\n"
        "Y tú ya estás en tu última vida.\n\n"
        "Decide bien cuál va a ser tu siguiente movimiento."
    )

async def cerrar_peticion_handle(ctx, codigo: str = None, respuesta: str = None):
    await borrar_mensaje_seguro(ctx)
    
    if not await validar_canal_correcto(ctx, canales.PETICIONES, "!cerrar-peticion"):
        return

    if not await moderador_permisos_handle(ctx):
        return

    author = ctx.author

    try:
        if codigo is None or respuesta is None:
            await author.send("📩 Vamos a cerrar una petición. Responde a las siguientes preguntas:")

            if codigo is None:
                await author.send("1️⃣ ¿Cuál es el **código** de la petición que quieres cerrar?")
                respuesta_codigo = await dm.esperar_respuesta(ctx.bot, author, timeout=90)
                codigo = respuesta_codigo.content.strip()

            if respuesta is None:
                await author.send("2️⃣ ¿Cuál es la **respuesta** que quieres enviar al usuario?")
                respuesta_msg = await dm.esperar_respuesta(ctx.bot, author, timeout=180)
                respuesta = respuesta_msg.content.strip()

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentar con `!cerrar-peticion`.")
        return
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes por privado. Activa los DMs o vuelve a intentarlo desde el canal.")
        return

    if not codigo or not respuesta:
        await author.send("❌ El código y la respuesta no pueden estar vacíos. Cancelado.")
        return

    # Buscar mensaje original en #peticiones-de-usuarios
    canal_peticiones = canales.get_canal(ctx.guild, canales.PETICIONES)
    canal_resolucion = canales.get_canal(ctx.guild, canales.RESOLUCION_PETICIONES)

    if not canal_peticiones or not canal_resolucion:
        await author.send("❌ No se encontraron los canales `#peticiones-de-usuarios` o `#resolucion-de-peticiones`.")
        return

    mensaje_objetivo = None
    autor_id = None
    contenido_peticion = "Sin descripción disponible"
    codigo_exacto = f"`{codigo}`"

    async for mensaje in canal_peticiones.history(limit=100):
        if not mensaje.embeds:
            continue
        embed = mensaje.embeds[0]
        # description, footer y valores pueden faltar (None): no deben romper la búsqueda
        textos = [embed.description or ""] + [f.value or "" for f in embed.fields]
        if any(codigo_exacto in t for t in textos):
            mensaje_objetivo = mensaje
            pie = (embed.footer.text or "").strip() if embed.footer else ""
            autor_id = int(pie) if pie.isdigit() else None
            contenido_peticion = embed.description or contenido_peticion
            break

    if not mensaje_objetivo:
        await author.send(f"⚠️ No encontré ninguna petición abierta con el código `{codigo}`.")
        return

    # Avisar al usuario si es posible; la petición se cierra igualmente (antes quedaba abierta para siempre)
    miembro = ctx.guild.get_member(autor_id) if autor_id else None
    aviso_usuario = "✅ Respuesta enviada al usuario por DM."
    if not miembro:
        aviso_usuario = "⚠️ El autor ya no está en el servidor (o no se pudo identificar): no se le ha podido avisar."
    else:
        try:
            await miembro.send(
                f"📬 Tu petición con código `{codigo}` ha sido **cerrada**.\n"
                f"💬 Respuesta del equipo:\n>>> {respuesta}"
            )
        except discord.HTTPException:
            aviso_usuario = "⚠️ El autor tiene los DMs cerrados: no se le ha podido enviar la respuesta."

    try:
        await mensaje_objetivo.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        await author.send("⚠️ No tengo permisos para eliminar mensajes en `#peticiones-de-usuarios`.")
        return

    # 📦 Publicar resumen en #resolucion-de-peticiones
    embed_resolucion = discord.Embed(title="📌 Petición Resuelta", color=discord.Color.green())
    embed_resolucion.add_field(name="🔢 Código de solicitud", value=codigo_exacto, inline=False)
    embed_resolucion.add_field(name="👤 Usuario solicitante",
                               value=miembro.mention if miembro else (f"<@{autor_id}>" if autor_id else "Desconocido"),
                               inline=True)
    embed_resolucion.add_field(name="🔧 Cerrada por", value=ctx.author.mention, inline=True)
    embed_resolucion.add_field(name="📝 Contenido original", value=contenido_peticion[:1024], inline=False)
    embed_resolucion.add_field(name="✅ Resolución", value=respuesta[:1024], inline=False)
    if autor_id:
        embed_resolucion.set_footer(text=f"ID del solicitante: {autor_id}")
    await canal_resolucion.send(embed=embed_resolucion)

    await author.send(f"✅ Petición `{codigo}` cerrada y registrada en #resolucion-de-peticiones.\n{aviso_usuario}")

async def sorteo_torneo_handle(ctx, codigo_torneo: str, premio: str = "Premio del sorteo"):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, canales.COMANDOS, "!sorteo-torneo"):
        return
    if not await moderador_permisos_handle(ctx):
        return
    
    if codigo_torneo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del torneo.\n"
                "Por favor, respóndeme con el **código del torneo** del que quieres hacer el sorteo. Tienes 60 segundos."
            )

            respuesta = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60.0)
            codigo_torneo = respuesta.content.strip()

            if not codigo_torneo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!sorteo-torneo <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    # Participantes: inscritos del torneo en el estado del bot (ya no se consulta Challonge)
    from utils.torneos_estado import obtener_torneo_estado
    torneo = await obtener_torneo_estado(ctx.bot, codigo_torneo)
    if not torneo:
        await ctx.author.send(f"❌ El torneo `{codigo_torneo}` no existe.")
        return
    candidatos = [m for m in (ctx.guild.get_member(int(uid)) for uid in torneo.get("inscritos_ids", [])) if m]

    if not candidatos:
        await ctx.author.send("⚠️ No hay participantes válidos (inscritos que sigan en el servidor) para el sorteo.")
        return

    # Elegir ganador aleatorio
    ganador = random.choice(candidatos)

    # Mensaje al moderador
    try:
        await ctx.author.send(
            f"🎉 Sorteo realizado para el torneo `{codigo_torneo}`\n"
            f"🏆 Ganador: {ganador.display_name} ({ganador.mention})\n"
            f"🎁 Premio: {premio}"
        )
    except discord.Forbidden:
        await ctx.send("⚠️ No pude enviarte mensaje privado con el resultado.")

    # Mensaje al ganador
    try:
        await ganador.send(
            f"🎉 ¡Felicidades! Has sido seleccionado en un sorteo del torneo `{codigo_torneo}`.\n"
            f"🎁 Te ha tocado: {premio}"
        )
    except discord.Forbidden:
        await ctx.send(f"⚠️ No pude enviar mensaje privado a {ganador.display_name}.")

async def moderador_permisos_handle(ctx, only_check: bool = False) -> bool:
    autor = ctx.author
    servidor = ctx.guild
    if servidor is None:
        # Comando usado por DM: los comandos de admin solo funcionan en el servidor
        if not only_check:
            try:
                await autor.send("❌ Este comando solo se puede usar en el servidor.")
            except discord.Forbidden:
                pass
        return False
    es_dueno = autor == servidor.owner
    rol_moderador = canales.get_rol(servidor, canales.ROL_ADMIN)
    # Mismo criterio que comando_roles_permitidos: dueño, rol "admin" o permiso de administrador
    permisos = getattr(autor, "guild_permissions", None)
    tiene_permiso = (
        es_dueno
        or (rol_moderador is not None and rol_moderador in autor.roles)
        or bool(permisos and permisos.administrator)
    )

    if not tiene_permiso:
        if not only_check:
            # await asignar_strike_automatico(ctx)
            await ctx.author.send("❌ No tienes permisos de moderador.")
            pass
        return False

    return True

async def nuevo_sorteo_handle(ctx, *, args: str = None):
    await borrar_mensaje_seguro(ctx)

    if not await moderador_permisos_handle(ctx):
        return

    if not await validar_canal_correcto(ctx, canales.COMANDOS, "!nuevo_sorteo"):
        return

    author = ctx.author

    try:
        if not args or len([p.strip() for p in args.split("|")]) < 4:
            await author.send("📩 Vamos a crear un nuevo sorteo. Responde a las siguientes preguntas:")

            await author.send("1️⃣ ¿Cuál es el **código** del sorteo?")
            codigo_msg = await dm.esperar_respuesta(ctx.bot, author, timeout=90)
            codigo = codigo_msg.content.strip()

            await author.send("2️⃣ ¿Cuál es la **fecha límite** del sorteo?")
            fecha_msg = await dm.esperar_respuesta(ctx.bot, author, timeout=90)
            fecha = fecha_msg.content.strip()

            await author.send("3️⃣ ¿Cuál es el **regalo** del sorteo?")
            regalo_msg = await dm.esperar_respuesta(ctx.bot, author, timeout=90)
            regalo = regalo_msg.content.strip()

        else:
            _, codigo, fecha, regalo = [p.strip() for p in args.split("|")]

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentarlo con `!nuevo_sorteo`.")
        return
    except discord.Forbidden:
        await ctx.send("❌ No puedo enviarte mensajes por privado. Activa los DMs o vuelve a intentarlo desde el canal.")
        return

    # Crear el embed para el canal de anuncios
    embed = discord.Embed(
        title="🎁 ¡Nuevo Sorteo Activo!",
        description=f"**Código:** `{codigo}`\n**Fecha límite:** {fecha}\n**Regalo:** {regalo}",
        color=discord.Color.gold()
    )
    embed.set_footer(text="¡Participa antes de que finalice el sorteo!")

    canal_anuncios = obtener_canal_anuncios(ctx.guild)
    if canal_anuncios:
        await canal_anuncios.send(embed=embed)
    else:
        await author.send("⚠️ No encontré el canal de anuncios (`#📰-tablon‐anuncios`).")

    canal_sorteos_activos = canales.get_canal(ctx.guild, canales.SORTEOS_ACTIVOS)
    if canal_sorteos_activos:
        await canal_sorteos_activos.send(f"🎉 **Sorteo activo:** `{codigo}`\n📅 **Fecha:** {fecha}\n🎁 **Regalo:** {regalo}")
        await author.send(f"🎉 **se ha creado un nuevo sorteo con el codigo:** `{codigo}`")
    else:
        await author.send("⚠️ No encontré el canal `#sorteos-activos`.")

async def realizar_sorteo_handle(ctx, codigo: str):
    await borrar_mensaje_seguro(ctx)

    if not await moderador_permisos_handle(ctx):
        return

    if not await validar_canal_correcto(ctx, canales.COMANDOS, "!realizar-sorteo"):
        return
    
    if codigo is None:
        try:
            await ctx.author.send(
                "📩 No escribiste el código del Sorteo.\n"
                "Por favor, respóndeme con el **código del sorteo** del que quieres hacer el sorteo. Tienes 60 segundos."
            )

            respuesta = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60.0)
            codigo = respuesta.content.strip()

            if not codigo:
                await ctx.author.send("❌ El código no puede estar vacío. Cancelo la inscripción.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!sorteo-torneo <código_torneo>`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")
            return

    canal_inscritos = canales.get_canal(ctx.guild, canales.INSCRITOS_SORTEOS)
    canal_sorteos_activos = canales.get_canal(ctx.guild, canales.SORTEOS_ACTIVOS)
    canal_publicacion = obtener_canal_anuncios(ctx.guild)

    # Todos los canales se comprueban ANTES de notificar al ganador o borrar nada
    if not canal_inscritos or not canal_sorteos_activos or not canal_publicacion:
        await ctx.author.send(
            "❌ Faltan canales para realizar el sorteo (`#inscritos-sorteos`, `#sorteos-activos` "
            "o el de anuncios). No se ha hecho nada."
        )
        return

    # Inscritos válidos (misma lectura que !inscribirse-sorteo; solo quien sigue en el servidor)
    inscritos = [m for m in (ctx.guild.get_member(uid) for uid in await leer_inscritos_sorteo(canal_inscritos, codigo)) if m]

    if not inscritos:
        await ctx.send(f"❌ No hay inscritos para el sorteo `{codigo}`.")
        return

    # Escoger ganador
    ganador_user = random.choice(inscritos)

    # Enviar mensajes privados
    try:
        await ganador_user.send(f"🎉 ¡Has ganado el sorteo `{codigo}`! Felicidades.")
        await ctx.author.send(f"✅ El ganador del sorteo `{codigo}` es {ganador_user.mention}. Se le ha notificado por privado.")
    except discord.Forbidden:
        await ctx.send(f"⚠️ No pude enviar mensaje al ganador ({ganador_user.mention}), tiene los DMs cerrados.")

    # Eliminar todos los inscritos de ese sorteo con purge()
    eliminados_msgs = await canal_inscritos.purge(
        limit=None,
        check=lambda m: f"| {codigo} |" in m.content  # asegura que el código esté en el mensaje
    )
    eliminados = len(eliminados_msgs)

    # Eliminar el sorteo del canal de sorteos activos
    await canal_sorteos_activos.purge(
        limit=100,
        check=lambda m: m.content.startswith("🎉") and f"`{codigo}`" in m.content   # código exacto: "S1" no borra "S10"
    )

    await canal_publicacion.send(f"✅ Sorteo `{codigo}` finalizado. {eliminados} inscritos eliminados y sorteo activo eliminado.\n🏆 ✅ El ganador del sorteo `{codigo}` es {ganador_user.mention}.")


async def nuevo_comunicado_handle(ctx, mensaje: str = None):
    await borrar_mensaje_seguro(ctx)
    
    if not await moderador_permisos_handle(ctx):
        return

    canal = obtener_canal_anuncios(ctx.guild)
    if not canal:
        await ctx.author.send("❌ No encontré el canal de anuncios (`#📰-tablon‐anuncios`). No se ha enviado nada.")
        return

    # Si no hay mensaje, pedimos por DM
    if not mensaje:
        try:
            await ctx.author.send(
                "📩 No escribiste el Mensaje para el canal 📰-tablon‐anuncios.\n"
                "Por favor, respóndeme con el mensaje que quieras transmitir. Tienes 60 segundos."
            )

            respuesta = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60.0)
            mensaje = respuesta.content.strip()

            if not mensaje:
                await ctx.author.send("❌ El mensaje no puede estar vacío. Cancelado.")
                return

        except asyncio.TimeoutError:
            await ctx.author.send("⏰ Tiempo agotado. Intenta de nuevo con `!nuevo_comunicado mensaje`.")
            return
        except discord.Forbidden:
            await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs.")
            return

    # Enviar comunicado al canal con @everyone
    embed = discord.Embed(
        title="📢 Comunicado",
        description=mensaje,
        color=0x00ffcc
    )

    await canal.send("@everyone", embed=embed)
    await ctx.author.send(f"✅ Comunicado enviado a {canal.mention}")

async def eliminar_decks_handle(ctx, codigo_torneo: str = None):
    """
    Permite eliminar decks de un torneo. Si no se proporciona código, pide al usuario seleccionarlo.
    Se puede eliminar decks individuales o todos a la vez.
    """
    await borrar_mensaje_seguro(ctx)
    
    if not await moderador_permisos_handle(ctx):
        return

    # 1️⃣ Obtener código de torneo si no se proporcionó
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(ctx, "📋 Debes seleccionar un torneo para eliminar listas.")
        if not codigo_torneo:
            return await ctx.send("❌ No se seleccionó ningún torneo. Operación cancelada.")

    # 2️⃣ Decks de ESE torneo (código exacto, canal entero; lector común de utils/decks.py)
    if not decks.canal_decks(ctx.guild):
        return await ctx.send("❌ No encontré el canal `submitted-decks` en este servidor.")
    decks_encontrados = await decks.listar(ctx.guild, codigo_torneo=codigo_torneo)

    if not decks_encontrados:
        return await ctx.author.send(f"📭 No se encontraron decks para el torneo `{codigo_torneo}`.")

    # 4️⃣ Mostrar lista de decks para eliminar
    texto = f"📋 Decks encontrados para el torneo `{codigo_torneo}`:\n"
    for idx, deck in enumerate(decks_encontrados, start=1):
        texto += f"{idx}. {deck['nombre_deck']} → {deck['archetype']} (Jugador: {deck['jugador']})\n"

    try:
        await enviar_en_trozos(ctx.author, texto)
    except discord.Forbidden:
        return await ctx.send("❌ No puedo enviarte mensajes privados. Activa los DMs para continuar.")

    # 5️⃣ Pedir selección
    await ctx.author.send(
        "✏️ Responde con los **números separados por coma** de los decks a eliminar (ej: 1,3,4) "
        "o escribe `todos` para eliminar todos los decks. Tienes 120 segundos."
    )

    try:
        respuesta = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=120)
        contenido = respuesta.content.strip().lower()

        if contenido in ("todos", "all"):
            # Seleccionar todos los decks
            to_delete = [deck["mensaje"] for deck in decks_encontrados]
        else:
            # Selección por números separados por coma (sin repetidos: no se borra dos veces el mismo)
            indices = sorted({int(x.strip()) - 1 for x in contenido.split(",") if x.strip()})
            to_delete = [decks_encontrados[i]["mensaje"] for i in indices if 0 <= i < len(decks_encontrados)]

        if not to_delete:
            return await ctx.author.send("❌ Ningún número corresponde a un deck de la lista. Operación cancelada.")

        # 6️⃣ Confirmar antes de borrar
        await ctx.author.send(
            f"⚠️ Vas a eliminar **{len(to_delete)}** deck(s) del torneo `{codigo_torneo}`. "
            "Esta acción no se puede deshacer. ¿Confirmas? (sí/no)"
        )
        confirmacion = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirmacion.content):
            return await ctx.author.send("❌ Operación cancelada. No se ha eliminado ningún deck.")

    except ValueError:
        return await ctx.author.send("❌ Entrada inválida. Debes poner números separados por coma o 'todos'.")
    except asyncio.TimeoutError:
        return await ctx.author.send("⏰ Tiempo agotado. Operación cancelada.")

    # 7️⃣ Borrar
    eliminados = 0
    for msg in to_delete:
        try:
            await msg.delete()
            eliminados += 1
        except discord.Forbidden:
            await ctx.author.send(f"❌ No tengo permisos para eliminar el mensaje de {msg.author}.")
        except discord.HTTPException:
            await ctx.author.send(f"❌ No se pudo eliminar el mensaje de {msg.author}.")

    await ctx.author.send(f"✅ Eliminados {eliminados} decks del torneo `{codigo_torneo}`.")


async def actualizar_web_handle(ctx):
    """Regenera la caché de torneos de la web. Solo admins."""
    await borrar_mensaje_seguro(ctx)

    if not await moderador_permisos_handle(ctx):
        return

    await ctx.author.send("🔄 Actualizando cache de torneos...")
    guild = ctx.guild
    from utils.api import regenerar_cache  # import local: evita ciclos
    payload = await regenerar_cache(guild)
    await ctx.author.send(f"✅ Cache actualizada con {len(payload['torneos'])} torneo(s).")
