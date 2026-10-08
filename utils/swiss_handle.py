import logging
import discord
from typing import List, Optional, Tuple
import asyncio
import re
from datetime import datetime

from utils import dm
from utils import canales
from utils.torneos_estado import leer_clasificacion
from utils import decks
from utils import servicios
from utils.commons import (borrar_mensaje_seguro, buscar_usuario_en_servidor, validar_canal_correcto,
                           obtener_torneo_usuario, enviar_en_trozos, nombre_miembro,
                           codigo_etiquetado)
from utils.jugadores import submitted_deck_handle
from utils.validacion_web import EntradaInvalida, resultado as validar_resultado
from utils.swiss import engine, presentacion
from utils.swiss.service import (
    crear_torneo,
    eliminar_torneo_swiss,
    obtener_torneos_activos,
    obtener_torneo,
    obtener_rondas,
    iniciar_torneo,
    reiniciar_torneo,
    finalizar_torneo,
    generar_ronda,
    reportar_resultado,
    modificar_resultado,
    eliminar_ronda_swiss,
    publicar_clasificacion_swiss,
    publicar_emparejamientos
)

log = logging.getLogger(__name__)

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

        await ctx.author.send("1️⃣ ¿Nombre del torneo?")
        nombre_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=90)
        if nombre_msg.content.lower() == "cancelar": return
        nombre = nombre_msg.content.strip()

        await ctx.author.send("2️⃣ ¿Formato? (Premodern, Classic-Legacy, 7Pts, etc.)")
        formato_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=90)
        if formato_msg.content.lower() == "cancelar": return
        formato = formato_msg.content.strip()

        await ctx.author.send("3️⃣ ¿Número máximo de jugadores?")
        jugadores_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=90)
        if jugadores_msg.content.lower() == "cancelar": return
        try:
            max_jugadores = int(jugadores_msg.content.strip())
        except ValueError:
            await ctx.author.send("❌ Debe ser un número.")
            return

        await ctx.author.send("4️⃣ ¿Nivel? (`todos` o `socios`)")
        nivel_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=90)
        if nivel_msg.content.lower() == "cancelar": return
        nivel = nivel_msg.content.strip().lower()
        if nivel not in ["todos", "socios"]:
            await ctx.author.send("❌ Nivel no válido.")
            return

        await ctx.author.send("5️⃣ Fecha de inicio (DD/MM/YYYY)")
        fecha_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=90)
        if fecha_msg.content.lower() == "cancelar": return
        fecha_str = fecha_msg.content.strip()
        try:
            datetime.strptime(fecha_str, "%d/%m/%Y")
        except ValueError:
            await ctx.author.send("❌ Formato inválido. Usaré hoy.")
            fecha_str = datetime.now().strftime("%d/%m/%Y")

        codigo = await crear_torneo(ctx.bot, nombre, formato, max_jugadores, nivel, fecha_str)

        canal_activos = canales.get_canal(ctx.guild, canales.TORNEOS_ACTIVOS)
        if canal_activos:
            await canal_activos.send(
                f"🎮 **Torneo creado:** {nombre}\n"
                f"🏷️ **Código:** `{codigo}`\n"
                f"📋 **Formato:** {formato} (Swiss)\n"
                f"👥 **Jugadores:** {max_jugadores}\n"
                f"📅 **Inicio:** {fecha_str}\n"
                f"🎯 **Nivel:** {nivel}"
            )
        canal_cartelera = canales.get_canal(ctx.guild, canales.CARTELERA_TORNEOS)
        if canal_cartelera:
            await canal_cartelera.send(
                f"📢 **Nuevo torneo suizo creado!**\n"
                f"🏷️ **Nombre:** {nombre}\n"
                f"📋 **Formato:** {formato}\n"
                f"👥 **Máximo jugadores:** {max_jugadores}\n"
                f"🔒 **Nivel:** {nivel}\n"
                f"🏷️ **Código:** `{codigo}`\n"
                f"📅 **Inicio:** {fecha_str}\n"
                f"📌 Usa `!inscribir-swiss {codigo}` para apuntarte."
            )

        await ctx.author.send(f"✅ Torneo **{nombre}** ({formato}) creado con código `{codigo}`.")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: inscribir-swiss (asistente)
# ============================================================

def _es_admin(ctx) -> bool:
    """Dueño del servidor, rol 'admin' o permiso de administrador (mismo criterio que comando_roles_permitidos)."""
    autor = ctx.author
    if ctx.guild is None or not isinstance(autor, discord.Member):
        return False
    return (
        autor == ctx.guild.owner
        or autor.guild_permissions.administrator
        or any(r.name.lower() == canales.ROL_ADMIN for r in autor.roles)
    )


async def swiss_inscribir_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("🔍 **Inscribir en torneo suizo**\nEscribe `cancelar` para salir.")

        torneos = await obtener_torneos_activos(ctx.bot)
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

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(torneos_abiertos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = torneos_abiertos[idx]

        # Solo los admins pueden inscribir a otra persona; el resto se inscribe a sí mismo
        if _es_admin(ctx):
            await ctx.author.send("2️⃣ ¿A quién inscribes? (`yo` o nombre/mención)")
            usuario_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
            if usuario_msg.content.lower() == "cancelar":
                return
            if usuario_msg.content.lower() in ["yo", "mi", "me"]:
                usuario = ctx.author
            else:
                # Acepta nombre, ID o mención (<@id> / <@!id>)
                texto_usuario = re.sub(r"^<@!?(\d+)>$", r"\1", usuario_msg.content.strip())
                usuario = buscar_usuario_en_servidor(ctx.guild, texto_usuario)
                if not isinstance(usuario, discord.Member):
                    await ctx.author.send("❌ Usuario no encontrado en el servidor.")
                    return
        else:
            usuario = ctx.author

        # Un admin que inscribe a otra persona puede saltarse el nivel del torneo (excepción manual)
        res = await servicios.inscribir(ctx.bot, ctx.guild, usuario, torneo["codigo"],
                                        forzar=usuario.id != ctx.author.id)
        if not res.ok:
            await ctx.author.send(f"❌ {res.mensaje}")
            return
        await ctx.author.send(f"✅ {usuario.mention} inscrito en `{torneo['codigo']}`.")

        # Preguntar si quiere subir deck
        if usuario.id == ctx.author.id:
            try:
                await usuario.send(f"✅ Te has inscrito en el torneo `{torneo['codigo']}`.\n¿Quieres subir tu deck ahora? Responde `sí` o `no`.")
                respuesta = await dm.esperar_respuesta(ctx.bot, usuario, timeout=90.0)
                if dm.es_si(respuesta.content):
                    await submitted_deck_handle(ctx, torneo["codigo"])
                else:
                    await usuario.send("👌 Perfecto, podrás subir tu deck más tarde usando el comando correspondiente.")
            except asyncio.TimeoutError:
                await usuario.send("⏰ Tiempo agotado para subir deck. Puedes hacerlo más tarde con `!subir-deck`.")
            except discord.Forbidden:
                await ctx.author.send("⚠️ No pude enviarte el mensaje de confirmación. Revisa tus DMs.")
        else:
            # Inscrito por un admin: solo se le avisa, sin abrir el asistente de deck
            try:
                await usuario.send(f"🎮 Un admin te ha inscrito en el torneo `{torneo['codigo']}`.")
            except discord.Forbidden:
                await ctx.author.send(f"⚠️ No pude avisar a {usuario.display_name} por DM. Puede que tenga los DMs cerrados.")

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

        torneos = await obtener_torneos_activos(ctx.bot)
        mis_torneos = [
            t for t in torneos
            if str(ctx.author.id) in t.get("inscritos_ids", []) and t.get("estado", "abierto") == "abierto"
        ]
        if not mis_torneos:
            await ctx.author.send(
                "❌ No estás inscrito en ningún torneo suizo con inscripciones abiertas.\n"
                "Si el torneo ya ha empezado, habla con un admin."
            )
            return

        mensaje = "📋 **Tus torneos:**\n"
        for i, t in enumerate(mis_torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']}\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(mis_torneos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = mis_torneos[idx]

        await ctx.author.send(f"¿Seguro que quieres desinscribirte de `{torneo['codigo']}`? (sí/no)")
        confirm = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirm.content):
            await ctx.author.send("❌ Cancelado.")
            return

        res = await servicios.desinscribir(ctx.bot, ctx.guild, ctx.author, torneo["codigo"])
        await ctx.author.send(f"{'✅' if res.ok else '❌'} {res.mensaje}")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: iniciar-swiss (asistente) - solo admin
# ============================================================

async def _elegir_torneo_para_iniciar(ctx) -> Optional[dict]:
    torneos = await obtener_torneos_activos(ctx.bot)
    disponibles = [t for t in torneos if t.get("estado") == "abierto" and t.get("ronda_actual", 0) == 0]
    if not disponibles:
        await ctx.author.send("❌ No hay torneos listos para iniciar (deben estar en estado 'abierto' y sin rondas).")
        return None
    mensaje = "📋 **Torneos listos para iniciar:**\n"
    for i, t in enumerate(disponibles, 1):
        mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} ({len(t.get('inscritos_ids', []))} inscritos)\n"
    await ctx.author.send(mensaje + "\nEscribe el **número** del torneo:")

    seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
    if dm.es_cancelar(seleccion_msg.content):
        return None
    idx = dm.indice_elegido(seleccion_msg.content, len(disponibles))
    if idx is None:
        await ctx.author.send("❌ Número no válido.")
        return None
    return disponibles[idx]


async def _jugadores_sin_deck(ctx, torneo: dict) -> Tuple[List[str], List[dict]]:
    """(nombres con deck ✅, [{name, user_id}] sin deck) de los inscritos del torneo."""
    decks_subidos = await decks.codigos_subidos(ctx.guild)
    con_deck, sin_deck = [], []
    for uid in torneo.get("inscritos_ids", []):
        miembro = ctx.guild.get_member(int(uid))
        nombre = miembro.display_name if miembro else f"<@{uid}>"
        if f"{torneo['codigo']}_{uid}" in decks_subidos:
            con_deck.append(f"{nombre} ✅")
        else:
            sin_deck.append({"name": nombre, "user_id": uid})
    return con_deck, sin_deck


async def _decidir_sin_deck(ctx, inscritos_ids: list, con_deck: list, sin_deck: list) -> Optional[list]:
    """Pregunta qué hacer con quien no subió deck. Devuelve la lista a quitar ([] = continuar) o None si se cancela."""
    await ctx.author.send(
        "**Revisión de decks antes de iniciar el torneo:**\n\n"
        "Jugadores con deck subido:\n" + "\n".join(con_deck) + "\n\n"
        "Jugadores SIN deck subido:\n" + "\n".join(p["name"] + " ❌" for p in sin_deck) + "\n\n"
        "❓ ¿Qué deseas hacer con los jugadores que NO subieron deck?\n"
        "Responde con **'continuar'** para iniciar el torneo con todos los participantes, \n"
        "o **'eliminar'** para quitar a los que no subieron el deck. Tienes 90 segundos."
    )
    accion = (await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=90.0)).content.lower().strip()
    if accion == "eliminar":
        # se eliminarán AL CONFIRMAR: si luego se cancela, no se toca a nadie
        if len(inscritos_ids) - len(sin_deck) < 2:
            await ctx.author.send("❌ Si se eliminan, quedan menos de 2 jugadores. No se puede iniciar el torneo.")
            return None
        if sin_deck:
            await ctx.author.send("🗑️ Al iniciar se eliminarán: " + ", ".join(p["name"] for p in sin_deck))
        return list(sin_deck)
    if accion == "continuar":
        await ctx.author.send("✅ Se iniciará el torneo con todos los participantes, aunque algunos no hayan subido deck.")
        return []
    await ctx.author.send("❌ Opción no reconocida. Cancelo la operación.")
    return None


async def _iniciar_torneo(ctx, codigo: str, quitar: list) -> bool:
    """
    Cierra inscripciones y genera la ronda 1 con el lock del torneo y sobre los datos ACTUALES (durante las
    preguntas otro admin pudo iniciarlo o alguien inscribirse). Si falla, todo vuelve atrás.
    """
    ok, msg = await iniciar_torneo(ctx.bot, codigo, [p["user_id"] for p in quitar])
    if not ok:
        await ctx.author.send(f"❌ {msg}")
    return ok


async def _avisar_eliminados(ctx, codigo: str, quitar: list):
    for p in quitar:
        await ctx.author.send(f"✅ Eliminado del torneo: {p['name']}")
        miembro = ctx.guild.get_member(int(p["user_id"]))
        if miembro:
            try:
                await miembro.send(f"❌ Has quedado fuera del torneo `{codigo}` porque no subiste tu deck antes del inicio.")
            except discord.HTTPException:
                pass


async def swiss_iniciar_asistente_handle(ctx):
    """Inicia un torneo suizo después de verificar que los jugadores han subido deck."""
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("🚀 **Iniciar torneo suizo con verificación de decks**\nEscribe `cancelar` para salir.")
        torneo = await _elegir_torneo_para_iniciar(ctx)
        if not torneo:
            return
        codigo = torneo["codigo"]
        inscritos_ids = torneo.get("inscritos_ids", [])
        if len(inscritos_ids) < 2:
            await ctx.author.send("❌ Se necesitan al menos 2 jugadores para iniciar el torneo.")
            return

        con_deck, sin_deck = await _jugadores_sin_deck(ctx, torneo)
        quitar = await _decidir_sin_deck(ctx, inscritos_ids, con_deck, sin_deck)
        if quitar is None:
            return

        await ctx.author.send("¿Deseas iniciar el torneo ahora? Responde con **'sí'** para continuar o **'no'** para cancelar. Tienes 60 segundos.")
        if not dm.es_si((await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60.0)).content):
            await ctx.author.send("❌ Inicio de torneo cancelado.")
            return

        if not await _iniciar_torneo(ctx, codigo, quitar):
            return
        await _avisar_eliminados(ctx, codigo, quitar)
        await ctx.author.send(f"✅ Torneo `{codigo}` iniciado. Ronda 1 generada.")

        await publicar_emparejamientos(ctx.bot, ctx.guild, codigo)
        await publicar_clasificacion_swiss(ctx.bot, ctx.guild, codigo)
        canal_resultados = canales.get_canal(ctx.guild, canales.RESULTADOS)
        if canal_resultados:
            await canal_resultados.send(f"🏁 **Torneo `{codigo}` iniciado.** ¡Buena suerte a todos!")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
        log.exception(f"❌ Error en iniciar con verificación de decks: {e}")

# ============================================================
# COMANDO: reportar-swiss (asistente)
# ============================================================

async def swiss_reportar_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📊 **Reportar resultado**\nEscribe `cancelar` para salir.")

        torneos = await obtener_torneos_activos(ctx.bot)
        activos = [t for t in torneos if t.get("ronda_actual", 0) > 0 and t.get("estado") != "finalizado"]
        if not activos:
            await ctx.author.send("❌ No hay torneos activos con rondas.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(activos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {t.get('ronda_actual', 0)})\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(activos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = activos[idx]

        await ctx.author.send("2️⃣ ¿Jugador 1? (nombre, mención o **ID numérico**)")
        j1_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if j1_msg.content.lower() == "cancelar":
            return
        jugador1 = buscar_usuario_en_servidor(ctx.guild, j1_msg.content)
        if not jugador1:
            await ctx.author.send("❌ Usuario no encontrado. Prueba con el **ID numérico**.")
            return

        await ctx.author.send("3️⃣ ¿Resultado? (formato X-Y, ej: 2-1)")
        res_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if res_msg.content.lower() == "cancelar":
            return
        try:
            resultado = validar_resultado(res_msg.content)
        except EntradaInvalida as e:
            await ctx.author.send(f"❌ {e.mensaje}")
            return

        await ctx.author.send("4️⃣ ¿Jugador 2? (nombre, mención o **ID numérico**)")
        j2_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if j2_msg.content.lower() == "cancelar":
            return
        jugador2 = buscar_usuario_en_servidor(ctx.guild, j2_msg.content)
        if not jugador2:
            await ctx.author.send("❌ Usuario no encontrado. Prueba con el **ID numérico**.")
            return

        # Validaciones
        torneo_actual = await obtener_torneo(ctx.bot, torneo["codigo"])
        if not torneo_actual:
            await ctx.author.send("❌ No se pudo obtener el torneo.")
            return
        rondas = await obtener_rondas(ctx.bot, torneo["codigo"])
        if not rondas:
            await ctx.author.send("❌ El torneo no tiene rondas generadas.")
            return
        ronda_actual = rondas[-1]
        if ronda_actual.get("completa", False):
            await ctx.author.send("❌ La ronda actual ya está completa.")
            return

        _, emp_encontrado, _ = engine.buscar_partida(ronda_actual, jugador1.id, jugador2.id)
        if not emp_encontrado:
            await ctx.author.send("❌ Ese enfrentamiento no existe en la ronda actual.")
            return
        if emp_encontrado.get("resultado") is not None:
            await ctx.author.send("❌ Este partido ya tiene un resultado reportado.")
            return

        if not servicios.puede_reportar(ctx.author, jugador1.id, jugador2.id):
            await ctx.author.send("❌ Solo los jugadores o un administrador pueden reportar.")
            return

        await ctx.author.send(
            f"📋 Confirmar: {jugador1.display_name} {resultado} {jugador2.display_name} en `{torneo['codigo']}`. ¿Continuar? (sí/no)"
        )
        confirm = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirm.content):
            await ctx.author.send("❌ Cancelado.")
            return

        # Guarda, quita la partida de #citas, la anuncia en #resultados y publica la clasificación (igual que la web)
        res = await servicios.reportar(ctx.bot, ctx.guild, ctx.author, torneo["codigo"], jugador1.id, jugador2.id,
                                       resultado)
        await ctx.author.send(f"{'✅' if res.ok else '❌'} {res.mensaje}")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
        log.exception(f"❌ Error en reportar: {e}")
# ============================================================
# COMANDO: clasificacion-swiss (asistente)
# ============================================================

async def swiss_clasificacion_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    try:
        await ctx.author.send("📊 **Clasificación**\nEscribe el código del torneo o `cancelar`.")

        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']}\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(torneos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = torneos[idx]

        clasificacion_data = await leer_clasificacion(ctx.bot, torneo["codigo"])
        if not clasificacion_data:
            await ctx.author.send("❌ No se pudo obtener la clasificación.")
            return

        clasificacion = clasificacion_data.get("clasificacion", [])
        if not clasificacion:
            await ctx.author.send("❌ No hay clasificación disponible.")
            return

        await ctx.author.send(presentacion.texto_clasificacion_dm(ctx.guild, clasificacion))

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: siguiente-ronda-swiss (asistente) - solo admin
# ============================================================

async def _partidas_pendientes(ctx, codigo: str):
    """Partidas sin resultado de la última ronda: lista de (j1, j2, nombre1, nombre2)."""
    rondas = await obtener_rondas(ctx.bot, codigo)
    if not rondas:
        return []

    def nombre(uid):
        m = ctx.guild.get_member(int(uid)) if ctx.guild else None
        return m.display_name if m else f"Usuario {uid}"

    return [(e["j1"], e["j2"], nombre(e["j1"]), nombre(e["j2"]))
            for e in engine.partidas_pendientes(rondas[-1]) if e.get("j2") is not None]


async def swiss_partidos_pendientes_handle(ctx, codigo_torneo: str = None):
    """!partidos-pendientes: partidas sin resultado de la ronda actual de un torneo suizo (por DM)."""
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, canales.COMANDOS, "!partidos-pendientes"):
        return

    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx, mensaje_inicial="📋 ¿De qué torneo quieres ver las partidas pendientes?"
        )
        if not codigo_torneo:
            return

    torneo = await obtener_torneo(ctx.bot, codigo_torneo)
    if not torneo or torneo.get("tipo") != "swiss":
        await ctx.author.send(f"❌ El torneo `{codigo_torneo}` no existe.")
        return
    if torneo.get("estado") == "finalizado":
        await ctx.author.send(f"🏁 El torneo `{codigo_torneo}` ya ha finalizado.")
        return

    rondas = await obtener_rondas(ctx.bot, codigo_torneo)
    if not rondas:
        await ctx.author.send(f"⏳ El torneo `{codigo_torneo}` aún no ha empezado: no hay rondas.")
        return

    ronda_num = rondas[-1].get("numero")
    pendientes = await _partidas_pendientes(ctx, codigo_torneo)
    if not pendientes:
        texto = f"✅ Todas las partidas de la **ronda {ronda_num}** de `{codigo_torneo}` tienen resultado."
        if _es_admin(ctx):
            texto += "\nℹ️ Usa `!siguiente-ronda-swiss` para generar la siguiente ronda."
    else:
        yo = str(ctx.author.id)
        lineas = [f"{'👉' if yo in (j1, j2) else '•'} {n1} vs {n2}" for j1, j2, n1, n2 in pendientes]
        texto = (f"📋 **Partidas pendientes · ronda {ronda_num} · `{codigo_torneo}`** ({len(pendientes)}):\n"
                 + "\n".join(lineas))
    await enviar_en_trozos(ctx.author, texto)


async def swiss_siguiente_ronda_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)
    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("⏩ **Siguiente ronda**\nEscribe `cancelar` para salir.")

        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {t.get('ronda_actual', 0)})\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(torneos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = torneos[idx]

        # Verificar que el torneo no esté ya finalizado
        if torneo.get("estado") == "finalizado":
            await ctx.author.send("❌ El torneo ya está finalizado.")
            return

        # Confirmar
        await ctx.author.send(f"⚠️ ¿Generar siguiente ronda para `{torneo['codigo']}`? (sí/no)")
        confirm = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirm.content):
            await ctx.author.send("❌ Cancelado.")
            return

        # Generar la siguiente ronda
        ok, msg = await generar_ronda(ctx.bot, torneo["codigo"])
        if not ok:
            pendientes = await _partidas_pendientes(ctx, torneo["codigo"])
            if not pendientes:
                await ctx.author.send(f"❌ {msg}")
                return
            # Ofrecer cerrar las pendientes como empate 0-0 (regla avisada a los jugadores)
            lista = "\n".join(f"• {n1} vs {n2}" for _, _, n1, n2 in pendientes)
            await ctx.author.send(
                f"⚠️ {msg}\n{lista}\n\n"
                f"¿Cerrarlas como **empate 0-0** y pasar a la siguiente ronda? (sí/no)"
            )
            forzar = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
            if not dm.es_si(forzar.content):
                await ctx.author.send("❌ Cancelado. La ronda sigue abierta.")
                return
            for j1, j2, _, _ in pendientes:
                # Al cerrar la última, reportar_resultado genera y publica la siguiente ronda (o finaliza)
                await reportar_resultado(ctx.bot, torneo["codigo"], j1, "0-0", j2, ctx.guild, publicar=False)
            await ctx.author.send(
                f"✅ {len(pendientes)} partida(s) cerradas como empate. "
                f"La siguiente ronda se ha generado y publicado (o el torneo ha finalizado si era la última)."
            )
            return

        await ctx.author.send(f"✅ {msg}")
        torneo_actualizado = await obtener_torneo(ctx.bot, torneo["codigo"]) or {}
        ronda_actual = torneo_actualizado.get("ronda_actual", torneo.get("ronda_actual", 0) + 1)

        # ============================================================
        # 1️⃣ PUBLICAR EMPAREJAMIENTOS EN 🍸-citas‐a‐ciegas
        # ============================================================
        await publicar_emparejamientos(ctx.bot, ctx.guild, torneo["codigo"])

        # ============================================================
        # 2️⃣ ACTUALIZAR CLASIFICACIÓN Y PUBLICAR EN 🍺-el‐ranking‐de‐la‐barra
        # ============================================================
        await publicar_clasificacion_swiss(ctx.bot, ctx.guild, torneo["codigo"])

        # ============================================================
        # 3️⃣ (OPCIONAL) ANUNCIAR EN CANAL DE RESULTADOS
        # ============================================================
        canal_resultados = canales.get_canal(ctx.guild, canales.RESULTADOS)
        if canal_resultados:
            await canal_resultados.send(f"🔄 **Se ha generado la Ronda {ronda_actual} del torneo `{torneo['codigo']}`.**")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
        log.exception(f"❌ Error en siguiente-ronda-swiss: {e}")

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

        torneos = await obtener_torneos_activos(ctx.bot)
        if not torneos:
            await ctx.author.send("❌ No hay torneos suizos activos.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(torneos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']}\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(torneos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = torneos[idx]

        await ctx.author.send(f"⚠️ ¿Eliminar permanentemente `{torneo['codigo']}`? (sí/no)")
        confirm = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirm.content):
            await ctx.author.send("❌ Cancelado.")
            return

        ok = await eliminar_torneo_swiss(ctx.bot, torneo["codigo"])
        if not ok:
            await ctx.author.send("❌ No se pudo eliminar el torneo.")
            return

        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` eliminado.")

        canal_activos = canales.get_canal(ctx.guild, canales.TORNEOS_ACTIVOS)
        if canal_activos:
            async for msg in canal_activos.history(limit=200):
                if msg.author == ctx.bot.user and codigo_etiquetado(msg.content) == torneo["codigo"]:   # código exacto
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

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(torneos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = torneos[idx]

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

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(torneos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = torneos[idx]

        await ctx.author.send(f"⚠️ ¿Reiniciar `{torneo['codigo']}`? Esto borrará todas las rondas y la clasificación, pero mantendrá los inscritos y lo dejará en estado 'abierto'. ¿Continuar? (sí/no)")
        confirm = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirm.content):
            await ctx.author.send("❌ Cancelado.")
            return

        await reiniciar_torneo(ctx.bot, torneo["codigo"], ctx.guild)

        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` reiniciado y en estado **abierto**. Puedes iniciarlo con `!iniciar-swiss`.")

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

        torneos = await obtener_torneos_activos(ctx.bot)
        rondas_por_torneo = {t["codigo"]: await obtener_rondas(ctx.bot, t["codigo"]) for t in torneos}
        con_rondas = [t for t in torneos if rondas_por_torneo[t["codigo"]]]

        if not con_rondas:
            await ctx.author.send("❌ No hay torneos suizos con rondas.")
            return

        mensaje = "📋 **Torneos con rondas:**\n"
        for i, t in enumerate(con_rondas, 1):
            rondas_count = len(rondas_por_torneo[t["codigo"]])
            ronda_actual = t.get("ronda_actual", 0)
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} ({rondas_count} rondas, última Ronda {ronda_actual})\n"
        if len(mensaje) > 1900:
            chunks = [mensaje[i:i+1900] for i in range(0, len(mensaje), 1900)]
            for chunk in chunks:
                await ctx.author.send(chunk)
        else:
            await ctx.author.send(mensaje)

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(con_rondas))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = con_rondas[idx]

        rondas = await obtener_rondas(ctx.bot, torneo["codigo"])

        mensaje_rondas = f"📋 **Rondas del torneo {torneo['codigo']}:**\n"
        for i, r in enumerate(rondas, 1):
            num = r.get("numero", 0)
            completa = "✅" if r.get("completa", False) else "⏳"
            mensaje_rondas += f"{i}. Ronda {num} {completa}\n"
        mensaje_rondas += "\nℹ️ Solo se puede eliminar la **última** ronda.\nEscribe el **número** de la ronda que quieres eliminar:"
        if len(mensaje_rondas) > 1900:
            chunks = [mensaje_rondas[i:i+1900] for i in range(0, len(mensaje_rondas), 1900)]
            for chunk in chunks:
                await ctx.author.send(chunk)
        else:
            await ctx.author.send(mensaje_rondas)

        ronda_seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(ronda_seleccion_msg.content):
            return
        idx_ronda = dm.indice_elegido(ronda_seleccion_msg.content, len(rondas))
        if idx_ronda is None:
            await ctx.author.send("❌ Número no válido.")
            return
        ronda = rondas[idx_ronda]
        ronda_num = ronda.get("numero")

        await ctx.author.send(f"⚠️ ¿Estás seguro de eliminar la Ronda {ronda_num} del torneo `{torneo['codigo']}`? (sí/no)")
        confirm = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirm.content):
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
                generar_resp = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
                if dm.es_si(generar_resp.content):
                    ok_gen, msg_gen = await generar_ronda(ctx.bot, torneo["codigo"])
                    if ok_gen:
                        await ctx.author.send(f"✅ {msg_gen}")
                        await publicar_emparejamientos(ctx.bot, ctx.guild, torneo["codigo"])
                        await publicar_clasificacion_swiss(ctx.bot, ctx.guild, torneo["codigo"])
                    else:
                        await ctx.author.send(f"❌ Error al generar la ronda: {msg_gen}")
            except asyncio.TimeoutError:
                await ctx.author.send("⏰ Tiempo agotado. No se generó nueva ronda.")

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

        seleccion_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(seleccion_msg.content):
            return
        idx = dm.indice_elegido(seleccion_msg.content, len(activos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = activos[idx]

        await ctx.author.send(f"⚠️ ¿Estás seguro de finalizar el torneo `{torneo['codigo']}`? (sí/no)")
        confirm = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(confirm.content):
            await ctx.author.send("❌ Cancelado.")
            return

        await finalizar_torneo(ctx.bot, torneo["codigo"], ctx.guild)
        await ctx.author.send(f"✅ Torneo `{torneo['codigo']}` marcado como finalizado.")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")

# ============================================================
# COMANDO: modificar-resultado-swiss (asistente)
# ============================================================

async def swiss_modificar_resultado_asistente_handle(ctx):
    await borrar_mensaje_seguro(ctx)

    if not ctx.author.guild_permissions.administrator:
        await ctx.author.send("❌ Necesitas ser administrador.")
        return

    try:
        await ctx.author.send("✏️ **Modificar resultado Swiss**\nEscribe `cancelar` para salir.")

        # 1️⃣ Elegir torneo (también los finalizados, para poder corregir errores de la última ronda)
        torneos = await obtener_torneos_activos(ctx.bot)
        activos = [t for t in torneos if t.get("ronda_actual", 0) > 0]
        if not activos:
            await ctx.author.send("❌ No hay torneos con rondas.")
            return

        mensaje = "📋 **Torneos activos:**\n"
        for i, t in enumerate(activos, 1):
            mensaje += f"{i}. `{t['codigo']}` → {t['nombre']} (Ronda {t.get('ronda_actual', 0)})\n"
        mensaje += "\nEscribe el **número** del torneo:"
        await ctx.author.send(mensaje)

        sel_torneo = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if dm.es_cancelar(sel_torneo.content):
            return
        idx = dm.indice_elegido(sel_torneo.content, len(activos))
        if idx is None:
            await ctx.author.send("❌ Número no válido.")
            return
        torneo = activos[idx]

        # 2️⃣ Mostrar todas las rondas y partidos ya reportados
        rondas = await obtener_rondas(ctx.bot, torneo["codigo"])
        if not rondas:
            await ctx.author.send("❌ El torneo no tiene rondas.")
            return

        # Construir lista de partidos con resultado reportado
        opciones = []
        texto = "📋 **Partidos con resultado reportado:**\n"
        contador = 1
        for ronda in rondas:
            ronda_num = ronda.get("numero", 0)
            for emp in ronda.get("emparejamientos", []):
                # Los BYE no se pueden modificar: no tienen rival y cambiarlos corrompe la clasificación
                if emp.get("resultado") is None or emp.get("resultado") == "BYE" or emp.get("j2") is None:
                    continue
                j1_id = emp.get("j1")
                j2_id = emp.get("j2")

                nombre1 = await nombre_miembro(ctx.guild, j1_id, f"Usuario {j1_id}")

                if j2_id is None:
                    nombre2 = "BYE"
                else:
                    nombre2 = await nombre_miembro(ctx.guild, j2_id, f"Usuario {j2_id}")

                texto += f"{contador}. Ronda {ronda_num}: {nombre1} vs {nombre2} → {emp.get('resultado')}\n"
                opciones.append({
                    "ronda": ronda_num,
                    "j1": j1_id,
                    "j2": j2_id,
                    "nombre1": nombre1,
                    "nombre2": nombre2,
                })
                contador += 1

        if not opciones:
            await ctx.author.send("❌ No hay resultados reportados en este torneo (los BYE no se pueden modificar).")
            return

        await ctx.author.send(texto)
        await ctx.author.send("\nEscribe el **número** del partido a modificar:")

        sel_partido = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if sel_partido.content.lower() == "cancelar":
            return
        try:
            idx_p = int(sel_partido.content.strip()) - 1
            if idx_p < 0 or idx_p >= len(opciones):
                await ctx.author.send("❌ Número fuera de rango.")
                return
            elegido = opciones[idx_p]
        except ValueError:
            await ctx.author.send("❌ Número no válido.")
            return

        j1_id = elegido["j1"]
        j2_id = elegido["j2"]
        nombre1 = elegido["nombre1"]
        nombre2 = elegido["nombre2"]

        # 3️⃣ Pedir nuevo resultado
        await ctx.author.send(
            f"📊 Nuevo resultado para el partido (formato `X-Y`, según orden **{nombre1} vs {nombre2}**):"
        )
        res_msg = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if res_msg.content.lower() == "cancelar":
            return
        try:
            nuevo_resultado = validar_resultado(res_msg.content)
        except EntradaInvalida as e:
            await ctx.author.send(f"❌ {e.mensaje}")
            return

        # 4️⃣ Confirmación (avisando de lo que no se recalcula)
        avisos = []
        ultima_ronda = rondas[-1].get("numero", 0)
        if elegido["ronda"] < ultima_ronda:
            avisos.append(
                f"⚠️ Ya se han emparejado rondas posteriores (hasta la {ultima_ronda}). "
                "Esos emparejamientos **no** se rehacen; solo se recalcula la clasificación."
            )
        if torneo.get("estado") == "finalizado":
            avisos.append("ℹ️ El torneo está finalizado: se recalculará y republicará la clasificación final.")
        aviso_txt = ("\n".join(avisos) + "\n") if avisos else ""
        await ctx.author.send(f"{aviso_txt}🔒 Confirmar cambio a **{nuevo_resultado}** (sí/no):")
        conf = await dm.esperar_respuesta(ctx.bot, ctx.author, timeout=60)
        if not dm.es_si(conf.content):
            await ctx.author.send("❌ Modificación cancelada.")
            return

        # 5️⃣ Aplicar el cambio (sobre las rondas actuales) y recalcular y republicar la clasificación
        ok, msg = await modificar_resultado(ctx.bot, torneo["codigo"], elegido["ronda"], j1_id, j2_id,
                                            nuevo_resultado, ctx.guild)
        if not ok:
            await ctx.author.send(f"❌ {msg}")
            return

        # 7️⃣ Anunciar en canal de resultados
        canal_resultados = canales.get_canal(ctx.guild, canales.RESULTADOS)
        if canal_resultados:
            nombre1 = await nombre_miembro(ctx.guild, j1_id, f"Usuario {j1_id}")
            nombre2 = await nombre_miembro(ctx.guild, j2_id, f"Usuario {j2_id}")

            await canal_resultados.send(
                f"🔄 Resultado **modificado** en `{torneo['codigo']}`:\n"
                f"**{nombre1}** {nuevo_resultado} **{nombre2}**"
            )

        await ctx.author.send(f"✅ {msg}")

    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tiempo agotado.")
    except Exception as e:
        await ctx.author.send(f"❌ Error: {e}")
        log.exception(f"❌ Error en modificar-resultado-swiss: {e}")
