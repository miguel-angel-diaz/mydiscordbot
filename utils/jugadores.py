import discord
from datetime import datetime, timedelta
import re

from utils.resultados import generar_embed_clasificacion, calcular_clasificacion, extraer_partidas, guardar_resultado
from utils.torneos import generar_codigo_unico


MAX_ERRORES = 3
TIEMPO_LIMITE_MINUTOS = 10
intentos_fallidos = {}  # Guardado temporal por usuario

async def agendar_partida_handle(ctx, fecha, hora, jugador1, _vs, jugador2):
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")

    if not await validar_canal_correcto(ctx, "agenda", "!agendar-partida"):
        return

    errores = []

    if not fecha:
        errores.append("• Falta la **fecha**. Formato esperado: `dd/mm/yyyy`")
    else:
        try:
            datetime.strptime(fecha, "%d/%m/%Y")
        except ValueError:
            errores.append(f"• Fecha inválida (`{fecha}`). Usa el formato `dd/mm/yyyy`")

    if not hora:
        errores.append("• Falta la **hora**. Formato esperado: `hh:mm`")
    else:
        try:
            datetime.strptime(hora, "%H:%M")
        except ValueError:
            errores.append(f"• Hora inválida (`{hora}`). Usa el formato `hh:mm`")

    if not jugador1:
        errores.append("• Falta el **jugador 1** (`@mención`)")
    if not jugador2:
        errores.append("• Falta el **jugador 2** (`@mención`)")

    if _vs is None or _vs.lower() != "vs":
        errores.append("• Falta la palabra clave **vs** entre los jugadores")

    if errores:
        mensaje = "❌ Comando incorrecto. Revisa los siguientes errores:\n\n"
        mensaje += "\n".join(errores)
        mensaje += "\n\n✅ **Ejemplo correcto:** `!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`"
        await ctx.author.send(mensaje)
        await manejar_error_de_agendamiento(ctx)
        return

    canal_destino = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal_destino:
        await ctx.author.send("❌ No se encontró el canal `#partidos-agendados`.")
        return

    mensaje_agendado = (
        f"📅 [EVENTO] {fecha} {hora} | {jugador1.mention} vs {jugador2.mention} | "
        f"Agendado por {ctx.author.mention}"
    )

    await canal_destino.send(mensaje_agendado)

    # Mensajes privados a los involucrados
    mensaje_privado = (
        f"✅ Se ha agendado una partida para el `{fecha}` a las `{hora}` entre {jugador1.mention} y {jugador2.mention}."
        f"\npuedes consultar en el canal de  `#agenda` con el comando `!partidas-pendientes` para más detalles."
    )

    await ctx.author.send("✅ Has agendado la partida correctamente.")
    
    # Enviar mensajes privados a los jugadores si son usuarios del servidor
    for jugador in (jugador1, jugador2):
        try:
            await jugador.send(mensaje_privado)
        except discord.Forbidden:
            await ctx.author.send(f"⚠️ No se pudo enviar mensaje privado a {jugador.mention}.")

    if ctx.author.id in intentos_fallidos:
        del intentos_fallidos[ctx.author.id]

async def manejar_error_de_agendamiento(ctx):
    ahora = datetime.now()
    usuario_id = ctx.author.id

    intentos = intentos_fallidos.get(usuario_id, [])
    intentos = [t for t in intentos if ahora - t < timedelta(minutes=TIEMPO_LIMITE_MINUTOS)]
    intentos.append(ahora)
    intentos_fallidos[usuario_id] = intentos

    intentos_restantes = MAX_ERRORES - len(intentos)

    mensaje = (
        f"❌ **Comando incorrecto.** Asegúrate de usar este formato:\n"
        "`!agendar-partida dd/mm/yyyy hh:mm @Jugador1 vs @Jugador2`\n"
        f"🔄 Ejemplo: `!agendar-partida 07/07/2025 23:45 @Fizban vs @sete`\n\n"
        f"⚠️ Tienes {intentos_restantes} intento(s) antes de recibir el rol **Strike**."
    )

    await ctx.send(mensaje)

    if len(intentos) >= MAX_ERRORES:
        rol_strike = discord.utils.get(ctx.guild.roles, name="Strike")
        if rol_strike and rol_strike not in ctx.author.roles:
            await ctx.author.add_roles(rol_strike)
            await ctx.send(f"🚫 {ctx.author.mention}, has cometido demasiados errores. Se te ha asignado el rol **Strike**.")

async def eventos_hoy_handle(ctx):
    # Intentar eliminar el mensaje del canal público
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")
    
    # Validar canal correcto
    if not await validar_canal_correcto(ctx, "partidos-agendados", "!eventos-hoy"):
        return

    canal = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal:
        await ctx.author.send("❌ No se encontró el canal `#partidos-agendados`.")
        return

    hoy = datetime.now().date()
    eventos_hoy = []

    patron = re.compile(
        r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
    )

    async for mensaje in canal.history(limit=100):
        if not mensaje.content.startswith("📅 [EVENTO]"):
            continue

        match = patron.search(mensaje.content)
        if not match:
            continue

        fecha_str, hora_str, jugador1, jugador2 = match.groups()
        try:
            fecha_completa = datetime.strptime(f"{fecha_str} {hora_str}", "%d/%m/%Y %H:%M")
        except ValueError:
            continue

        if fecha_completa.date() == hoy:
            eventos_hoy.append((fecha_completa.strftime("%H:%M"), jugador1.strip(), jugador2.strip()))

    if not eventos_hoy:
        await ctx.author.send("📭 No hay eventos agendados para hoy.")
        return

    embed = discord.Embed(title="📅 Partidas de hoy", color=discord.Color.green())
    for hora, jugador1, jugador2 in sorted(eventos_hoy):
        embed.add_field(name=hora, value=f"{jugador1} vs {jugador2}", inline=False)

    await ctx.author.send(embed=embed)


async def inscribirse_handler(ctx, codigo=None):
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")

    if not await validar_canal_correcto(ctx, "inscripciones", "!inscribirse"):
        return

    if not codigo:
        await ctx.author.send("❌ Debes proporcionar un código. Ejemplo: `!inscribirse CZI1F6`")
        return

    codigo = codigo.upper()
    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-en-torneos")

    if not canal_torneos or not canal_inscritos:
        await ctx.author.send("❌ No se encuentran los canales necesarios.")
        return

    patron = re.compile(
        r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` \| `(.+?)` \| código: `(\w{6})`",
        re.IGNORECASE
    )
    torneo = None

    async for mensaje in canal_torneos.history(limit=100):
        match = patron.search(mensaje.content)
        if match and match.group(6).upper() == codigo:
            nombre, fecha, cupo, tipo, acceso, _ = match.groups()
            torneo = {
                "nombre": nombre,
                "fecha": fecha,
                "cupo": int(cupo),
                "tipo": tipo,
                "acceso": acceso,
                "codigo": codigo
            }
            break

    if not torneo:
        await ctx.author.send(f"❌ No se encontró ningún torneo con el código `{codigo}`.")
        return

    # ✅ Validación de acceso por roles
    acceso = torneo["acceso"].lower()
    roles_usuario = [r.name.lower() for r in ctx.author.roles]

    tiene_acceso = False
    if acceso == "todos":
        tiene_acceso = True
    elif acceso == "socio":
        tiene_acceso = any(r in roles_usuario for r in ["socio", "second-chance-socio"])
    elif acceso == "miembro":
        tiene_acceso = any(r in roles_usuario for r in ["miembro", "second-chance-miembro"])

    if not tiene_acceso:
        await ctx.author.send(
            f"🚫 El torneo `{torneo['nombre']}` es exclusivo para `{torneo['acceso']}`.\n"
            f"No tienes los permisos necesarios para inscribirte."
        )
        return

    # ✅ Comprobación de duplicado e inscripción
    ya_inscrito = False
    total_inscritos = 0

    async for mensaje in canal_inscritos.history(limit=200):
        if mensaje.content.startswith("🎟️ Inscrito") and f"`{codigo}`" in mensaje.content:
            total_inscritos += 1
            if ctx.author.mention in mensaje.content:
                ya_inscrito = True
                break

    if ya_inscrito:
        await ctx.author.send(f"ℹ️ Ya estás inscrito en el torneo `{torneo['nombre']}`.")
        return

    if total_inscritos >= torneo["cupo"]:
        await ctx.author.send(f"🚫 El torneo `{torneo['nombre']}` ya alcanzó su cupo máximo.")
        return

    numero = total_inscritos + 1
    mensaje = (
        f"🎟️ Inscrito #{numero} | {torneo['nombre']} (`{torneo['codigo']}`) | <@{ctx.author.id}>"
    )
    await canal_inscritos.send(mensaje)
    await ctx.author.send(f"✅ Te has inscrito correctamente en `{torneo['nombre']}`.")

    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios-torneos")
    if canal_anuncios:
        plazas_restantes = torneo["cupo"] - numero
        mensaje_anuncio = (
            f"📢 {ctx.author.mention} se ha inscrito al torneo `{torneo['nombre']}` "
            f"(`{torneo['codigo']}`). Quedan **{plazas_restantes}** plazas disponibles."
        )
        await canal_anuncios.send(mensaje_anuncio)

async def desinscribirse_handler(ctx, codigo=None):
    try:
        await ctx.message.delete()
    except (discord.NotFound, discord.Forbidden):
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")

    if not await validar_canal_correcto(ctx, "inscripciones", "!desinscribirse"):
        return

    if not codigo:
        try:
            await ctx.author.send("❌ Debes indicar el código del torneo. Ejemplo: `!desinscribirse CZI1F6`")
        except discord.Forbidden:
            pass
        return

    codigo = codigo.upper()
    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-en-torneos")
    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios-torneos")

    if not canal_inscritos or not canal_torneos:
        try:
            await ctx.author.send("❌ No se encuentran los canales necesarios.")
        except discord.Forbidden:
            pass
        return

    # Recuperar datos del torneo
    patron = re.compile(
        r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` \| `(.+?)` \| código: `(\w{6})`",
        re.IGNORECASE
    )
    torneo = None

    async for mensaje in canal_torneos.history(limit=100):
        match = patron.search(mensaje.content)
        if match and match.group(6).upper() == codigo:
            nombre, fecha, cupo, tipo, acceso, _ = match.groups()
            torneo = {
                "nombre": nombre,
                "fecha": fecha,
                "cupo": int(cupo),
                "tipo": tipo,
                "acceso": acceso,
                "codigo": codigo
            }
            break

    if not torneo:
        try:
            await ctx.author.send(f"❌ No se encontró el torneo con código `{codigo}`.")
        except discord.Forbidden:
            pass
        return

    # Buscar mensajes de inscripción a eliminar
    mensajes_a_borrar = []

    async for mensaje in canal_inscritos.history(limit=200):
        if (
            mensaje.author == ctx.guild.me and
            ctx.author.mention in mensaje.content and
            f"`{codigo}`" in mensaje.content
        ):
            mensajes_a_borrar.append(mensaje)

    if not mensajes_a_borrar:
        try:
            await ctx.author.send(f"ℹ️ No estás inscrito en el torneo con código `{codigo}`.")
        except discord.Forbidden:
            pass
        return

    for msg in mensajes_a_borrar:
        try:
            await msg.delete()
        except discord.Forbidden:
            continue

    try:
        await ctx.author.send(f"✅ Has sido desinscrito del torneo con código `{codigo}`.")
    except discord.Forbidden:
        pass

    # ✅ Recuento de inscritos restantes
    total_inscritos_restantes = 0
    async for mensaje in canal_inscritos.history(limit=200):
        if mensaje.content.startswith("🎟️ Inscrito") and f"`{codigo}`" in mensaje.content:
            total_inscritos_restantes += 1

    plazas_disponibles = torneo["cupo"] - total_inscritos_restantes

    if canal_anuncios:
        mensaje_anuncio = (
            f"📢 {ctx.author.mention} se ha **desinscrito** del torneo `{torneo['nombre']}` "
            f"(`{torneo['codigo']}`). Quedan **{plazas_disponibles}** plazas disponibles."
        )
        await canal_anuncios.send(mensaje_anuncio)
    

async def ver_inscritos_handler(ctx, codigo=None):
       # Intentar eliminar el mensaje del canal público
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")
    
    # Validar canal correcto
    if not await validar_canal_correcto(ctx, "inscripciones", "!ver-inscritos"):
        return
    if not codigo:
        await ctx.send("❌ Debes indicar el código del torneo. Ejemplo: `!ver-inscritos CZI1F6`")
        return

    codigo = codigo.upper()
    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-en-torneos")
    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")

    patron_torneo = re.compile(r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` \| código: `(\w{6})`", re.IGNORECASE)
    torneo = None

    async for mensaje in canal_torneos.history(limit=100):
        match = patron_torneo.search(mensaje.content)
        if match and match.group(5).upper() == codigo:
            nombre, fecha, cupo, tipo, _ = match.groups()
            torneo = {"nombre": nombre, "fecha": fecha, "cupo": int(cupo)}
            break

    if not torneo:
        await ctx.send(f"❌ No se encontró el torneo con el código `{codigo}`.")
        return

    inscritos = []
    patron_inscrito = re.compile(r"🎟️ Inscrito #\d+ en `(.+?)` \(`(\w{6})`\)\n👤 <@!?(\d+)>", re.IGNORECASE)

    async for mensaje in canal_inscritos.history(limit=200):
        match = patron_inscrito.search(mensaje.content)
        if match and match.group(2).upper() == codigo:
            miembro = ctx.guild.get_member(int(match.group(3)))
            inscritos.append(miembro.mention if miembro else f"<@{match.group(3)}>")

    if not inscritos:
        await ctx.send(f"ℹ️ No hay jugadores inscritos en `{torneo['nombre']}`.")
        return

    embed = discord.Embed(
        title=f"🎯 Inscritos en {torneo['nombre']}",
        description=f"🗓️ Fecha límite: `{torneo['fecha']}`\n🔢 Cupo: {len(inscritos)}/{torneo['cupo']}",
        color=discord.Color.purple()
    )
    for i, jugador in enumerate(inscritos, start=1):
        embed.add_field(name=f"#{i}", value=jugador, inline=False)

    await ctx.send(embed=embed)

# TORNEOS ACTIVOS
async def torneos_activos_handle(ctx):
    canal = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    if not canal:
        await ctx.send("❌ No se encontró el canal `#torneos-activos`.")
        return

    hoy = datetime.now().date()
    patron = re.compile(r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` creado por (.+)", re.IGNORECASE)

    torneos = []

    async for mensaje in canal.history(limit=100):
        match = patron.search(mensaje.content)
        if match:
            nombre, fecha_str, cantidad, tipo, autor = match.groups()
            try:
                fecha = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                if fecha >= hoy:
                    torneos.append((fecha_str, nombre, tipo, cantidad, autor))
            except ValueError:
                continue

    if not torneos:
        await ctx.send("📭 No hay torneos activos para hoy o más adelante.")
        return

    embed = discord.Embed(title="🏆 Torneos activos", color=discord.Color.purple())
    for fecha, nombre, tipo, cantidad, autor in sorted(torneos):
        embed.add_field(
            name=f"{nombre} ({fecha})",
            value=f"• Tipo: `{tipo}`\n• Jugadores: `{cantidad}`\n• Creador: {autor}",
            inline=False
        )

    await ctx.send(embed=embed)

# REPORTAR RESULTADO
async def reportar_resultado_handle(ctx, jugador1, resultado, jugador2, codigo):
    if ctx.channel.name != "resultados":
        return await ctx.send("❌ Este comando solo puede usarse en el canal `#resultados`.")

    errores = []
    if not jugador1:
        errores.append("• Falta **Jugador 1** (`@mención`).")
    if not resultado or not re.match(r"^\d+-\d+$", resultado):
        errores.append("• Resultado inválido. Usa formato como `2-1`, `1-1`, etc.")
    if not jugador2:
        errores.append("• Falta **Jugador 2** (`@mención`).")
    if not codigo:
        errores.append("• Falta el **código del torneo**.")

    if errores:
        return await ctx.send("❌ Errores en el comando:\n" + "\n".join(errores) + "\n\n✅ Ejemplo: `!reportar-resultado @Jugador1 2-1 @Jugador2 ABC123`")

    codigo = codigo.upper()
    canal_resultados = discord.utils.get(ctx.guild.text_channels, name="resultados-de-partidas")
    canal_clasificacion = discord.utils.get(ctx.guild.text_channels, name="clasificaciones")

    if not canal_resultados or not canal_clasificacion:
        return await ctx.send("❌ No se encontraron los canales requeridos.")

    await guardar_resultado(ctx, canal_resultados, jugador1, resultado, jugador2, codigo)

    partidas = await extraer_partidas(canal_resultados, codigo)
    if len(partidas) < 1:
        return await ctx.send("⚠️ No hay suficientes partidas registradas para calcular clasificación.")

    clasificacion = calcular_clasificacion(partidas, ctx.guild)
    embed = generar_embed_clasificacion(clasificacion, codigo)

    await canal_clasificacion.send(embed=embed)
    await ctx.send("✅ Resultado registrado y clasificación actualizada.")

async def partidas_pendientes_handle(ctx):
    # Intentamos borrar el mensaje público para que sea todo privado
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass
    
      # Validar canal correcto
    if not await validar_canal_correcto(ctx, "agenda", "!partidas-pendientes"):
        return

    canal_partidos = discord.utils.get(ctx.guild.text_channels, name="partidos-agendados")
    if not canal_partidos:
        await ctx.author.send("❌ No se encontró el canal `#partidos-agendados` en este servidor.")
        return

    patron = re.compile(
        r"\[EVENTO\]\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+\|\s+(.+?)\s+vs\s+(.+?)\s+\|"
    )

    partidas_usuario = []

    async for mensaje in canal_partidos.history(limit=200):
        if not mensaje.content.startswith("📅 [EVENTO]"):
            continue

        match = patron.search(mensaje.content)
        if not match:
            continue

        fecha_str, hora_str, jugador1_text, jugador2_text = match.groups()

        # Comprobar si el usuario está mencionado en el mensaje
        if ctx.author.mention in mensaje.content:
            partidas_usuario.append(f"{fecha_str} {hora_str}: {jugador1_text} vs {jugador2_text}")

    if not partidas_usuario:
        await ctx.author.send("ℹ️ No tienes partidas pendientes agendadas.")
        return

    mensaje_respuesta = "📅 **Tus partidas pendientes:**\n" + "\n".join(partidas_usuario)
    await ctx.author.send(mensaje_respuesta)

async def validar_canal_correcto(ctx, canal_valido: str, comando: str):
    """
    Verifica si el comando fue usado en el canal correcto. Si no lo fue:
    - Manda un mensaje privado al autor.
    - Elimina el mensaje del canal si es posible.
    - Retorna False para indicar que no se debe continuar.
    """
    if ctx.channel.name != canal_valido:
        try:
            await ctx.author.send(
                f"❌ El comando `{comando}` solo se puede usar en el canal `#{canal_valido}`.\n"
                f"Por favor, usa el comando allí para que funcione correctamente."
            )
        except discord.Forbidden:
            pass  # Usuario con DMs cerrados

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass  # Bot sin permisos para borrar mensajes

        return False
    
    return True

async def nueva_peticion_handle(ctx, descripcion):
    # Eliminar mensaje original si es posible
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")

    # Validar descripción
    if not descripcion:
        try:
            await ctx.author.send(
                "❌ Debes incluir una descripción.\n"
                "Ejemplo: `!nueva-peticion Agregar soporte para torneos dobles.`"
            )
        except discord.Forbidden:
            await ctx.send("❌ Debes incluir una descripción. Y además, no puedo enviarte mensajes por privado.")
        return

    # Obtener canal destino
    canal_destino = discord.utils.get(ctx.guild.text_channels, name="peticiones-de-usuarios")
    if not canal_destino:
        try:
            await ctx.author.send("❌ No se encontró el canal `#peticiones-de-usuarios`.")
        except discord.Forbidden:
            await ctx.send("❌ No se encontró el canal `#peticiones-de-usuarios` y no puedo contactarte por DM.")
        return

    # Generar código y crear embed
    codigo = generar_codigo_unico()
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(
        title="📬 Nueva petición recibida",
        description=descripcion,
        color=discord.Color.blue()
    )
    embed.add_field(name="👤 Usuario", value=ctx.author.mention, inline=True)
    embed.add_field(name="🆔 Código", value=f"`{codigo}`", inline=True)
    embed.add_field(name="📅 Fecha", value=fecha, inline=True)
    embed.add_field(name="📌 Estado", value="🟢 **Abierta**", inline=False)
    embed.set_footer(text=str(ctx.author.id))  # Aquí se guarda el ID

    # Enviar al canal público
    await canal_destino.send(embed=embed)

    # Confirmación por DM o fallback público
    try:
        await ctx.author.send(f"✅ Tu petición ha sido registrada con el código `{codigo}`.")
    except discord.Forbidden:
        await ctx.send(f"✅ Tu petición ha sido registrada con el código `{codigo}`, pero no pude enviarte mensaje privado.")