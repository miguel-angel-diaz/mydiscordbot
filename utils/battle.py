######## battle.py #######
"""
Battle Royale con el sistema propio (sin Challonge).

A diferencia del suizo no hay rondas ni inscripción: un admin va apuntando enfrentamientos libres entre dos
miembros y, cuando se juegan, se reporta el resultado. Una misma pareja puede enfrentarse como máximo
MAX_POR_PAREJA veces en un battle.

Dónde se guarda (igual que el suizo, en mensajes del bot):
  - #torneos-estado: {"tipo": "battle", "nombre", "formato", "estado": "en desarrollo" | "finalizado", ...}
  - #rondas-torneo:  {"enfrentamientos": [{"id", "j1", "j2", "resultado", "anulado", ...}]}
La clasificación usa la MISMA calcular_estadisticas() del suizo (puntos, OMW%, diferencia, Buchholz).
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import discord

from utils import canales
from utils import dm
from utils.commons import borrar_mensaje_seguro, buscar_usuario_en_servidor, trocear_lista, validar_canal_correcto
from utils.swiss import engine
from utils.swiss_handle import _es_admin
from utils.torneos_estado import (
    actualizar_torneo_estado,
    generar_codigo_unico,
    guardar_rondas,
    leer_estado,
    leer_rondas,
    obtener_torneo_estado,
)
from utils.validacion_web import EntradaInvalida, resultado as validar_resultado

TIPO = "battle"
EN_CURSO = "en desarrollo"
FINALIZADO = "finalizado"
MAX_POR_PAREJA = 2
FORMATOS = ("Premodern", "Pauper")
TIMEOUT_DM = 90

CANAL_COMANDOS = canales.COMANDOS
CANAL_RANKING = canales.RANKING
CANAL_CARTELERA = canales.CARTELERA_TORNEOS

SOLO_USUARIOS = discord.AllowedMentions(everyone=False, roles=False, users=True)
TZ = ZoneInfo("Europe/Madrid")

_locks: Dict[str, asyncio.Lock] = {}


def _lock(codigo: str) -> asyncio.Lock:
    """Un lock por battle: dos admins a la vez no pueden pasarse del límite ni reportar dos veces lo mismo."""
    return _locks.setdefault(codigo, asyncio.Lock())


def _ahora() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


# ============================================================
# DATOS
# ============================================================

async def obtener_battle(bot, codigo: str) -> Optional[dict]:
    """El battle con ese código, o None si no existe o es un torneo de otro tipo."""
    if not codigo:
        return None
    torneo = await obtener_torneo_estado(bot, codigo)
    return torneo if torneo and torneo.get("tipo") == TIPO else None


async def listar_battles(bot, solo_en_curso: bool = True) -> List[dict]:
    estado = await leer_estado(bot)
    return [t for t in estado.get("torneos", [])
            if t.get("tipo") == TIPO and (not solo_en_curso or t.get("estado") == EN_CURSO)]


async def leer_enfrentamientos(bot, codigo: str) -> List[dict]:
    datos = await leer_rondas(bot, codigo) or {}
    return datos.get("enfrentamientos", [])


async def _guardar_enfrentamientos(bot, codigo: str, enfrentamientos: List[dict]):
    await guardar_rondas(bot, codigo, {"codigo": codigo, "enfrentamientos": enfrentamientos})


def _activos(enfrentamientos: List[dict]) -> List[dict]:
    return [e for e in enfrentamientos if not e.get("anulado")]


async def participantes(bot, codigo: str) -> List[str]:
    """IDs de quienes tienen algún enfrentamiento no anulado (el battle no tiene inscripción), en orden de aparición."""
    ids = []
    for e in _activos(await leer_enfrentamientos(bot, codigo)):
        for pid in (e.get("j1"), e.get("j2")):
            if pid and str(pid) not in ids:
                ids.append(str(pid))
    return ids


def _es_pareja(e: dict, a: str, b: str) -> bool:
    return {e.get("j1"), e.get("j2")} == {a, b}


def veces_enfrentados(enfrentamientos: List[dict], a, b) -> int:
    """Enfrentamientos de la pareja que cuentan para el límite (jugados o pendientes; los anulados no)."""
    a, b = str(a), str(b)
    return sum(1 for e in _activos(enfrentamientos) if _es_pareja(e, a, b))


def pendientes(enfrentamientos: List[dict], jugador=None) -> List[dict]:
    pend = [e for e in _activos(enfrentamientos) if e.get("resultado") is None]
    if jugador is not None:
        pend = [e for e in pend if str(jugador) in (e.get("j1"), e.get("j2"))]
    return pend


def _validar_resultado_battle(resultado: str) -> str:
    resultado = validar_resultado(resultado)          # X-Y con 0-3 partidas; lanza EntradaInvalida
    if resultado == "0-0":
        raise EntradaInvalida("Un 0-0 no es un resultado: si no se jugó, no lo reportes")
    return resultado


# ============================================================
# OPERACIONES (sin Discord: devuelven (ok, mensaje, ...))
# ============================================================

async def crear_battle(bot, nombre: str, formato: str, creador_id) -> str:
    codigo = f"br{generar_codigo_unico(6).lower()}"
    while await obtener_torneo_estado(bot, codigo):
        codigo = f"br{generar_codigo_unico(6).lower()}"
    await actualizar_torneo_estado(bot, codigo, {
        "nombre": nombre,
        "formato": formato,
        "tipo": TIPO,
        "estado": EN_CURSO,
        "fecha_inicio": datetime.now(TZ).strftime("%d/%m/%Y"),
        "max_por_pareja": MAX_POR_PAREJA,
        "creado_por": str(creador_id),
    })
    await _guardar_enfrentamientos(bot, codigo, [])
    return codigo


async def registrar_enfrentamiento(bot, codigo: str, j1, j2) -> Tuple[bool, str, Optional[dict]]:
    j1, j2 = str(j1), str(j2)
    if j1 == j2:
        return False, "Un jugador no puede enfrentarse a sí mismo.", None
    async with _lock(codigo):
        battle = await obtener_battle(bot, codigo)
        if not battle:
            return False, f"El battle `{codigo}` no existe.", None
        if battle.get("estado") != EN_CURSO:
            return False, f"El battle `{codigo}` ya ha finalizado.", None
        enfs = await leer_enfrentamientos(bot, codigo)
        limite = int(battle.get("max_por_pareja", MAX_POR_PAREJA))
        veces = veces_enfrentados(enfs, j1, j2)
        if veces >= limite:
            return False, f"Esa pareja ya se ha enfrentado {veces} veces (máximo {limite}).", None
        enf = {"id": max((e.get("id", 0) for e in enfs), default=0) + 1, "j1": j1, "j2": j2,
               "resultado": None, "creado": _ahora()}
        enfs.append(enf)
        await _guardar_enfrentamientos(bot, codigo, enfs)
        return True, f"Enfrentamiento #{enf['id']} registrado ({veces + 1}/{limite} de la pareja).", enf


async def reportar_resultado_battle(bot, codigo: str, j1, j2, resultado: str, autor_id) -> Tuple[bool, str, Optional[dict]]:
    """
    Resultado del enfrentamiento PENDIENTE más antiguo de la pareja. `resultado` va en el orden j1-j2 recibido;
    si el enfrentamiento se guardó al revés, se da la vuelta.
    """
    try:
        resultado = _validar_resultado_battle(resultado)
    except EntradaInvalida as e:
        return False, e.mensaje, None
    j1, j2 = str(j1), str(j2)
    async with _lock(codigo):
        battle = await obtener_battle(bot, codigo)
        if not battle:
            return False, f"El battle `{codigo}` no existe.", None
        if battle.get("estado") != EN_CURSO:
            return False, f"El battle `{codigo}` ya ha finalizado: solo un admin puede corregir resultados.", None
        enfs = await leer_enfrentamientos(bot, codigo)
        enf = next((e for e in pendientes(enfs) if _es_pareja(e, j1, j2)), None)
        if not enf:
            return False, "Esa pareja no tiene ningún enfrentamiento pendiente en este battle.", None
        if enf["j1"] != j1:
            s1, s2 = resultado.split("-")
            resultado = f"{s2}-{s1}"
        enf.update({"resultado": resultado, "reportado_por": str(autor_id), "reportado": _ahora()})
        await _guardar_enfrentamientos(bot, codigo, enfs)
        return True, "Resultado registrado.", enf


async def modificar_resultado_battle(bot, codigo: str, enf_id: int, resultado: str, autor_id) -> Tuple[bool, str, Optional[dict]]:
    """Corrección de un admin: fija el resultado (en el orden j1-j2 guardado) de cualquier enfrentamiento no anulado."""
    try:
        resultado = _validar_resultado_battle(resultado)
    except EntradaInvalida as e:
        return False, e.mensaje, None
    async with _lock(codigo):
        if not await obtener_battle(bot, codigo):
            return False, f"El battle `{codigo}` no existe.", None
        enfs = await leer_enfrentamientos(bot, codigo)
        enf = next((e for e in _activos(enfs) if e.get("id") == enf_id), None)
        if not enf:
            return False, f"No existe el enfrentamiento #{enf_id}.", None
        enf.update({"resultado": resultado, "reportado_por": str(autor_id), "reportado": _ahora()})
        await _guardar_enfrentamientos(bot, codigo, enfs)
        return True, "Resultado modificado.", enf


async def anular_pendientes_jugador(bot, codigo: str, jugador) -> int:
    """Anula los enfrentamientos pendientes de un jugador (p. ej. si abandona el servidor). Los jugados se mantienen."""
    async with _lock(codigo):
        enfs = await leer_enfrentamientos(bot, codigo)
        afectados = pendientes(enfs, jugador)
        for e in afectados:
            e.update({"anulado": True, "anulado_en": _ahora()})
        if afectados:
            await _guardar_enfrentamientos(bot, codigo, enfs)
        return len(afectados)


async def finalizar_battle(bot, codigo: str) -> Tuple[bool, str, int]:
    """Cierra el battle; los enfrentamientos aún sin resultado se anulan (no puntúan)."""
    async with _lock(codigo):
        battle = await obtener_battle(bot, codigo)
        if not battle:
            return False, f"El battle `{codigo}` no existe.", 0
        if battle.get("estado") == FINALIZADO:
            return False, f"El battle `{codigo}` ya estaba finalizado.", 0
        enfs = await leer_enfrentamientos(bot, codigo)
        sin_jugar = pendientes(enfs)
        for e in sin_jugar:
            e.update({"anulado": True, "anulado_en": _ahora()})
        if sin_jugar:
            await _guardar_enfrentamientos(bot, codigo, enfs)
        await actualizar_torneo_estado(bot, codigo, {"estado": FINALIZADO, "fecha_fin": datetime.now(TZ).strftime("%d/%m/%Y")})
        return True, "Battle finalizado.", len(sin_jugar)


def calcular_clasificacion_battle(codigo: str, enfrentamientos: List[dict]) -> List[dict]:
    """Clasificación de los jugadores con algún resultado, con las reglas y el orden del suizo."""
    jugados = [e for e in _activos(enfrentamientos) if e.get("resultado")]
    jugadores = sorted({e["j1"] for e in jugados} | {e["j2"] for e in jugados})
    return engine.clasificacion(codigo, [{"emparejamientos": jugados}], jugadores)


# ============================================================
# PUBLICACIÓN
# ============================================================

def _nombre(guild, pid: str) -> str:
    miembro = guild.get_member(int(pid)) if str(pid).isdigit() else None
    return miembro.display_name if miembro else f"Usuario {str(pid)[-4:]}"


def _cabecera_clasificacion(codigo: str) -> str:
    return f"📊 **Clasificación del battle `{codigo}`:**"


def textos_clasificacion(guild, codigo: str, nombre_battle: str, clasificacion: List[dict], finalizado: bool) -> List[str]:
    """Mensajes (≤ 2000 caracteres) con la tabla; cada trozo es un bloque de código completo."""
    cabecera = _cabecera_clasificacion(codigo)
    titulo = f"{cabecera} {nombre_battle}" + (" — 🏁 FINAL" if finalizado else "")
    columnas = f"{'Rk':<3} | {'Participante':<22} | {'G-P-E':<5} | {'Pts':<3} | {'OMW%':<5} | {'Bch':<7} | Dif"
    filas = [f"{p['rk']:<3} | {_nombre(guild, p['id'])[:22]:<22} | {p['w']}-{p['l']}-{p['dw']:<1} | {int(p['mp']):<3} | "
             f"{p['omw']:.3f} | {p['bch']:.5f} | {p['dif']:+}" for p in clasificacion]
    if not filas:
        return [f"{titulo}\nTodavía no hay resultados."]
    trozos = trocear_lista("\n".join(filas), 1700)
    mensajes = []
    for i, trozo in enumerate(trozos, 1):
        encabezado = titulo if i == 1 else f"{cabecera} (continuación {i}/{len(trozos)})"
        mensajes.append(f"{encabezado}\n```markdown\n{columnas}\n{'-' * 72}\n{trozo}\n```")
    return mensajes


async def publicar_clasificacion_battle(bot, guild, codigo: str) -> bool:
    """Recalcula y publica la clasificación en el ranking, sustituyendo la anterior (todos sus trozos)."""
    canal = canales.get_canal(guild, CANAL_RANKING)
    battle = await obtener_battle(bot, codigo)
    if not canal or not battle:
        return False
    clasificacion = calcular_clasificacion_battle(codigo, await leer_enfrentamientos(bot, codigo))
    mensajes = textos_clasificacion(guild, codigo, battle.get("nombre", ""), clasificacion,
                                    battle.get("estado") == FINALIZADO)
    cabecera = _cabecera_clasificacion(codigo)
    async for msg in canal.history(limit=100):
        if msg.author == bot.user and not msg.embeds and msg.content.startswith(cabecera):
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
    for m in mensajes:
        await canal.send(m, allowed_mentions=discord.AllowedMentions.none())
    return True


# ============================================================
# HANDLERS DE COMANDOS (asistentes por DM)
# ============================================================

async def _dm(destinatario, texto: str) -> bool:
    try:
        await destinatario.send(texto, allowed_mentions=SOLO_USUARIOS)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def _preguntar(ctx, texto: str) -> Optional[str]:
    """Pregunta por DM (None si se agota el tiempo o escribe 'cancelar'): ver utils/dm.py."""
    return await dm.preguntar(ctx.bot, ctx.author, texto, TIMEOUT_DM)


async def _elegir_de_lista(ctx, titulo: str, opciones: List[str]) -> Optional[int]:
    return await dm.elegir_de_lista(ctx.bot, ctx.author, titulo, opciones, TIMEOUT_DM)


async def _elegir_battle(ctx, codigo: Optional[str], solo_en_curso: bool = True) -> Optional[dict]:
    if codigo:
        battle = await obtener_battle(ctx.bot, codigo.strip().lower())
        if not battle:
            await ctx.author.send(f"❌ No existe ningún battle con el código `{codigo}`.")
            return None
        if solo_en_curso and battle.get("estado") != EN_CURSO:
            await ctx.author.send(f"❌ El battle `{battle['codigo']}` ya ha finalizado.")
            return None
        return battle
    battles = await listar_battles(ctx.bot, solo_en_curso)
    if not battles:
        await ctx.author.send("❌ No hay ningún battle en curso." if solo_en_curso else "❌ No hay ningún battle.")
        return None
    if len(battles) == 1:
        return battles[0]
    i = await _elegir_de_lista(ctx, "**Battles:**", [
        f"`{b['codigo']}` — {b.get('nombre', '')}" + (" (finalizado)" if b.get("estado") == FINALIZADO else "")
        for b in battles])
    return battles[i] if i is not None else None


async def _miembro_valido(ctx, valor, etiqueta: str) -> Optional[discord.Member]:
    miembro = valor if isinstance(valor, discord.Member) else buscar_usuario_en_servidor(ctx.guild, valor or "")
    if not isinstance(miembro, discord.Member):
        await ctx.author.send(f"❌ No encontré a {etiqueta} en el servidor.")
        return None
    if miembro.bot:
        await ctx.author.send(f"❌ {miembro.display_name} es un bot.")
        return None
    return miembro


def _describir(guild, e: dict) -> str:
    estado = f"**{e['resultado']}**" if e.get("resultado") else "pendiente"
    return f"#{e['id']} {_nombre(guild, e['j1'])} vs {_nombre(guild, e['j2'])} — {estado}"


async def nuevo_battle_handle(ctx, nombre: str = None):
    await borrar_mensaje_seguro(ctx)
    if not nombre:
        nombre = await _preguntar(ctx, "⚔️ Nuevo Battle Royale.\n1️⃣ ¿Qué **nombre** tendrá?")
        if not nombre:
            return
    nombre = nombre.strip()[:80]
    resp = await _preguntar(ctx, f"2️⃣ ¿**Formato**? ({' / '.join(FORMATOS)})")
    if resp is None:
        return
    formato = next((f for f in FORMATOS if f.lower() == resp.lower()), None)
    if not formato:
        await ctx.author.send("❌ Formato no válido. Operación cancelada.")
        return

    codigo = await crear_battle(ctx.bot, nombre, formato, ctx.author.id)
    await ctx.author.send(
        f"✅ Battle **{nombre}** creado con código `{codigo}`.\n"
        f"Apunta enfrentamientos con `!iniciar-battle {codigo} @jugador1 @jugador2` "
        f"(máximo {MAX_POR_PAREJA} por pareja) y ciérralo con `!finalizar-battle {codigo}`.")
    cartelera = canales.get_canal(ctx.guild, CANAL_CARTELERA)
    if cartelera:
        await cartelera.send(f"⚔️ **Nuevo Battle Royale: {nombre}** ({formato})\n🏷️ Código: `{codigo}`",
                             allowed_mentions=discord.AllowedMentions.none())


async def iniciar_battle_handle(ctx, codigo_torneo: str = None, jugador1=None, jugador2=None):
    await borrar_mensaje_seguro(ctx)
    battle = await _elegir_battle(ctx, codigo_torneo)
    if not battle:
        return
    if jugador1 is None:
        jugador1 = await _preguntar(ctx, "1️⃣ Nombre o ID del **jugador 1**:")
        if jugador1 is None:
            return
    j1 = await _miembro_valido(ctx, jugador1, "el jugador 1")
    if not j1:
        return
    if jugador2 is None:
        jugador2 = await _preguntar(ctx, "2️⃣ Nombre o ID del **jugador 2**:")
        if jugador2 is None:
            return
    j2 = await _miembro_valido(ctx, jugador2, "el jugador 2")
    if not j2:
        return

    codigo = battle["codigo"]
    ok, msg, enf = await registrar_enfrentamiento(ctx.bot, codigo, j1.id, j2.id)
    if not ok:
        await ctx.author.send(f"❌ {msg}")
        return
    aviso = (f"🔥 **Battle `{codigo}`** — {battle.get('nombre', '')}\n{j1.mention} vs {j2.mention}\n"
             f"Cuando terminéis, reportad el resultado con `!reportar-resultado-battle` en `#{CANAL_COMANDOS}`.")
    sin_dm = [j.display_name for j in (j1, j2) if not await _dm(j, aviso)]
    await ctx.author.send(f"✅ {msg}\n**{j1.display_name}** vs **{j2.display_name}** en `{codigo}`."
                          + (f"\n⚠️ Sin DM a: {', '.join(sin_dm)}." if sin_dm else ""))


async def reportar_resultado_battle_handle(ctx, codigo_battle: str = None, jugador1=None, resultado: str = None, jugador2=None):
    await borrar_mensaje_seguro(ctx)
    if not await validar_canal_correcto(ctx, CANAL_COMANDOS, "!reportar-resultado-battle"):
        return
    battle = await _elegir_battle(ctx, codigo_battle)
    if not battle:
        return
    codigo = battle["codigo"]
    es_admin = _es_admin(ctx)

    if jugador1 is not None and jugador2 is not None:
        j1 = await _miembro_valido(ctx, jugador1, "el jugador 1")
        j2 = j1 and await _miembro_valido(ctx, jugador2, "el jugador 2")
        if not j1 or not j2:
            return
        id1, id2 = str(j1.id), str(j2.id)
    else:
        # Sin jugadores: se elige entre los enfrentamientos pendientes (los propios, o todos si es admin)
        enfs = await leer_enfrentamientos(ctx.bot, codigo)
        lista = pendientes(enfs) if es_admin else pendientes(enfs, ctx.author.id)
        if jugador1 is not None:
            # Solo se dio un jugador: sus enfrentamientos pendientes (antes se ignoraba y salía la lista entera)
            j1 = await _miembro_valido(ctx, jugador1, "el jugador")
            if not j1:
                return
            lista = [e for e in lista if str(j1.id) in (e["j1"], e["j2"])]
        if not lista:
            await ctx.author.send(f"📭 No tienes enfrentamientos pendientes en `{codigo}`." if not es_admin
                                  else f"📭 No hay enfrentamientos pendientes en `{codigo}`.")
            return
        if len(lista) == 1 and jugador1 is not None:
            i = 0                                          # un solo pendiente con ese jugador: no hace falta elegir
        else:
            i = await _elegir_de_lista(ctx, f"**Enfrentamientos pendientes de `{codigo}`:**",
                                       [_describir(ctx.guild, e) for e in lista])
        if i is None:
            return
        id1, id2 = lista[i]["j1"], lista[i]["j2"]
        resultado = None                                   # el orden lo marca el enfrentamiento elegido

    if str(ctx.author.id) not in (id1, id2) and not es_admin:
        await ctx.author.send("❌ Solo los jugadores del enfrentamiento o un admin pueden reportar el resultado.")
        return

    if not resultado:
        resultado = await _preguntar(ctx, f"Resultado de **{_nombre(ctx.guild, id1)}** vs **{_nombre(ctx.guild, id2)}** "
                                          f"(partidas ganadas de cada uno, p. ej. `2-1`):")
        if resultado is None:
            return

    ok, msg, enf = await reportar_resultado_battle(ctx.bot, codigo, id1, id2, resultado, ctx.author.id)
    if not ok:
        await ctx.author.send(f"❌ {msg}")
        return
    await _anunciar_resultado(ctx, battle, enf)
    await publicar_clasificacion_battle(ctx.bot, ctx.guild, codigo)


async def _anunciar_resultado(ctx, battle: dict, enf: dict):
    s1, s2 = (int(x) for x in enf["resultado"].split("-"))
    ganador = enf["j1"] if s1 > s2 else enf["j2"] if s2 > s1 else None
    texto = (f"📢 Resultado en el battle `{battle['codigo']}`:\n"
             f"🆚 <@{enf['j1']}> vs <@{enf['j2']}> → **{enf['resultado']}**\n"
             + (f"🏅 Gana <@{ganador}>" if ganador else "⚖️ Empate"))
    for pid in {enf["j1"], enf["j2"], str(ctx.author.id)}:
        miembro = ctx.guild.get_member(int(pid))
        if miembro:
            await _dm(miembro, texto)


async def modificar_resultado_battle_handle(ctx, codigo_battle: str = None):
    await borrar_mensaje_seguro(ctx)
    battle = await _elegir_battle(ctx, codigo_battle, solo_en_curso=False)
    if not battle:
        return
    codigo = battle["codigo"]
    lista = _activos(await leer_enfrentamientos(ctx.bot, codigo))
    if not lista:
        await ctx.author.send(f"📭 `{codigo}` no tiene enfrentamientos.")
        return
    i = await _elegir_de_lista(ctx, f"**Enfrentamientos de `{codigo}`:**", [_describir(ctx.guild, e) for e in lista])
    if i is None:
        return
    enf = lista[i]
    resultado = await _preguntar(ctx, f"Nuevo resultado de **{_nombre(ctx.guild, enf['j1'])}** vs "
                                      f"**{_nombre(ctx.guild, enf['j2'])}** (en ese orden, p. ej. `2-1`):")
    if resultado is None:
        return
    ok, msg, enf = await modificar_resultado_battle(ctx.bot, codigo, enf["id"], resultado, ctx.author.id)
    if not ok:
        await ctx.author.send(f"❌ {msg}")
        return
    await ctx.author.send(f"✅ {msg} {_describir(ctx.guild, enf)}")
    await publicar_clasificacion_battle(ctx.bot, ctx.guild, codigo)


async def actualizar_clasificacion_battle_handle(ctx, codigo_battle: str = None):
    await borrar_mensaje_seguro(ctx)
    battle = await _elegir_battle(ctx, codigo_battle, solo_en_curso=False)
    if not battle:
        return
    if await publicar_clasificacion_battle(ctx.bot, ctx.guild, battle["codigo"]):
        await ctx.author.send(f"✅ Clasificación de `{battle['codigo']}` publicada en `#{CANAL_RANKING}`.")
    else:
        await ctx.author.send(f"❌ No se encontró el canal `#{CANAL_RANKING}`.")


async def finalizar_battle_handle(ctx, codigo_battle: str = None):
    await borrar_mensaje_seguro(ctx)
    battle = await _elegir_battle(ctx, codigo_battle)
    if not battle:
        return
    codigo = battle["codigo"]
    sin_jugar = pendientes(await leer_enfrentamientos(ctx.bot, codigo))
    aviso = f"\n⚠️ Hay {len(sin_jugar)} enfrentamiento(s) sin resultado: se anularán y no puntuarán." if sin_jugar else ""
    resp = await _preguntar(ctx, f"¿Finalizar el battle `{codigo}` ({battle.get('nombre', '')})?{aviso}\n"
                                 f"Escribe `si` para confirmar.")
    if resp is None or resp.lower() not in ("si", "sí"):
        if resp is not None:
            await ctx.author.send("❌ Operación cancelada.")
        return
    ok, msg, anulados = await finalizar_battle(ctx.bot, codigo)
    if not ok:
        await ctx.author.send(f"❌ {msg}")
        return
    await publicar_clasificacion_battle(ctx.bot, ctx.guild, codigo)
    await ctx.author.send(f"🏁 {msg}" + (f" {anulados} enfrentamiento(s) anulado(s)." if anulados else ""))
