# utils/swiss_handlers.py
import discord
import asyncio
from datetime import datetime

from utils.torneos_estado import actualizar_torneo_estado
from utils.commons import borrar_mensaje_seguro, buscar_usuario_en_servidor, obtener_deck_en_canal
from utils.jugadores import submitted_deck_handle
from utils.swiss_core import (
    crear_torneo,
    eliminar_torneo_swiss,
    obtener_torneos_activos,
    obtener_torneo,
    inscribir_jugador,
    desinscribir_jugador,
    generar_ronda,
    reportar_resultado,
    calcular_clasificacion,
    eliminar_ronda_swiss,
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

        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            total = len(torneo_actualizado.get("inscritos_ids", []))
            maximo = torneo_actualizado.get("total_maximo")
            plazas = maximo - total if maximo else "∞"

            await ctx.author.send(f"✅ {usuario.mention} inscrito en `{torneo['codigo']}`.")

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
        # PREGUNTAR SI QUIERE SUBIR DECK
        # ============================================================
        if usuario.id == ctx.author.id:
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
        # ELIMINAR DECK DEL USUARIO
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

        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            await publicar_clasificacion_swiss(ctx, torneo_actualizado)

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

async def swiss_reportar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📊 **Reportar resultado**\nResponde a las preguntas. Escribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        # 1. Listar torneos activos con rondas
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
        if seleccion_msg.content.lower() == "cancelar":
            return
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

        rondas = torneo_actual.get("rondas", [])
        if not rondas:
            await ctx.author.send("❌ El torneo no tiene rondas generadas.")
            return
        ronda_actual = rondas[-1]
        emparejamientos = ronda_actual.get("emparejamientos", [])

        # 2. Pedir jugador 1
        await ctx.author.send("2️⃣ ¿Jugador 1? (nombre o mención)")
        j1_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if j1_msg.content.lower() == "cancelar":
            return
        jugador1 = buscar_usuario_en_servidor(ctx.guild, j1_msg.content)
        if not jugador1:
            await ctx.author.send("❌ Usuario no encontrado.")
            return

        # 3. Pedir resultado
        await ctx.author.send("3️⃣ ¿Resultado? (formato X-Y, ej: 2-1)")
        res_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if res_msg.content.lower() == "cancelar":
            return
        resultado = res_msg.content.strip()
        if "-" not in resultado:
            await ctx.author.send("❌ Formato inválido. Usa X-Y.")
            return

        # 4. Pedir jugador 2
        await ctx.author.send("4️⃣ ¿Jugador 2? (nombre o mención)")
        j2_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if j2_msg.content.lower() == "cancelar":
            return
        jugador2 = buscar_usuario_en_servidor(ctx.guild, j2_msg.content)
        if not jugador2:
            await ctx.author.send("❌ Usuario no encontrado.")
            return

        # ============================================================
        # VALIDACIONES
        # ============================================================

        emp_encontrado = None
        emp_idx = -1
        for i, emp in enumerate(emparejamientos):
            if (emp.get("j1") == str(jugador1.id) and emp.get("j2") == str(jugador2.id)) or \
               (emp.get("j1") == str(jugador2.id) and emp.get("j2") == str(jugador1.id)):
                emp_encontrado = emp
                emp_idx = i
                break

        if not emp_encontrado:
            await ctx.author.send("❌ Ese enfrentamiento no existe en la ronda actual.")
            return

        if emp_encontrado.get("resultado") is not None:
            await ctx.author.send("❌ Este partido ya tiene un resultado reportado.")
            return

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

        ok, msg, emp, emp_idx = await reportar_resultado(
            ctx.bot, torneo["codigo"], jugador1.id, resultado, jugador2.id, ctx.guild
        )
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ {msg}")

        # ============================================================
        # ELIMINAR EL ENFRENTAMIENTO DEL MENSAJE DE LA RONDA EN CITAS
        # ============================================================
        canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas and emp is not None and emp_idx >= 0:
            torneo_actual = await obtener_torneo(ctx.bot, torneo["codigo"])
            if torneo_actual:
                rondas = torneo_actual.get("rondas", [])
                if rondas:
                    ronda_actual_data = rondas[-1]
                    ronda_num = ronda_actual_data.get("numero", 0)
                    async for msg in canal_citas.history(limit=200):
                        if msg.author == ctx.bot.user and f"Emparejamientos Ronda {ronda_num} - Torneo {torneo['codigo']}" in msg.content:
                            lines = msg.content.splitlines()
                            nueva_lines = []
                            for line in lines:
                                if (jugador1.mention in line and jugador2.mention in line) or \
                                   (jugador2.mention in line and jugador1.mention in line):
                                    continue
                                nueva_lines.append(line)
                            if len(nueva_lines) < len(lines):
                                await msg.edit(content="\n".join(nueva_lines))
                            break

        # ============================================================
        # ACTUALIZAR CLASIFICACIÓN
        # ============================================================
        await calcular_clasificacion(ctx.bot, torneo["codigo"])
        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            await publicar_clasificacion_swiss(ctx, torneo_actualizado)

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
# COMANDO: eliminar-ronda-swiss (asistente) - solo admin
# ============================================================

async def swiss_eliminar_ronda_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🗑️ **Eliminar ronda de torneo suizo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        con_rondas = [t for t in torneos if t.get("rondas")]
        if not con_rondas:
            await ctx.author.send("❌ No hay torneos suizos con rondas.")
            return

        mensaje = "📋 **Torneos con rondas:**\n"
        for i, t in enumerate(con_rondas, 1):
            rondas_count = len(t.get("rondas", []))
            ronda_actual = t.get("ronda_actual", 0)
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} ({rondas_count} rondas, última Ronda {ronda_actual})\n"
        if len(mensaje) > 1900:
            chunks = [mensaje[i:i+1900] for i in range(0, len(mensaje), 1900)]
            for chunk in chunks:
                await ctx.author.send(chunk)
        else:
            await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar":
            return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = con_rondas[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        rondas = torneo.get("rondas", [])
        mensaje_rondas = f"📋 **Rondas del torneo {torneo['codigo']}:**\n"
        for i, r in enumerate(rondas, 1):
            num = r.get("numero", 0)
            completa = "✅" if r.get("completa", False) else "⏳"
            mensaje_rondas += f"{i}. Ronda {num} {completa}\n"
        mensaje_rondas += "\nEscribe el **número** de la ronda que quieres eliminar:"
        if len(mensaje_rondas) > 1900:
            chunks = [mensaje_rondas[i:i+1900] for i in range(0, len(mensaje_rondas), 1900)]
            for chunk in chunks:
                await ctx.author.send(chunk)
        else:
            await ctx.author.send(mensaje_rondas)

        ronda_seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if ronda_seleccion_msg.content.lower() == "cancelar":
            return
        try:
            idx_ronda = int(ronda_seleccion_msg.content.strip()) - 1
            ronda = rondas[idx_ronda]
            ronda_num = ronda.get("numero")
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        await ctx.author.send(f"⚠️ ¿Estás seguro de eliminar la Ronda {ronda_num} del torneo `{torneo['codigo']}`? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        ok, msg = await eliminar_ronda_swiss(ctx.bot, torneo["codigo"], ronda_num, ctx.guild)
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ {msg}")

        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado and torneo_actualizado.get("ronda_actual", 0) == 0:
            await ctx.author.send("ℹ️ El torneo se ha quedado sin rondas. ¿Quieres generar la Ronda 1 ahora? (sí/no)")
            try:
                generar_resp = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
                if generar_resp.content.lower() in ["sí", "si", "yes", "y"]:
                    ok_gen, msg_gen = await generar_ronda(ctx.bot, torneo["codigo"])
                    if ok_gen:
                        await ctx.author.send(f"✅ {msg_gen}")
                        canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
                        if canal_citas:
                            torneo_actual = await obtener_torneo(ctx.bot, torneo["codigo"])
                            if torneo_actual:
                                rondas_actual = torneo_actual.get("rondas", [])
                                if rondas_actual:
                                    ultima_ronda = rondas_actual[-1]
                                    mensaje_citas = f"📢 **Emparejamientos Ronda {ultima_ronda['numero']} - Torneo {torneo['codigo']}**\n"
                                    for emp in ultima_ronda.get("emparejamientos", []):
                                        j1 = emp["j1"]
                                        j2 = emp["j2"]
                                        if j2 is None:
                                            mensaje_citas += f"<@{j1}> → BYE\n"
                                        else:
                                            mensaje_citas += f"<@{j1}> vs <@{j2}>\n"
                                    await canal_citas.send(mensaje_citas)
                        await calcular_clasificacion(ctx.bot, torneo["codigo"])
                        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
                        if torneo_actualizado:
                            await publicar_clasificacion_swiss(ctx, torneo_actualizado)
                    else:
                        await ctx.author.send(f"❌ Error al generar la ronda: {msg_gen}")
            except asyncio.TimeoutError:
                await ctx.author.send("⏰ Tiempo agotado. No se generó nueva ronda.")
        else:
            if torneo_actualizado:
                await publicar_clasificacion_swiss(ctx, torneo_actualizado)

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

# ============================================================
# COMANDO: lista-inscritos-swiss (asistente)
# ============================================================

async def swiss_lista_inscritos_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📋 **Lista de inscritos**\nEscribe el código del torneo o `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

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

        inscritos_ids = torneo.get("inscritos_ids", [])
        if not inscritos_ids:
            await ctx.author.send(f"📭 No hay jugadores inscritos en `{torneo['codigo']}`.")
            return

        lines = [f"📋 **Inscritos en {torneo['nombre']} ({torneo['codigo']})**: {len(inscritos_ids)} jugadores"]
        for uid in inscritos_ids:
            member = ctx.guild.get_member(int(uid))
            nombre = member.display_name if member else f"Usuario {uid}"
            lines.append(f"• {nombre} (<@{uid}>)")

        for chunk in [lines[i:i+20] for i in range(0, len(lines), 20)]:
            await ctx.author.send("\n".join(chunk))

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: reiniciar-swiss (asistente) - solo admin
# ============================================================

async def swiss_reiniciar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🔄 **Reiniciar torneo suizo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

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

        await ctx.author.send(f"⚠️ ¿Reiniciar `{torneo['codigo']}`? Esto borrará todas las rondas y la clasificación, pero mantendrá los inscritos. ¿Continuar? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        torneo["ronda_actual"] = 0
        torneo["rondas"] = []
        torneo["clasificacion"] = []
        await actualizar_torneo_estado(ctx.bot, torneo["codigo"], torneo)

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

# ============================================================
# PUBLICAR CLASIFICACIÓN (CORREGIDA - ELIMINA Y ENVÍA NUEVO)
# ============================================================
async def publicar_clasificacion_swiss(ctx, torneo: dict):
    """
    Publica la clasificación de un torneo suizo en el canal de ranking,
    usando la misma lógica que el sistema Challonge (elimina mensaje antiguo y envía nuevos).
    """
    canal_ranking = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return

    # Calcular clasificación si no existe
    if not torneo.get("clasificacion"):
        await calcular_clasificacion(ctx.bot, torneo["codigo"])
        torneo = await obtener_torneo(ctx.bot, torneo["codigo"])

    clasificacion = torneo.get("clasificacion", [])
    
    # Si no hay clasificación, mostrar todos a 0
    if not clasificacion:
        inscritos = torneo.get("inscritos_ids", [])
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

    # ============================================================
    # CONSTRUIR MENSAJE CON NOMBRES REALES (como en Challonge)
    # ============================================================
    lines = [f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"]
    lines.append("```markdown")
    lines.append(f"{'Rango':<5} | {'Participante':<22} | {'G-P-E':<5} | {'Pts':<4} | {'OMW%':<6} | {'Buchholz':<8} | {'Dif':<4}")
    lines.append("-" * 72)

    for p in clasificacion:
        # Obtener nombre real del miembro (igual que en Challonge)
        try:
            # Intentar convertir a int para fetch_member
            member = await ctx.guild.fetch_member(int(p["discord_id"]))
            nombre_mostrado = f"{member.display_name} ({member.mention})"
        except (ValueError, discord.NotFound):
            # Si no es un ID válido o no está en el servidor
            nombre_mostrado = f"{p['discord_id']} (no en el servidor)"
        except Exception:
            nombre_mostrado = f"<@{p['discord_id']}>"

        # Truncar nombre a 22 caracteres para mantener formato
        nombre_truncado = nombre_mostrado[:22] if len(nombre_mostrado) > 22 else nombre_mostrado
        gpe = f"{p['wins']}-{p['losses']}-{p['draws']}"
        line = f"{p['rank']:<5} | {nombre_truncado:<22} | {gpe:<5} | {p['mp']:<4} | {p['omw']:.3f}  | {p['buchholz']:.5f}  | {p['diff']:+}"
        lines.append(line)

    lines.append("```")
    mensaje_completo = "\n".join(lines)

    # ============================================================
    # ELIMINAR MENSAJE ANTIGUO (si existe)
    # ============================================================
    mensaje_existente = None
    async for msg in canal_ranking.history(limit=50):
        if msg.author == ctx.bot.user and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"):
                mensaje_existente = msg
                break

    if mensaje_existente:
        try:
            await mensaje_existente.delete()
        except Exception as e:
            print(f"⚠️ No se pudo eliminar mensaje antiguo: {e}")

    # ============================================================
    # ENVIAR NUEVO MENSAJE (dividido si es necesario)
    # ============================================================
    # Si el mensaje es demasiado largo, dividirlo en partes de 10 jugadores
    if len(mensaje_completo) > 1900:
        # Separar cabecera y líneas de jugadores
        header_lines = lines[:3]  # Cabecera, encabezados y separador
        player_lines = lines[3:-1]  # Líneas de jugadores (sin el ``` final)
        footer = "```"

        # Dividir en chunks de 10 jugadores
        chunks = []
        for i in range(0, len(player_lines), 10):
            chunk_lines = header_lines + player_lines[i:i+10] + [footer]
            chunk = "\n".join(chunk_lines)
            chunks.append(chunk)

        # Enviar cada chunk
        for chunk in chunks:
            await canal_ranking.send(chunk)
    else:
        await canal_ranking.send(mensaje_completo)