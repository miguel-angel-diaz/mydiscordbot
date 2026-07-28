# utils/swiss_handlers.py
import discord
import asyncio
from datetime import datetime

from utils.commons import borrar_mensaje_seguro, buscar_usuario_en_servidor, obtener_deck_en_canal
from utils.jugadores import submitted_deck_handle
from utils.torneos_estado import actualizar_torneo_estado


from utils.swiss_core import (
    crear_torneo,
    eliminar_torneo_swiss,
    obtener_torneos_activos,
    obtener_torneo,
    inscribir_jugador,
    desinscribir_jugador,
    generar_ronda,
    reportar_resultado,
    calcular_clasificacion
)

# ============================================================
# COMANDO: nuevo-swiss (asistente)
# ============================================================

async def swiss_nuevo_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🎮 **Crear torneo suizo**\nResponde a las preguntas. Escribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        await ctx.author.send("1️⃣ ¿Nombre del torneo?")
        nombre_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
        if nombre_msg.content.lower() == "cancelar": return
        nombre = nombre_msg.content.strip()

        await ctx.author.send("2️⃣ ¿Número máximo de jugadores?")
        jugadores_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
        if jugadores_msg.content.lower() == "cancelar": return
        try:
            max_jugadores = int(jugadores_msg.content.strip())
        except ValueError:
            await ctx.author.send("❌ Debe ser un número.")
            return

        await ctx.author.send("3️⃣ ¿Nivel? (`todos` o `socios`)")
        nivel_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
        if nivel_msg.content.lower() == "cancelar": return
        nivel = nivel_msg.content.strip().lower()
        if nivel not in ["todos", "socios"]:
            await ctx.author.send("❌ Nivel no válido.")
            return

        await ctx.author.send("4️⃣ Fecha de inicio (DD/MM/YYYY)")
        fecha_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=90)
        if fecha_msg.content.lower() == "cancelar": return
        fecha_str = fecha_msg.content.strip()
        try:
            datetime.strptime(fecha_str, "%d/%m/%Y")
        except ValueError:
            await ctx.author.send("❌ Formato inválido. Usaré hoy.")
            fecha_str = datetime.now().strftime("%d/%m/%Y")

        codigo = await crear_torneo(ctx.bot, nombre, max_jugadores, nivel, fecha_str)

        canal_activos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
        if canal_activos:
            await canal_activos.send(
                f"🎮 **Torneo creado:** {nombre}\n"
                f"🏷️ **Código:** `{codigo}`\n"
                f"📋 **Formato:** Premodern (Swiss)\n"
                f"👥 **Jugadores:** {max_jugadores}\n"
                f"📅 **Inicio:** {fecha_str}\n"
                f"🎯 **Nivel:** {nivel}"
            )
        canal_cartelera = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
        if canal_cartelera:
            await canal_cartelera.send(
                f"📢 **Nuevo torneo suizo creado!**\n"
                f"🏷️ **Nombre:** {nombre}\n"
                f"👥 **Máximo jugadores:** {max_jugadores}\n"
                f"🔒 **Nivel:** {nivel}\n"
                f"🏷️ **Código:** `{codigo}`\n"
                f"📅 **Inicio:** {fecha_str}\n"
                f"📌 Usa `!inscribir-swiss {codigo}` para apuntarte."
            )

        await ctx.author.send(f"✅ Torneo **{nombre}** creado con código `{codigo}`.")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: inscribir-swiss (asistente)
# ============================================================

async def swiss_inscribir_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("🔍 **Inscribir en torneo suizo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos disponibles:**\n"
        for i, t in enumerate(torneos, 1):
            inscritos = len(t.get("inscritos_ids", []))
            maximo = t.get("total_maximo", "∞")
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} ({inscritos}/{maximo} inscritos)\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar":
            return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        await ctx.author.send("2️⃣ ¿A quién inscribes? (`yo` o nombre/mención)")
        usuario_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if usuario_msg.content.lower() == "cancelar":
            return
        if usuario_msg.content.lower() in ["yo", "mi", "me"]:
            usuario = ctx.author
        else:
            usuario = buscar_usuario_en_servidor(ctx.guild, usuario_msg.content)
            if not usuario:
                await ctx.author.send("❌ Usuario no encontrado.")
                return

        ok, msg = await inscribir_jugador(ctx.bot, torneo["codigo"], usuario.id)
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        # ✅ Inscripción exitosa → obtener torneo actualizado
        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            total = len(torneo_actualizado.get("inscritos_ids", []))
            maximo = torneo_actualizado.get("total_maximo")
            plazas = maximo - total if maximo else "∞"

            # Confirmación al usuario que ejecutó el comando
            await ctx.author.send(f"✅ {usuario.mention} inscrito en `{torneo['codigo']}`.")

            # Anuncio en la cartelera
            canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
            if canal_anuncios:
                await canal_anuncios.send(
                    f"📥 {usuario.mention} se ha inscrito en `{torneo['codigo']}`.\n"
                    f"👥 Inscritos: {total}/{maximo or '∞'} | 🪑 Plazas libres: {plazas}"
                )
        else:
            await ctx.author.send("⚠️ No se pudo obtener el estado actualizado del torneo.")
            return

        # ============================================================
        # 🆕 PREGUNTAR SI QUIERE SUBIR DECK
        # ============================================================
        if usuario.id == ctx.author.id:
            # El usuario es el autor, preguntar en el mismo DM
            try:
                await usuario.send(f"✅ Te has inscrito en el torneo `{torneo['codigo']}`.\n¿Quieres subir tu deck ahora? Responde `sí` o `no`.")
                def dm_autor(m):
                    return m.author == usuario and isinstance(m.channel, discord.DMChannel)
                respuesta = await ctx.bot.wait_for("message", check=dm_autor, timeout=90.0)
                if respuesta.content.lower() in ["sí", "si", "s", "yes", "y"]:
                    await submitted_deck_handle(ctx, torneo["codigo"])
                else:
                    await usuario.send("👌 Perfecto, podrás subir tu deck más tarde usando el comando correspondiente.")
            except asyncio.TimeoutError:
                await usuario.send("⏰ Tiempo agotado para subir deck. Puedes hacerlo más tarde con `!subir-deck`.")
            except discord.Forbidden:
                await ctx.author.send("⚠️ No pude enviarte el mensaje de confirmación. Revisa tus DMs.")
        else:
            # El usuario es otro, intentar enviarle DM
            try:
                await usuario.send(f"🎮 Te han inscrito en el torneo `{torneo['codigo']}`.\n¿Quieres subir tu deck ahora? Responde `sí` o `no`.")
                def dm_usuario(m):
                    return m.author == usuario and isinstance(m.channel, discord.DMChannel)
                respuesta = await ctx.bot.wait_for("message", check=dm_usuario, timeout=90.0)
                if respuesta.content.lower() in ["sí", "si", "s", "yes", "y"]:
                    await submitted_deck_handle(ctx, torneo["codigo"])
                else:
                    await usuario.send("👌 Perfecto, podrás subir tu deck más tarde usando el comando correspondiente.")
            except asyncio.TimeoutError:
                await usuario.send("⏰ Tiempo agotado para subir deck. Puedes hacerlo más tarde con `!subir-deck`.")
            except discord.Forbidden:
                # No se pudo enviar DM al usuario
                await ctx.author.send(f"⚠️ No pude enviar mensaje a {usuario.display_name} para preguntar por el deck. Puede que tenga DMs cerrados.")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
# ============================================================
# COMANDO: desinscribir-swiss (asistente)
# ============================================================

async def swiss_desinscribir_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("🔍 **Desinscribir de torneo suizo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        mis_torneos = [t for t in torneos if str(ctx.author.id) in t.get("inscritos_ids", [])]
        if not mis_torneos:
            await ctx.author.send("❌ No estás inscrito en ningún torneo suizo activo.")
            return

        mensaje = "📋 **Tus torneos:**\n"
        for i, t in enumerate(mis_torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']}\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar":
            return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = mis_torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        await ctx.author.send(f"¿Seguro que quieres desinscribirte de `{torneo['codigo']}`? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        ok, msg = await desinscribir_jugador(ctx.bot, torneo["codigo"], ctx.author.id)
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        # ✅ Desinscripción exitosa → obtener torneo actualizado y enviar mensajes
        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            total = len(torneo_actualizado.get("inscritos_ids", []))
            maximo = torneo_actualizado.get("total_maximo")
            plazas = maximo - total if maximo else "∞"
            await ctx.author.send(f"✅ Te has desinscrito de `{torneo['codigo']}`.")
            canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
            if canal_anuncios:
                await canal_anuncios.send(
                    f"📤 {ctx.author.mention} se ha desinscrito de `{torneo['codigo']}`.\n"
                    f"👥 Inscritos: {total}/{maximo or '∞'} | 🪑 Plazas libres: {plazas}"
                )
        else:
            await ctx.author.send("⚠️ No se pudo obtener el estado actualizado del torneo.")
            return

        # ============================================================
        # 🗑️ ELIMINAR DECK DEL USUARIO EN submitted-decks
        # ============================================================
        codigo_deck = f"{torneo['codigo']}_{ctx.author.id}"
        deck = await obtener_deck_en_canal(ctx.guild, codigo_deck)
        if deck and deck.get("mensaje"):
            try:
                await deck["mensaje"].delete()
                await ctx.author.send(f"✅ Se eliminó tu deck `{deck['nombre_deck']}` de submitted-decks.")
            except discord.Forbidden:
                await ctx.author.send(f"⚠️ No tengo permisos para eliminar el deck `{codigo_deck}`.")
            except discord.HTTPException as e:
                await ctx.author.send(f"⚠️ Error al eliminar el deck: {e}")
        else:
            # No hay deck subido, no hacemos nada
            pass

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: iniciar-swiss (asistente) - solo admin
# ============================================================

async def swiss_iniciar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🚀 **Iniciar torneo suizo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        disponibles = [t for t in torneos if t.get("ronda_actual", 0) == 0]
        if not disponibles:
            await ctx.author.send("❌ No hay torneos listos para iniciar.")
            return

        mensaje = "📋 **Torneos listos para iniciar:**\n"
        for i, t in enumerate(disponibles, 1):
            inscritos = len(t.get("inscritos_ids", []))
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} ({inscritos} inscritos)\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = disponibles[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        ok, msg = await generar_ronda(ctx.bot, torneo["codigo"])
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` iniciado. Ronda 1 generada.")

        # ============================================================
        # 🆕 PUBLICAR CLASIFICACIÓN INICIAL (todos a 0)
        # ============================================================
        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            await publicar_clasificacion_inicial(ctx, torneo_actualizado)

        # ============================================================
        # PUBLICAR EMPAREJAMIENTOS EN CANAL DE CITAS
        # ============================================================
        canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            if torneo_actualizado:
                rondas = torneo_actualizado.get("rondas", [])
                if rondas:
                    ronda1 = rondas[0]
                    mensaje_citas = f"📢 **Emparejamientos Ronda 1 - Torneo {torneo['codigo']}**\n"
                    for emp in ronda1.get("emparejamientos", []):
                        j1 = emp["j1"]
                        j2 = emp["j2"]
                        if j2 is None:
                            mensaje_citas += f"<@{j1}> → BYE\n"
                        else:
                            mensaje_citas += f"<@{j1}> vs <@{j2}>\n"
                    await canal_citas.send(mensaje_citas)

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
# ============================================================
# COMANDO: reportar-swiss (asistente)
# ============================================================

# utils/swiss_handlers.py

async def swiss_reportar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📊 **Reportar resultado**\nResponde a las preguntas. Escribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        activos = [t for t in torneos if t.get("ronda_actual", 0) > 0]
        if not activos:
            await ctx.author.send("❌ No hay torneos activos con rondas.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(activos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {t.get('ronda_actual', 0)})\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = activos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        # Obtener torneo actualizado
        torneo_actual = await obtener_torneo(ctx.bot, torneo["codigo"])
        if not torneo_actual:
            await ctx.author.send("❌ No se pudo obtener el torneo.")
            return

        # Obtener rondas y emparejamientos de la ronda actual
        rondas = torneo_actual.get("rondas", [])
        if not rondas:
            await ctx.author.send("❌ El torneo no tiene rondas generadas.")
            return
        ronda_actual = rondas[-1]
        emparejamientos = ronda_actual.get("emparejamientos", [])

        # Función para comprobar si un usuario está en un emparejamiento
        def esta_en_emparejamiento(user_id, emp):
            return emp.get("j1") == str(user_id) or emp.get("j2") == str(user_id)

        # Pedir jugador 1
        await ctx.author.send("2️⃣ ¿Jugador 1? (nombre o mención)")
        j1_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if j1_msg.content.lower() == "cancelar": return
        jugador1 = buscar_usuario_en_servidor(ctx.guild, j1_msg.content)
        if not jugador1:
            await ctx.author.send("❌ Usuario no encontrado.")
            return

        await ctx.author.send("3️⃣ ¿Resultado? (formato X-Y, ej: 2-1)")
        res_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if res_msg.content.lower() == "cancelar": return
        resultado = res_msg.content.strip()
        if "-" not in resultado:
            await ctx.author.send("❌ Formato inválido.")
            return

        await ctx.author.send("4️⃣ ¿Jugador 2? (nombre o mención)")
        j2_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if j2_msg.content.lower() == "cancelar": return
        jugador2 = buscar_usuario_en_servidor(ctx.guild, j2_msg.content)
        if not jugador2:
            await ctx.author.send("❌ Usuario no encontrado.")
            return

        # ============================================================
        # 🔐 VALIDACIONES DE PERMISOS Y EMPAREJAMIENTO
        # ============================================================

        # 1. Verificar que el enfrentamiento existe en la ronda actual
        emp_encontrado = None
        for emp in emparejamientos:
            if (emp.get("j1") == str(jugador1.id) and emp.get("j2") == str(jugador2.id)) or \
               (emp.get("j1") == str(jugador2.id) and emp.get("j2") == str(jugador1.id)):
                emp_encontrado = emp
                break

        if not emp_encontrado:
            await ctx.author.send("❌ Ese enfrentamiento no existe en la ronda actual.")
            return

        # 2. Verificar que el partido no esté ya reportado
        if emp_encontrado.get("resultado") is not None:
            await ctx.author.send("❌ Este partido ya tiene un resultado reportado.")
            return

        # 3. Verificar que el autor sea uno de los jugadores o administrador
        es_admin = ctx.author.guild_permissions.administrator
        es_jugador = ctx.author.id in (jugador1.id, jugador2.id)

        if not es_admin and not es_jugador:
            await ctx.author.send("❌ Solo los jugadores del enfrentamiento o un administrador pueden reportar este partido.")
            return

        # ============================================================
        # CONFIRMACIÓN Y REPORTE
        # ============================================================

        await ctx.author.send(f"📋 Confirmar: {jugador1.display_name} {resultado} {jugador2.display_name} en `{torneo['codigo']}`. ¿Continuar? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        ok, msg = await reportar_resultado(ctx.bot, torneo["codigo"], jugador1.id, resultado, jugador2.id)
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ Resultado reportado en `{torneo['codigo']}`.")

        # Actualizar clasificación
        await calcular_clasificacion(ctx.bot, torneo["codigo"])
        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            await publicar_clasificacion_swiss(ctx, torneo_actualizado)

        # Anuncio en canal de resultados
        canal_resultados = discord.utils.get(ctx.guild.text_channels, name="🍺-quién‐se‐lleva‐la‐ronda")
        if canal_resultados:
            await canal_resultados.send(
                f"🏆 Resultado en `{torneo['codigo']}`:\n"
                f"**{jugador1.display_name}** {resultado} **{jugador2.display_name}**"
            )

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
# ============================================================
# COMANDO: clasificacion-swiss (asistente)
# ============================================================

async def swiss_clasificacion_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📊 **Clasificación**\nEscribe el código del torneo o `cancelar`.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']}\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        clasificacion = await calcular_clasificacion(ctx.bot, torneo["codigo"])
        if not clasificacion:
            await ctx.author.send("❌ No se pudo calcular la clasificación.")
            return

        lines = ["📊 **Clasificación actual**", "Rk | Jugador | Pts | W-L-D | Dif"]
        for i, data in enumerate(clasificacion[:10], 1):
            member = ctx.guild.get_member(int(data["discord_id"]))
            nombre = member.display_name if member else f"<@{data['discord_id']}>"
            lines.append(f"{i:2} | {nombre:12} | {data['mp']:3.0f} | {data['wins']}-{data['losses']}-{data['draws']} | {data['diff']:+}")
        await ctx.author.send("\n".join(lines))

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: siguiente-ronda-swiss (asistente) - solo admin
# ============================================================

async def swiss_siguiente_ronda_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("⏩ **Siguiente ronda**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {t.get('ronda_actual', 0)})\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        await ctx.author.send(f"⚠️ ¿Generar siguiente ronda para `{torneo['codigo']}`? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        ok, msg = await generar_ronda(ctx.bot, torneo["codigo"])
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ Ronda {torneo.get('ronda_actual', 0)} generada para `{torneo['codigo']}`.")

        canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
            if torneo_actualizado:
                rondas = torneo_actualizado.get("rondas", [])
                if rondas:
                    ultima_ronda = rondas[-1]
                    mensaje_citas = f"📢 **Emparejamientos Ronda {ultima_ronda['numero']} - Torneo {torneo['codigo']}**\n"
                    for emp in ultima_ronda.get("emparejamientos", []):
                        j1 = emp["j1"]
                        j2 = emp["j2"]
                        if j2 is None:
                            mensaje_citas += f"<@{j1}> → BYE\n"
                        else:
                            mensaje_citas += f"<@{j1}> vs <@{j2}>\n"
                    await canal_citas.send(mensaje_citas)

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: eliminar-swiss (asistente) - solo admin
# ============================================================

async def swiss_eliminar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🗑️ **Eliminar torneo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']}\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        await ctx.author.send(f"⚠️ ¿Eliminar permanentemente `{torneo['codigo']}`? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        ok = await eliminar_torneo_swiss(ctx.bot, torneo["codigo"])
        if not ok:
            await ctx.author.send("❌ No se pudo eliminar el torneo.")
            return

        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` eliminado.")

        canal_activos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
        if canal_activos:
            async for msg in canal_activos.history(limit=200):
                if msg.author == ctx.bot.user and torneo["codigo"] in msg.content:
                    await msg.delete()
                    break

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

async def swiss_lista_inscritos_asistente_handle(ctx):
    """Muestra la lista de jugadores inscritos en un torneo suizo."""
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📋 **Lista de inscritos**\nEscribe el código del torneo o `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        # 1. Listar torneos activos para elegir
        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            inscritos = len(t.get("inscritos_ids", []))
            maximo = t.get("total_maximo", "∞")
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} ({inscritos}/{maximo} inscritos)\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar":
            return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        # 2. Obtener inscritos
        inscritos_ids = torneo.get("inscritos_ids", [])
        if not inscritos_ids:
            await ctx.author.send(f"📭 No hay jugadores inscritos en `{torneo['codigo']}`.")
            return

        # 3. Mostrar lista con menciones
        lines = [f"📋 **Inscritos en {torneo['nombre']} ({torneo['codigo']})**: {len(inscritos_ids)} jugadores"]
        for uid in inscritos_ids:
            member = ctx.guild.get_member(int(uid))
            nombre = member.display_name if member else f"Usuario {uid}"
            lines.append(f"• {nombre} (<@{uid}>)")

        # Enviar por partes si es muy largo
        for chunk in [lines[i:i+20] for i in range(0, len(lines), 20)]:
            await ctx.author.send("\n".join(chunk))

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# utils/swiss_handlers.py

async def publicar_clasificacion_inicial(ctx, torneo: dict):
    """Publica la clasificación inicial (todos a 0) en el canal de ranking."""
    canal_ranking = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return

    inscritos_ids = torneo.get("inscritos_ids", [])
    if not inscritos_ids:
        return

    # Construir tabla con todos los jugadores a 0
    lines = [f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"]
    lines.append("```markdown")
    lines.append("Rango | Participante           | G-P-E | Pts  | OMW%   | Buchholz | Dif")
    lines.append("------|------------------------|-------|------|--------|----------|-----")

    # Ordenar por nombre (o ID) para tener un orden consistente
    # Podríamos ordenar por nombre, pero usamos el orden de inscripción
    for i, uid in enumerate(inscritos_ids, 1):
        try:
            member = await ctx.guild.fetch_member(int(uid))
            nombre = member.display_name
        except:
            nombre = f"<@{uid}>"
        # Todos a 0
        line = f"{i:<5} | {nombre[:22]:<22} | 0-0-0 | 0    | 0.000  | 0.00000  | 0"
        lines.append(line)

    lines.append("```")
    mensaje = "\n".join(lines)

    # Buscar mensaje existente para editarlo (como en Challonge)
    mensaje_existente = None
    async for msg in canal_ranking.history(limit=50):
        if msg.author == ctx.bot.user and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"):
                mensaje_existente = msg
                break

    if mensaje_existente:
        await mensaje_existente.edit(content=mensaje)
    else:
        await canal_ranking.send(mensaje)

async def swiss_reiniciar_asistente_handle(ctx):
    """Reinicia un torneo suizo (borra rondas y clasificación, mantiene inscritos)."""
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🔄 **Reiniciar torneo suizo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        # Listar torneos activos (Swiss)
        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            inscritos = len(t.get("inscritos_ids", []))
            ronda = t.get("ronda_actual", 0)
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {ronda}, {inscritos} inscritos)\n"
        mensaje += "\nEscribe el **número** del torneo que quieres reiniciar:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        # Confirmación
        await ctx.author.send(f"⚠️ ¿Reiniciar `{torneo['codigo']}`? Esto borrará todas las rondas y la clasificación, pero mantendrá los inscritos. ¿Continuar? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        # Resetear el torneo
        torneo["ronda_actual"] = 0
        torneo["rondas"] = []
        torneo["clasificacion"] = []
        await actualizar_torneo_estado(ctx.bot, torneo["codigo"], torneo)

        # (Opcional) Eliminar mensajes de rondas y ranking anteriores
        canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            async for msg in canal_citas.history(limit=100):
                if f"Torneo {torneo['codigo']}" in msg.content and msg.author == ctx.bot.user:
                    await msg.delete()

        canal_ranking = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
        if canal_ranking:
            async for msg in canal_ranking.history(limit=100):
                if f"Clasificación del torneo `{torneo['codigo']}`" in msg.content and msg.author == ctx.bot.user:
                    await msg.delete()

        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` reiniciado. Puedes volver a iniciarlo con `!iniciar-swiss`.")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# utils/swiss_handlers.py

async def publicar_clasificacion_swiss(ctx, torneo: dict):
    """
    Publica o actualiza la clasificación de un torneo suizo en el canal de ranking.
    Si no hay clasificación calculada, la calcula.
    """
    canal_ranking = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return

    # Si no hay clasificación, calcularla
    if not torneo.get("clasificacion"):
        await calcular_clasificacion(ctx.bot, torneo["codigo"])
        torneo = await obtener_torneo(ctx.bot, torneo["codigo"])

    clasificacion = torneo.get("clasificacion", [])
    if not clasificacion:
        # Si aún no hay clasificación (sin rondas), mostrar todos a 0
        inscritos = torneo.get("inscritos_ids", [])
        clasificacion = []
        for uid in inscritos:
            try:
                member = await ctx.guild.fetch_member(int(uid))
                nombre = member.display_name
            except:
                nombre = f"<@{uid}>"
            clasificacion.append({
                "discord_id": uid,
                "nombre": nombre,
                "rank": len(clasificacion) + 1,
                "mp": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "omw": 0.0,
                "buchholz": 0.0,
                "diff": 0
            })

    # Construir tabla
    lines = [f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"]
    lines.append("```markdown")
    lines.append("Rango | Participante           | G-P-E | Pts  | OMW%   | Buchholz | Dif")
    lines.append("------|------------------------|-------|------|--------|----------|-----")
    for p in clasificacion:
        gpe = f"{p['wins']}-{p['losses']}-{p['draws']}"
        nombre = p.get('nombre', f"<@{p['discord_id']}>")
        line = f"{p['rank']:<5} | {nombre[:22]:<22} | {gpe:<5} | {p['mp']:<4} | {p['omw']:.3f}  | {p['buchholz']:.5f}  | {p['diff']:+}"
        lines.append(line)
    lines.append("```")
    mensaje = "\n".join(lines)

    # Buscar mensaje existente para editarlo
    mensaje_existente = None
    async for msg in canal_ranking.history(limit=50):
        if msg.author == ctx.bot.user and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"):
                mensaje_existente = msg
                break

    if mensaje_existente:
        await mensaje_existente.edit(content=mensaje)
    else:
        await canal_ranking.send(mensaje)