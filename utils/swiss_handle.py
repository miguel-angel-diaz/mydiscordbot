# utils/swiss_handlers.py
import discord
import asyncio
from datetime import datetime

from utils.commons import borrar_mensaje_seguro, buscar_usuario_en_servidor
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
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = torneos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        await ctx.author.send("2️⃣ ¿A quién inscribes? (`yo` o nombre/mención)")
        usuario_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if usuario_msg.content.lower() == "cancelar": return
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

        # Obtener torneo actualizado para el conteo correcto
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
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ {usuario.mention} inscrito en `{torneo['codigo']}`.")

        canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")
        if canal_anuncios:
            total = len(torneo["inscritos_ids"])
            maximo = torneo.get("total_maximo")
            plazas = maximo - total if maximo else "∞"
            await canal_anuncios.send(
                f"📥 {usuario.mention} se ha inscrito en `{torneo['codigo']}`.\n"
                f"👥 Inscritos: {total}/{maximo or '∞'} | 🪑 Plazas libres: {plazas}"
            )
            

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
        if seleccion_msg.content.lower() == "cancelar": return
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
        # Obtener torneo actualizado
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
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ Te has desinscrito de `{torneo['codigo']}`.")

        canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="📰-cartelera‐torneos")

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

        canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas:
            torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
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