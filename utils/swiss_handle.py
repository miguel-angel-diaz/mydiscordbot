# utils/swiss_handlers.py
import discord
import asyncio
from datetime import datetime

from utils.torneos_estado import (
    actualizar_torneo_estado,
    leer_rondas,
    leer_clasificacion,
    guardar_rondas,
    guardar_clasificacion,
    obtener_torneo_estado,
    eliminar_torneo_estado
)
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
        # 🔹 FILTRAR SOLO TORNEOS EN ESTADO "abierto"
        torneos_abiertos = [t for t in torneos if t.get("estado") == "abierto"]
        if not torneos_abiertos:
            await ctx.author.send("❌ No hay torneos suizos abiertos para inscripciones.")
            return

        mensaje = "📋 **Torneos disponibles (abiertos):**\n"
        for i, t in enumerate(torneos_abiertos, 1):
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
            torneo = torneos_abiertos[idx]
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

        # PREGUNTAR SI QUIERE SUBIR DECK (igual que antes, sin cambios)
        # ... (código existente para subir deck) ...

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
        # Solo torneos en estado "abierto" y sin rondas generadas (ronda_actual == 0)
        disponibles = [t for t in torneos if t.get("estado") == "abierto" and t.get("ronda_actual", 0) == 0]
        if not disponibles:
            await ctx.author.send("❌ No hay torneos listos para iniciar (deben estar en estado 'abierto' y sin rondas).")
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

        # Validar que haya al menos 2 jugadores
        if len(torneo.get("inscritos_ids", [])) < 2:
            await ctx.author.send("❌ Se necesitan al menos 2 jugadores para iniciar el torneo.")
            return

        # Verificar que no esté ya iniciado (por si acaso)
        if torneo.get("ronda_actual", 0) > 0:
            await ctx.author.send("⚠️ El torneo ya ha sido iniciado.")
            return

        ok, msg = await generar_ronda(ctx.bot, torneo["codigo"])
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        # Cambiar estado a "en desarrollo"
        await actualizar_torneo_estado(ctx.bot, torneo["codigo"], {"estado": "en desarrollo"})
        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` iniciado. Ronda 1 generada.")

        # Publicar clasificación y emparejamientos (código existente, sin cambios)
        # ...
        # (El resto del código de publicación se mantiene igual)

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
        print(f"❌ Error general: {e}")

# ============================================================
# COMANDO: reportar-swiss (asistente)
# ============================================================

async def swiss_reportar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📊 **Reportar resultado**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        # 1️⃣ Seleccionar torneo (listado simplificado)
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

        # 2️⃣ Pedir jugador 1
        await ctx.author.send("2️⃣ ¿Jugador 1? (nombre o mención)")
        j1_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if j1_msg.content.lower() == "cancelar":
            return
        jugador1 = buscar_usuario_en_servidor(ctx.guild, j1_msg.content)
        if not jugador1:
            await ctx.author.send("❌ Usuario no encontrado.")
            return

        # 3️⃣ Pedir resultado
        await ctx.author.send("3️⃣ ¿Resultado? (formato X-Y, ej: 2-1)")
        res_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if res_msg.content.lower() == "cancelar":
            return
        resultado = res_msg.content.strip()
        if "-" not in resultado:
            await ctx.author.send("❌ Formato inválido. Usa X-Y.")
            return

        # 4️⃣ Pedir jugador 2
        await ctx.author.send("4️⃣ ¿Jugador 2? (nombre o mención)")
        j2_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if j2_msg.content.lower() == "cancelar":
            return
        jugador2 = buscar_usuario_en_servidor(ctx.guild, j2_msg.content)
        if not jugador2:
            await ctx.author.send("❌ Usuario no encontrado.")
            return

        # --- Validaciones ---
        torneo_actual = await obtener_torneo(ctx.bot, torneo["codigo"])
        if not torneo_actual:
            await ctx.author.send("❌ No se pudo obtener el torneo.")
            return
        rondas_data = await leer_rondas(ctx.bot, torneo["codigo"])
        if not rondas_data:
            await ctx.author.send("❌ El torneo no tiene rondas generadas.")
            return
        rondas = rondas_data.get("rondas", [])
        if not rondas:
            await ctx.author.send("❌ El torneo no tiene rondas generadas.")
            return
        ronda_actual = rondas[-1]
        if ronda_actual.get("completa", False):
            await ctx.author.send("❌ La ronda actual ya está completa.")
            return

        emparejamientos = ronda_actual.get("emparejamientos", [])
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
            await ctx.author.send("❌ Solo los jugadores o un administrador pueden reportar.")
            return

        await ctx.author.send(f"📋 Confirmar: {jugador1.display_name} {resultado} {jugador2.display_name} en `{torneo['codigo']}`. ¿Continuar? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        # --- Reportar ---
        ok, msg, emp, emp_idx = await reportar_resultado(
            ctx.bot, torneo["codigo"], jugador1.id, resultado, jugador2.id, ctx.guild
        )
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        await ctx.author.send(f"✅ {msg}")

        # ============================================================
        # MEJORA: ELIMINAR LA LÍNEA DEL PARTIDO DEL MENSAJE DE CITAS
        # ============================================================
        canal_citas = discord.utils.get(ctx.guild.text_channels, name="🍸-citas‐a‐ciegas")
        if canal_citas and emp is not None:
            torneo_actual = await obtener_torneo(ctx.bot, torneo["codigo"])
            if torneo_actual:
                rondas_data = await leer_rondas(ctx.bot, torneo["codigo"])
                if rondas_data:
                    rondas = rondas_data.get("rondas", [])
                    if rondas:
                        ronda_actual_data = rondas[-1]
                        ronda_num = ronda_actual_data.get("numero", 0)
                        async for msg in canal_citas.history(limit=200):
                            if msg.author == ctx.bot.user and f"Emparejamientos Ronda {ronda_num} - Torneo {torneo['codigo']}" in msg.content:
                                lines = msg.content.splitlines()
                                nueva_lines = []
                                for line in lines:
                                    # Si la línea contiene ambos jugadores (menciones), la saltamos
                                    if (jugador1.mention in line and jugador2.mention in line) or \
                                       (jugador2.mention in line and jugador1.mention in line):
                                        continue
                                    nueva_lines.append(line)
                                # Si solo queda título, eliminamos el mensaje completo
                                if len(nueva_lines) <= 2:  # título y posible línea vacía
                                    await msg.delete()
                                else:
                                    await msg.edit(content="\n".join(nueva_lines))
                                break

        # ============================================================
        # ACTUALIZAR CLASIFICACIÓN Y PUBLICAR
        # ============================================================
        await calcular_clasificacion(ctx.bot, torneo["codigo"])
        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            await publicar_clasificacion_swiss(ctx, torneo_actualizado)

        # ============================================================
        # ANUNCIAR RESULTADO EN CANAL DE RESULTADOS
        # ============================================================
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
        print(f"❌ Error en reportar: {e}")
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
        con_rondas = []
        for t in torneos:
            rondas_data = await leer_rondas(ctx.bot, t["codigo"])
            if rondas_data and rondas_data.get("rondas"):
                con_rondas.append(t)

        if not con_rondas:
            await ctx.author.send("❌ No hay torneos suizos con rondas.")
            return

        mensaje = "📋 **Torneos con rondas:**\n"
        for i, t in enumerate(con_rondas, 1):
            rondas_data = await leer_rondas(ctx.bot, t["codigo"])
            rondas_count = len(rondas_data.get("rondas", [])) if rondas_data else 0
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

        rondas_data = await leer_rondas(ctx.bot, torneo["codigo"])
        rondas = rondas_data.get("rondas", []) if rondas_data else []

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
                                rondas_data = await leer_rondas(ctx.bot, torneo["codigo"])
                                if rondas_data:
                                    rondas_actual = rondas_data.get("rondas", [])
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

        clasificacion_data = await leer_clasificacion(ctx.bot, torneo["codigo"])
        if not clasificacion_data:
            await ctx.author.send("❌ No se pudo obtener la clasificación.")
            return

        clasificacion = clasificacion_data.get("clasificacion", [])
        if not clasificacion:
            await ctx.author.send("❌ No hay clasificación disponible.")
            return

        lines = ["📊 **Clasificación actual**", "Rk | Jugador | Pts | W-L-D | Dif"]
        for i, data in enumerate(clasificacion[:10], 1):
            member = ctx.guild.get_member(int(data["id"]))
            nombre = member.display_name if member else f"<@{data['id']}>"
            lines.append(f"{data['rk']:2} | {nombre:12} | {data['mp']:3.0f} | {data['w']}-{data['l']}-{data['dw']} | {data['dif']:+}")
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
                rondas_data = await leer_rondas(ctx.bot, torneo["codigo"])
                if rondas_data:
                    rondas = rondas_data.get("rondas", [])
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
    """Reinicia un torneo suizo (borra rondas y clasificación, mantiene inscritos y lo deja en estado 'abierto')."""
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
            estado = t.get("estado", "desconocido")
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {ronda}, {inscritos} inscritos, estado: {estado})\n"
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

        await ctx.author.send(f"⚠️ ¿Reiniciar `{torneo['codigo']}`? Esto borrará todas las rondas y la clasificación, pero mantendrá los inscritos y lo dejará en estado 'abierto'. ¿Continuar? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        # Resetear el torneo
        await actualizar_torneo_estado(ctx.bot, torneo["codigo"], {
            "ronda_actual": 0,
            "estado": "abierto"  # <--- NUEVO: lo deja listo para iniciar
        })
        await guardar_rondas(ctx.bot, torneo["codigo"], {"codigo": torneo["codigo"], "rondas": []})
        await guardar_clasificacion(ctx.bot, torneo["codigo"], {"codigo": torneo["codigo"], "clasificacion": []})

        # Eliminar mensajes de rondas y ranking anteriores
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

        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` reiniciado y en estado **abierto**. Puedes iniciarlo con `!iniciar-swiss`.")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: finalizar-swiss (asistente) - solo admin
# ============================================================

async def swiss_finalizar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🏁 **Finalizar torneo suizo**\nEscribe `cancelar` para salir.")
        def dm_check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        torneos = await obtener_torneos_activos(ctx.bot)
        activos = [t for t in torneos if t.get("estado") != "finalizado"]
        if not activos:
            await ctx.author.send("❌ No hay torneos suizos activos para finalizar.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(activos, 1):
            ronda = t.get("ronda_actual", 0)
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {ronda})\n"
        mensaje += "\nEscribe el **número** del torneo que quieres finalizar:"
        await ctx.author.send(mensaje)

        seleccion_msg = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if seleccion_msg.content.lower() == "cancelar": return
        try:
            idx = int(seleccion_msg.content.strip()) - 1
            torneo = activos[idx]
        except:
            await ctx.author.send("❌ Número no válido.")
            return

        await ctx.author.send(f"⚠️ ¿Estás seguro de finalizar el torneo `{torneo['codigo']}`? (sí/no)")
        confirm = await ctx.bot.wait_for("message", check=dm_check, timeout=60)
        if confirm.content.lower() not in ["sí", "si", "yes", "y"]:
            await ctx.author.send("❌ Cancelado.")
            return

        await actualizar_torneo_estado(ctx.bot, torneo["codigo"], {"estado": "finalizado"})

        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` marcado como finalizado.")

        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"])
        if torneo_actualizado:
            await publicar_clasificacion_swiss(ctx, torneo_actualizado)

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# PUBLICAR CLASIFICACIÓN (VERSIÓN FINAL)
# ============================================================
async def publicar_clasificacion_swiss(ctx, torneo: dict):
    canal_ranking = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return

    clasificacion_data = await leer_clasificacion(ctx.bot, torneo["codigo"])
    if not clasificacion_data:
        await calcular_clasificacion(ctx.bot, torneo["codigo"])
        clasificacion_data = await leer_clasificacion(ctx.bot, torneo["codigo"])

    clasificacion = clasificacion_data.get("clasificacion", []) if clasificacion_data else []

    if not clasificacion:
        inscritos = torneo.get("inscritos_ids", [])
        for uid in inscritos:
            try:
                member = await ctx.guild.fetch_member(int(uid))
                nombre = member.display_name
            except:
                nombre = f"<@{uid}>"
            clasificacion.append({
                "id": uid,
                "rk": len(clasificacion) + 1,
                "mp": 0,
                "w": 0,
                "l": 0,
                "dw": 0,
                "omw": 0.0,
                "bch": 0.0,
                "dif": 0
            })

    lines = [f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"]
    lines.append("```markdown")
    lines.append(f"{'Rk':<3} | {'Participante':<22} | {'G-P-E':<5} | {'Pts':<3} | {'OMW%':<5} | {'Bch':<6} | {'Dif':<3}")
    lines.append("-" * 72)

    for p in clasificacion:
        try:
            member = ctx.guild.get_member(int(p["id"]))
            nombre = member.display_name if member else f"<@{p['id']}>"
        except:
            nombre = f"<@{p['id']}>"
        nombre_truncado = nombre[:22] if len(nombre) > 22 else nombre

        gpe = f"{p.get('w', 0)}-{p.get('l', 0)}-{p.get('dw', 0)}"
        mp = p.get('mp', 0)
        omw = p.get('omw', 0.0)
        bch = p.get('bch', 0.0)
        dif = p.get('dif', 0)

        line = f"{p['rk']:<3} | {nombre_truncado:<22} | {gpe:<5} | {mp:<3} | {omw:.3f}  | {bch:.5f}  | {dif:+}"
        lines.append(line)

    lines.append("```")
    mensaje_completo = "\n".join(lines)

    async for msg in canal_ranking.history(limit=50):
        if msg.author == ctx.bot.user and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"):
                await msg.delete()
                break

    if len(mensaje_completo) <= 1900:
        await canal_ranking.send(mensaje_completo)
        return

    header_lines = lines[:3]
    player_lines = lines[3:-1]
    footer = "```"

    chunks = []
    for i in range(0, len(player_lines), 10):
        chunk_lines = header_lines + player_lines[i:i+10] + [footer]
        chunks.append("\n".join(chunk_lines))

    for chunk in chunks:
        await canal_ranking.send(chunk)
    canal_ranking = discord.utils.get(ctx.guild.text_channels, name="🍺-el‐ranking‐de‐la‐barra")
    if not canal_ranking:
        return

    clasificacion_data = await leer_clasificacion(ctx.bot, torneo["codigo"])
    if not clasificacion_data:
        await calcular_clasificacion(ctx.bot, torneo["codigo"])
        clasificacion_data = await leer_clasificacion(ctx.bot, torneo["codigo"])

    clasificacion = clasificacion_data.get("clasificacion", []) if clasificacion_data else []

    if not clasificacion:
        inscritos = torneo.get("inscritos_ids", [])
        for uid in inscritos:
            try:
                member = await ctx.guild.fetch_member(int(uid))
                nombre = member.display_name
            except:
                nombre = f"<@{uid}>"
            clasificacion.append({
                "id": uid,
                "rk": len(clasificacion) + 1,
                "mp": 0,
                "w": 0,
                "l": 0,
                "dw": 0,
                "omw": 0.0,
                "bch": 0.0,
                "dif": 0
            })

    lines = [f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"]
    lines.append("```markdown")
    lines.append(f"{'Rk':<3} | {'Participante':<22} | {'G-P-E':<5} | {'Pts':<3} | {'OMW%':<5} | {'Bch':<6} | {'Dif':<3}")
    lines.append("-" * 72)

    for p in clasificacion:
        try:
            member = ctx.guild.get_member(int(p["id"]))
            nombre = member.display_name if member else f"<@{p['id']}>"
        except:
            nombre = f"<@{p['id']}>"
        nombre_truncado = nombre[:22] if len(nombre) > 22 else nombre

        gpe = f"{p.get('w', 0)}-{p.get('l', 0)}-{p.get('dw', 0)}"
        mp = p.get('mp', 0)
        omw = p.get('omw', 0.0)
        bch = p.get('bch', 0.0)
        dif = p.get('dif', 0)

        line = f"{p['rk']:<3} | {nombre_truncado:<22} | {gpe:<5} | {mp:<3} | {omw:.3f}  | {bch:.5f}  | {dif:+}"
        lines.append(line)

    lines.append("```")
    mensaje_completo = "\n".join(lines)

    async for msg in canal_ranking.history(limit=50):
        if msg.author == ctx.bot.user and not msg.embeds:
            if msg.content.startswith(f"📊 **Clasificación del torneo `{torneo['codigo']}`:**"):
                await msg.delete()
                break

    if len(mensaje_completo) <= 1900:
        await canal_ranking.send(mensaje_completo)
        return

    header_lines = lines[:3]
    player_lines = lines[3:-1]
    footer = "```"

    chunks = []
    for i in range(0, len(player_lines), 10):
        chunk_lines = header_lines + player_lines[i:i+10] + [footer]
        chunks.append("\n".join(chunk_lines))

    for chunk in chunks:
        await canal_ranking.send(chunk)