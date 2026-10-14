######## encuestas.py #######
"""
Encuesta ANÓNIMA de fin de torneo (suizo o battle) por DM, para sacar datos con los que mejorar.

Flujo:
  1. Al finalizar el torneo se programa la encuesta para la mañana siguiente (HORA_ENVIO, hora de Madrid), para no
     coincidir con la clasificación ni con el aviso del sorteo.
  2. La revisión periódica la envía: un DM a cada participante con el botón "Responder encuesta" (persistente).
  3. El botón abre las preguntas de elegir (desplegables) y "Enviar" abre un formulario con las de texto libre.
  4. A los DIAS_RECORDATORIO días se recuerda UNA vez a quien no ha contestado; a los DIAS_ABIERTA se cierra y el
     dueño recibe el resumen con el CSV. !resultados-encuesta saca lo mismo cuando se quiera.

Anonimato: las respuestas se guardan sin ID de usuario. Para que nadie vote dos veces solo se guarda una huella
HMAC(usuario + torneo) con una clave derivada del token del bot: quien vea #encuestas no puede saber quién ha
votado (y menos qué). Las huellas van ordenadas y cada respuesta se inserta en una posición al azar, así que
tampoco se pueden emparejar por orden de llegada.

Las preguntas están en data/encuesta.json; cada encuesta guarda una copia de las suyas al programarse.

Dónde se guarda: #encuestas (privado), con el mismo formato que el estado de los torneos (torneos_estado.py):
    {"codigo", "nombre", "estado": "programada" | "abierta" | "cerrada", "enviar_desde", "cierra",
     "recordatorio", "recordatorio_enviado", "destinatarios": ["<id>"], "enviados", "sin_dm",
     "votaron": ["<hmac>"], "respuestas": [{"<id pregunta>": valor}], "elegir": [...], "textos": [...]}
"""
import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks

import config
from utils import canales
from utils.torneos_estado import guardar_encuesta, leer_encuesta, leer_encuestas, obtener_torneo_estado

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Madrid")
HORA_ENVIO = time(hour=10)
DIAS_RECORDATORIO = 3
DIAS_ABIERTA = 7
MAX_TEXTO = 500
PAUSA_DM = 1.0                    # segundos entre DMs para no chocar con los límites de Discord
INTERVALO_REVISION_MIN = 30
FICHERO_PREGUNTAS = os.path.join(config.DIR_DATOS, "encuesta.json")

PROGRAMADA, ABIERTA, CERRADA = "programada", "abierta", "cerrada"
SIN_MENCIONES = discord.AllowedMentions.none()
PATRON_CODIGO = r"[A-Za-z0-9_-]+"

_locks: Dict[str, asyncio.Lock] = {}


def _lock(codigo: str) -> asyncio.Lock:
    return _locks.setdefault(codigo, asyncio.Lock())


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# PREGUNTAS Y ANONIMATO
# ============================================================

def validar_preguntas(datos: dict) -> Tuple[List[dict], List[dict]]:
    """(elegir, textos) de data/encuesta.json, con las opciones de las de estrellas ya puestas. ValueError si no vale."""
    elegir, textos = datos.get("elegir", []), datos.get("textos", [])
    if not 1 <= len(elegir) <= 4:
        raise ValueError("La encuesta necesita entre 1 y 4 preguntas de elegir (caben 4 desplegables y el botón).")
    if len(textos) > 5:
        raise ValueError("Como mucho 5 preguntas de texto (límite de los formularios de Discord).")
    ids = [p.get("id") for p in elegir + textos]
    if not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("Cada pregunta necesita un 'id' distinto.")
    preparadas = []
    for p in elegir:
        opciones = [str(n) for n in range(1, 6)] if p.get("tipo") == "estrellas" else [str(o) for o in p.get("opciones", [])]
        if not 2 <= len(opciones) <= 25:
            raise ValueError(f"La pregunta '{p['id']}' necesita entre 2 y 25 opciones.")
        preparadas.append({"id": p["id"], "texto": str(p["texto"])[:100], "tipo": p.get("tipo", "opciones"),
                           "opciones": opciones})
    return preparadas, [{"id": t["id"], "texto": str(t["texto"])[:45]} for t in textos]


def cargar_preguntas() -> Tuple[List[dict], List[dict]]:
    with open(FICHERO_PREGUNTAS, encoding="utf-8") as f:
        return validar_preguntas(json.load(f))


def _clave_huella() -> bytes:
    base = os.environ.get("ENCUESTA_SECRET") or config.DISCORD_TOKEN
    if not base:
        log.warning("⚠️ Sin DISCORD_TOKEN ni ENCUESTA_SECRET: las huellas de la encuesta cambiarán al reiniciar")
        base = secrets.token_urlsafe(32)
    return hashlib.sha256(f"encuesta-anonima:{base}".encode()).digest()


_CLAVE = None


def huella(usuario_id, codigo: str) -> str:
    """Identifica que `usuario_id` ya votó en `codigo` sin poder sacar el ID de ella."""
    global _CLAVE
    if _CLAVE is None:
        _CLAVE = _clave_huella()
    return hmac.new(_CLAVE, f"{codigo}:{usuario_id}".encode(), hashlib.sha256).hexdigest()[:32]


def siguiente_envio(desde: datetime) -> datetime:
    """La HORA_ENVIO (Madrid) del día siguiente a `desde`, en UTC."""
    local = desde.astimezone(TZ)
    return datetime.combine(local.date() + timedelta(days=1), HORA_ENVIO, tzinfo=TZ).astimezone(timezone.utc)


def _vencido(iso: Optional[str], ahora: datetime) -> bool:
    try:
        return bool(iso) and datetime.fromisoformat(iso) <= ahora
    except ValueError:
        return False


# ============================================================
# RESUMEN Y CSV (lógica pura; probada en tests/test_encuestas.py)
# ============================================================

def _barra(n: int, total: int, ancho: int = 10) -> str:
    lleno = round(ancho * n / total) if total else 0
    return "█" * lleno + "░" * (ancho - lleno)


def resumen(encuesta: dict, max_comentarios: int = 15) -> str:
    respuestas = encuesta.get("respuestas", [])
    total = len(respuestas)
    enviados = encuesta.get("enviados", 0)
    estado = {PROGRAMADA: "programada", ABIERTA: "abierta", CERRADA: "cerrada"}.get(encuesta.get("estado"), "?")
    lineas = [f"📋 **Encuesta de {encuesta.get('nombre') or encuesta.get('codigo')}** (`{encuesta.get('codigo')}`, {estado})",
              f"👥 Han respondido **{total}** de {enviados}" + (f" ({round(100 * total / enviados)} %)" if enviados else "")]
    if not total:
        return "\n".join(lineas + ["Todavía no hay respuestas."])
    for p in encuesta.get("elegir", []):
        valores = [r.get(p["id"]) for r in respuestas if r.get(p["id"]) is not None]
        cuenta = Counter(map(str, valores))
        cabecera = f"\n**{p['texto']}**"
        if p.get("tipo") == "estrellas" and valores:
            cabecera += f" — media **{sum(int(v) for v in valores) / len(valores):.1f}** / 5"
        lineas.append(cabecera)
        for opcion in p["opciones"]:
            n = cuenta.get(opcion, 0)
            etiqueta = "⭐" * int(opcion) if p.get("tipo") == "estrellas" else opcion
            lineas.append(f"`{_barra(n, len(valores))}` {n:>2} · {etiqueta}")
    for t in encuesta.get("textos", []):
        textos = [r[t["id"]] for r in respuestas if r.get(t["id"])]
        lineas.append(f"\n**{t['texto']}** ({len(textos)})")
        for texto in textos[:max_comentarios]:
            lineas.append(f"> {discord.utils.escape_mentions(discord.utils.escape_markdown(texto))[:300]}")
        if len(textos) > max_comentarios:
            lineas.append(f"… y {len(textos) - max_comentarios} más en el CSV.")
    return "\n".join(lineas)


def _celda(valor) -> str:
    """Sin inyección de fórmulas al abrir el CSV en Excel (=, +, -, @ al principio se ejecutarían)."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def csv_respuestas(encuesta: dict) -> bytes:
    columnas = [p["id"] for p in encuesta.get("elegir", [])] + [t["id"] for t in encuesta.get("textos", [])]
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")        # ";" para que Excel en español lo abra en columnas
    escritor.writerow(["torneo"] + columnas)
    for r in encuesta.get("respuestas", []):
        escritor.writerow([_celda(encuesta.get("codigo"))] + [_celda(r.get(c)) for c in columnas])
    return salida.getvalue().encode("utf-8-sig")       # con BOM: Excel respeta las tildes


def fichero_csv(encuesta: dict) -> discord.File:
    return discord.File(io.BytesIO(csv_respuestas(encuesta)), filename=f"encuesta_{encuesta.get('codigo')}.csv")


# ============================================================
# ACCESO A DISCORD
# ============================================================

def _servidor(bot) -> Optional[discord.Guild]:
    return bot.get_guild(config.GUILD_ID_ADMISION) or (bot.guilds[0] if bot.guilds else None)


async def _dueno(guild: discord.Guild):
    if guild.owner:
        return guild.owner
    try:
        return await guild.fetch_member(guild.owner_id)
    except discord.HTTPException:
        return None


async def _crear_encuesta(bot, codigo: str, enviar_desde: datetime) -> Tuple[bool, str]:
    """Guarda la encuesta del torneo en estado "programada". No hace nada si ya tenía una."""
    from utils import sorteos    # mismos participantes que el sorteo (inscritos no retirados / jugadores del battle)
    if await leer_encuesta(bot, codigo):
        return False, f"El torneo `{codigo}` ya tiene encuesta."    # p. ej. se reabrió y se volvió a finalizar
    torneo = await obtener_torneo_estado(bot, codigo)
    if not torneo:
        return False, f"El torneo `{codigo}` no existe."
    guild = _servidor(bot)
    if guild is None or canales.get_canal(guild, canales.ENCUESTAS) is None:
        return False, f"No existe el canal #{canales.ENCUESTAS} (créalo privado)."
    elegir, textos = cargar_preguntas()
    participantes = await sorteos._participantes(bot, codigo, torneo)
    if not participantes:
        return False, f"El torneo `{codigo}` no tiene participantes."
    await guardar_encuesta(bot, codigo, {
        "nombre": torneo.get("nombre") or codigo, "estado": PROGRAMADA,
        "enviar_desde": enviar_desde.isoformat(), "destinatarios": participantes,
        "elegir": elegir, "textos": textos, "votaron": [], "respuestas": [],
    })
    return True, f"Encuesta de `{codigo}` programada para {len(participantes)} participantes."


async def programar_encuesta(bot, codigo: str):
    """Al finalizar un torneo: deja la encuesta lista para la mañana siguiente. Nunca rompe la finalización."""
    try:
        ok, msg = await _crear_encuesta(bot, codigo, siguiente_envio(_ahora()))
        (log.info if ok else log.warning)("📋 %s", msg)
    except Exception:
        log.exception("❌ No se pudo programar la encuesta de %s", codigo)


async def enviar_encuesta_ahora(bot, codigo: str) -> Tuple[bool, str]:
    """!enviar-encuesta: crea la encuesta (si hace falta) y la manda ya, sin esperar a la mañana siguiente."""
    async with _lock(codigo):
        encuesta = await leer_encuesta(bot, codigo)
        if encuesta and encuesta.get("estado") != PROGRAMADA:
            return False, f"La encuesta de `{codigo}` ya se envió."
        if not encuesta:
            ok, msg = await _crear_encuesta(bot, codigo, _ahora())
            if not ok:
                return False, msg
            encuesta = await leer_encuesta(bot, codigo)
        guild = _servidor(bot)
        await _enviar(bot, guild, encuesta)
        await guardar_encuesta(bot, codigo, encuesta)
    sin_dm = f" ({encuesta['sin_dm']} con los DMs cerrados)" if encuesta.get("sin_dm") else ""
    return True, (f"Encuesta de `{codigo}` enviada a {encuesta['enviados']} participantes{sin_dm}. Se cierra en "
                  f"{DIAS_ABIERTA} días; mientras, puedes verla con `!resultados-encuesta`.")


async def torneos_para_encuesta(bot) -> List[dict]:
    """Suizos y battles que aún no tienen encuesta enviada; primero los finalizados."""
    from utils.torneos_estado import leer_estado
    enviadas = {e.get("codigo") for e in await leer_encuestas(bot) if e.get("estado") != PROGRAMADA}
    torneos = [t for t in (await leer_estado(bot)).get("torneos", [])
               if t.get("codigo") and t["codigo"] not in enviadas and t.get("tipo", "swiss") in ("swiss", "battle")]
    return sorted(torneos, key=lambda t: t.get("estado") != "finalizado")


def _vista_responder(codigo: str) -> discord.ui.View:
    vista = discord.ui.View(timeout=None)
    vista.add_item(BotonResponderEncuesta(codigo))
    return vista


async def _enviar(bot, guild, encuesta: dict):
    """
    Manda el DM a cada participante que siga en el servidor. Modifica `encuesta` (la guarda también quien llama).
    Se marca abierta ANTES de repartir: quien pulse el botón mientras siguen saliendo DMs ya puede responder (su
    respuesta espera al lock, que tiene quien llama, y se guarda en cuanto acaba el reparto).
    """
    codigo, enviados, sin_dm = encuesta["codigo"], [], 0
    ahora = _ahora()
    encuesta.update({"estado": ABIERTA, "cierra": (ahora + timedelta(days=DIAS_ABIERTA)).isoformat(),
                     "recordatorio": (ahora + timedelta(days=DIAS_RECORDATORIO)).isoformat(),
                     "recordatorio_enviado": False, "enviados": 0, "sin_dm": 0})
    await guardar_encuesta(bot, codigo, encuesta)
    texto = (f"📋 **¿Qué te pareció {encuesta['nombre']}?**\n"
             "Queremos mejorar los torneos y tu opinión cuenta. Son 30 segundos.\n"
             f"🔒 Es **anónima**: nadie, ni los organizadores, puede ver qué ha respondido cada uno. "
             f"Puedes contestar hasta el {discord.utils.format_dt(ahora + timedelta(days=DIAS_ABIERTA), 'D')}.")
    for uid in encuesta.get("destinatarios", []):
        miembro = guild.get_member(int(uid))
        if miembro is None or miembro.bot:
            continue
        try:
            await miembro.send(texto, view=_vista_responder(codigo), allowed_mentions=SIN_MENCIONES)
            enviados.append(str(uid))
        except discord.HTTPException:
            sin_dm += 1
        await asyncio.sleep(PAUSA_DM)
    encuesta.update({"destinatarios": enviados, "enviados": len(enviados), "sin_dm": sin_dm})
    log.info("📋 Encuesta de %s enviada a %d participantes (%d con los DMs cerrados)", codigo, len(enviados), sin_dm)


async def _recordar(bot, guild, encuesta: dict):
    votaron = set(encuesta.get("votaron", []))
    codigo = encuesta["codigo"]
    for uid in encuesta.get("destinatarios", []):
        if huella(uid, codigo) in votaron:
            continue
        miembro = guild.get_member(int(uid))
        if miembro is None:
            continue
        try:
            await miembro.send(f"⏰ Aún estás a tiempo de responder la encuesta (anónima) de **{encuesta['nombre']}**. "
                               "Usa el botón del mensaje anterior. ¡Gracias!", allowed_mentions=SIN_MENCIONES)
        except discord.HTTPException:
            pass
        await asyncio.sleep(PAUSA_DM)
    encuesta["recordatorio_enviado"] = True


async def _cerrar(bot, guild, encuesta: dict):
    encuesta["estado"] = CERRADA
    encuesta.pop("destinatarios", None)       # ya no hace falta saber a quién se mandó
    dueno = await _dueno(guild)
    if dueno is None:
        return
    try:
        await mandar_resultados(dueno, encuesta, cabecera="🏁 Encuesta cerrada.\n")
    except discord.HTTPException:
        log.warning("No se pudo mandar el resumen de la encuesta de %s al dueño", encuesta["codigo"])


async def mandar_resultados(destino, encuesta: dict, cabecera: str = ""):
    from utils.commons import enviar_en_trozos   # import local: commons es grande
    await enviar_en_trozos(destino, cabecera + resumen(encuesta))
    if encuesta.get("respuestas"):
        await destino.send("📎 Todas las respuestas, para abrir en Excel:", file=fichero_csv(encuesta))


async def revisar_encuestas(bot):
    guild = _servidor(bot)
    if guild is None:
        return
    ahora = _ahora()
    for encuesta in await leer_encuestas(bot):
        estado, codigo = encuesta.get("estado"), encuesta.get("codigo")
        pendiente = ((estado == PROGRAMADA and _vencido(encuesta.get("enviar_desde"), ahora))
                     or (estado == ABIERTA and (_vencido(encuesta.get("cierra"), ahora)
                                                or (not encuesta.get("recordatorio_enviado")
                                                    and _vencido(encuesta.get("recordatorio"), ahora)))))
        if not pendiente:
            continue
        async with _lock(codigo):
            encuesta = await leer_encuesta(bot, codigo)          # releída dentro del lock
            if not encuesta:
                continue
            if encuesta["estado"] == PROGRAMADA:
                await _enviar(bot, guild, encuesta)
            elif encuesta["estado"] == ABIERTA and _vencido(encuesta.get("cierra"), ahora):
                await _cerrar(bot, guild, encuesta)
            elif encuesta["estado"] == ABIERTA and not encuesta.get("recordatorio_enviado"):
                await _recordar(bot, guild, encuesta)
            await guardar_encuesta(bot, codigo, encuesta)


# ============================================================
# RESPONDER
# ============================================================

class BotonResponderEncuesta(discord.ui.DynamicItem[discord.ui.Button],
                             template=rf"encuesta:abrir:(?P<codigo>{PATRON_CODIGO})"):
    def __init__(self, codigo: str):
        super().__init__(discord.ui.Button(label="Responder encuesta", emoji="📋", style=discord.ButtonStyle.primary,
                                           custom_id=f"encuesta:abrir:{codigo}"))
        self.codigo = codigo

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["codigo"])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        encuesta = await leer_encuesta(interaction.client, self.codigo)
        motivo = _no_puede_votar(encuesta, interaction.user.id, self.codigo)
        if motivo:
            await interaction.followup.send(motivo)
            return
        preguntas = "\n".join(f"**{i}.** {p['texto']}" for i, p in enumerate(encuesta["elegir"], 1))
        await interaction.followup.send(
            f"{preguntas}\n\nElige en cada desplegable y pulsa **Enviar**"
            + (" (después podrás dejar comentarios)." if encuesta.get("textos") else "."),
            view=PreguntasEncuesta(self.codigo, encuesta["elegir"], encuesta.get("textos", []), interaction.message))


def _no_puede_votar(encuesta: Optional[dict], usuario_id, codigo: str) -> Optional[str]:
    if not encuesta or encuesta.get("estado") != ABIERTA:
        return "ℹ️ Esta encuesta ya está cerrada. ¡Gracias de todos modos!"
    if str(usuario_id) not in encuesta.get("destinatarios", []):
        return "❌ Esta encuesta es solo para quienes jugaron el torneo."
    if huella(usuario_id, codigo) in encuesta.get("votaron", []):
        return "✅ Ya respondiste esta encuesta. ¡Gracias!"
    return None


class SelectorPregunta(discord.ui.Select):
    def __init__(self, num: int, pregunta: dict):
        opciones = [discord.SelectOption(label=("⭐" * int(o)) if pregunta["tipo"] == "estrellas" else o[:100],
                                         value=o) for o in pregunta["opciones"]]
        super().__init__(placeholder=f"{num}. {pregunta['texto']}"[:150], options=opciones, row=num - 1)
        self.pregunta = pregunta

    async def callback(self, interaction: discord.Interaction):
        self.view.elegidas[self.pregunta["id"]] = self.values[0]
        await interaction.response.defer()


class PreguntasEncuesta(discord.ui.View):
    """Desplegables en memoria (15 min): si el bot se reinicia, basta con volver a pulsar "Responder encuesta"."""

    def __init__(self, codigo: str, elegir: List[dict], textos: List[dict], mensaje_boton: Optional[discord.Message]):
        super().__init__(timeout=900)
        self.codigo, self.elegir, self.textos, self.mensaje_boton = codigo, elegir, textos, mensaje_boton
        self.elegidas: Dict[str, str] = {}
        for num, pregunta in enumerate(elegir, 1):
            self.add_item(SelectorPregunta(num, pregunta))

    @discord.ui.button(label="Enviar", style=discord.ButtonStyle.success, row=4)
    async def enviar(self, interaction: discord.Interaction, _boton):
        faltan = [str(i) for i, p in enumerate(self.elegir, 1) if p["id"] not in self.elegidas]
        if faltan:
            await interaction.response.send_message(f"❗ Te falta contestar: {', '.join(faltan)}.")
            return
        if self.textos:
            await interaction.response.send_modal(ComentariosEncuesta(self))
            return
        await interaction.response.defer()
        await self.guardar(interaction, {})

    async def guardar(self, interaction: discord.Interaction, comentarios: Dict[str, str]):
        respuesta = {p["id"]: (int(self.elegidas[p["id"]]) if p["tipo"] == "estrellas" else self.elegidas[p["id"]])
                     for p in self.elegir}
        respuesta.update({k: v for k, v in comentarios.items() if v})
        ok, msg = await guardar_respuesta(interaction.client, self.codigo, interaction.user.id, respuesta)
        await interaction.followup.send(msg)
        if ok:
            self.stop()
            for mensaje in (interaction.message, self.mensaje_boton):
                if mensaje is not None:
                    try:
                        await mensaje.edit(view=None)
                    except discord.HTTPException:
                        pass


class ComentariosEncuesta(discord.ui.Modal, title="Comentarios (opcional)"):
    def __init__(self, preguntas: PreguntasEncuesta):
        super().__init__()
        self.preguntas = preguntas
        self.campos = {}
        for t in preguntas.textos:
            campo = discord.ui.TextInput(label=t["texto"], style=discord.TextStyle.paragraph, required=False,
                                         max_length=MAX_TEXTO)
            self.campos[t["id"]] = campo
            self.add_item(campo)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.preguntas.guardar(interaction, {k: " ".join(c.value.split()) for k, c in self.campos.items()})

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("❌ Error guardando una respuesta de la encuesta %s: %s", self.preguntas.codigo, type(error).__name__)
        try:
            await interaction.followup.send("❌ Algo ha fallado. Vuelve a pulsar «Responder encuesta».")
        except discord.HTTPException:
            pass


async def guardar_respuesta(bot, codigo: str, usuario_id, respuesta: dict) -> Tuple[bool, str]:
    async with _lock(codigo):
        encuesta = await leer_encuesta(bot, codigo)
        motivo = _no_puede_votar(encuesta, usuario_id, codigo)
        if motivo:
            return False, motivo
        votaron = set(encuesta.get("votaron", [])) | {huella(usuario_id, codigo)}
        encuesta["votaron"] = sorted(votaron)                  # ordenadas: no delatan el orden de llegada
        respuestas = encuesta.setdefault("respuestas", [])
        respuestas.insert(secrets.randbelow(len(respuestas) + 1), respuesta)
        await guardar_encuesta(bot, codigo, encuesta)
    return True, "✅ ¡Gracias! Tu respuesta se ha guardado de forma anónima."


# ============================================================
# CONSULTA (!resultados-encuesta)
# ============================================================

async def encuestas_consultables(bot) -> List[dict]:
    """Las abiertas y cerradas, las más recientes primero (las programadas aún no tienen respuestas)."""
    encuestas = [e for e in await leer_encuestas(bot) if e.get("estado") in (ABIERTA, CERRADA)]
    return sorted(encuestas, key=lambda e: e.get("cierra") or "", reverse=True)


def etiqueta_encuesta(encuesta: dict) -> str:
    estado = "abierta" if encuesta.get("estado") == ABIERTA else "cerrada"
    return (f"`{encuesta['codigo']}` → {encuesta.get('nombre')} ({estado}, "
            f"{len(encuesta.get('respuestas', []))}/{encuesta.get('enviados', 0)} respuestas)")


# ============================================================
# ARRANQUE
# ============================================================

@tasks.loop(minutes=INTERVALO_REVISION_MIN)
async def _revision_periodica():
    try:
        await revisar_encuestas(_bot)
    except Exception:
        log.exception("❌ revisar_encuestas falló")


@_revision_periodica.before_loop
async def _antes_de_revision():
    await _bot.wait_until_ready()


_bot = None


def registrar(bot):
    """En setup_hook: botón persistente y revisión periódica. Avisa en el log si data/encuesta.json no vale."""
    global _bot
    try:
        cargar_preguntas()
    except (OSError, ValueError, KeyError) as e:
        log.error("❌ data/encuesta.json no es válido: %s", e)
    bot.add_dynamic_items(BotonResponderEncuesta)
    if not _revision_periodica.is_running():
        _bot = bot
        _revision_periodica.start()
