######## sorteos.py #######
"""
Sorteo de premios al terminar un torneo (suizo o battle), con aceptación del ganador y recogida de datos de envío.

Flujo:
  1. Al finalizar un suizo, el bot pregunta por DM al DUEÑO del servidor si hay sorteo (botones Sí / No).
     Un admin también puede lanzarlo a mano con !sorteo-torneo. Mientras haya un sorteo sin cerrar, el torneo no se
     puede eliminar (se perdería la lista de participantes).
  2. "Sí" abre un formulario con los premios ("Tapete" / "Token x4"). Cada premio se sortea entre los participantes
     (inscritos no retirados que sigan en el servidor; nadie gana dos veces).
  3. Cada ganador recibe un DM con Aceptar / Renunciar y PLAZO_ACEPTACION para contestar. Si renuncia, no contesta
     a tiempo o tiene los DMs cerrados, ese premio se vuelve a sortear entre los demás.
  4. Aceptar abre un formulario con los datos de envío. Se publican SOLO en #premios (canal privado; si no existe o
     lo pueden ver los jugadores, van por DM al dueño) con un botón "Enviado" que borra los datos del mensaje.
     Lo que no se marque como enviado se borra solo a los DIAS_CONSERVACION días.

Datos personales: no se guardan en disco, ni en el estado del torneo, ni en el log. Solo existen en ese mensaje de
#premios. El estado del sorteo (premios, IDs de ganadores, plazos) va en el estado del torneo, como el resto.

Estado (clave "sorteo" del torneo en #torneos-estado):
    {"estado": "pregunta" | "en_curso" | "cerrado" | "sin_sorteo", "responsable": "<id>",
     "premios": [{"nombre", "ganador": "<id>" | None, "estado": "pendiente" | "aceptado" | "desierto", "plazo"}],
     "descartados": ["<id>", ...]}      # renunciaron, no contestaron o no se les pudo escribir
"""
import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import discord
from discord.ext import tasks

import config
from utils import canales
from utils.torneos_estado import actualizar_torneo_estado, leer_estado, obtener_torneo_estado

log = logging.getLogger(__name__)

PLAZO_ACEPTACION = timedelta(hours=48)
DIAS_CONSERVACION = 30            # días que pueden quedar datos de envío en #premios sin marcar como enviados
MAX_PREMIOS = 20
MAX_NOMBRE_PREMIO = 80
INTERVALO_REVISION_MIN = 30       # cada cuánto se revisan plazos vencidos y datos caducados

PREGUNTA, EN_CURSO, CERRADO, SIN_SORTEO = "pregunta", "en_curso", "cerrado", "sin_sorteo"
PENDIENTE, ACEPTADO, DESIERTO = "pendiente", "aceptado", "desierto"

PATRON_CODIGO = r"[A-Za-z0-9_-]+"
PATRON_CANTIDAD = re.compile(r"^(?:(?P<pre>\d+)\s*[x×]\s+(?P<nombre_pre>.+)|(?P<nombre_post>.+?)\s*\(?\s*[x×]\s*(?P<post>\d+)\s*\)?)$",
                             re.IGNORECASE)

SIN_MENCIONES = discord.AllowedMentions.none()
SOLO_USUARIOS = discord.AllowedMentions(users=True, roles=False, everyone=False)

_rng = secrets.SystemRandom()
_locks: Dict[str, asyncio.Lock] = {}


def _lock(codigo: str) -> asyncio.Lock:
    return _locks.setdefault(codigo, asyncio.Lock())


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# LÓGICA PURA (sin Discord; probada en tests/test_sorteos.py)
# ============================================================

def parsear_premios(texto: str) -> List[str]:
    """
    "Tapete\\nToken x4" o "Tapete, 4x Token" -> ["Tapete", "Token", "Token", "Token", "Token"].
    Lanza ValueError con un mensaje para el usuario si no hay premios, son demasiados o un nombre es muy largo.
    """
    premios = []
    for linea in re.split(r"[\n,;]", texto or ""):
        linea = " ".join(linea.split())
        if not linea:
            continue
        m = PATRON_CANTIDAD.match(linea)
        if m:
            nombre = (m["nombre_pre"] or m["nombre_post"]).strip()
            cantidad = int(m["pre"] or m["post"])
        else:
            nombre, cantidad = linea, 1
        if not nombre:
            raise ValueError(f"Falta el nombre del premio en «{linea}».")
        if len(nombre) > MAX_NOMBRE_PREMIO:
            raise ValueError(f"El nombre «{nombre[:30]}…» es demasiado largo (máximo {MAX_NOMBRE_PREMIO} caracteres).")
        if cantidad < 1:
            raise ValueError(f"La cantidad de «{nombre}» debe ser al menos 1.")
        premios.extend([nombre] * cantidad)
        if len(premios) > MAX_PREMIOS:
            raise ValueError(f"Como mucho se pueden sortear {MAX_PREMIOS} premios a la vez.")
    if not premios:
        raise ValueError("No has indicado ningún premio.")
    return premios


def ids_participantes(torneo: dict) -> List[str]:
    """Inscritos de un suizo que no se retiraron (los de un battle se leen aparte, ver _participantes)."""
    retirados = {str(r) for r in torneo.get("retirados", [])}
    return [str(p) for p in torneo.get("inscritos_ids", []) if str(p) not in retirados]


def candidatos(participantes: Iterable, sorteo: dict, presentes: Optional[set] = None) -> List[str]:
    """Quién puede ganar ahora: sin premio pendiente o aceptado, no descartado y (si se indica) aún en el servidor."""
    ocupados = {str(p.get("ganador")) for p in sorteo.get("premios", [])
                if p.get("ganador") and p.get("estado") in (PENDIENTE, ACEPTADO)}
    descartados = {str(d) for d in sorteo.get("descartados", [])}
    vistos, resultado = set(), []
    for pid in map(str, participantes):
        if pid in vistos or pid in ocupados or pid in descartados:
            continue
        if presentes is not None and pid not in presentes:
            continue
        vistos.add(pid)
        resultado.append(pid)
    return resultado


def sorteo_abierto(sorteo: Optional[dict]) -> bool:
    return bool(sorteo) and sorteo.get("estado") in (PREGUNTA, EN_CURSO)


def todo_resuelto(sorteo: dict) -> bool:
    return all(p.get("estado") in (ACEPTADO, DESIERTO) for p in sorteo.get("premios", []))


def plazo_vencido(premio: dict, ahora: datetime) -> bool:
    if premio.get("estado") != PENDIENTE or not premio.get("plazo"):
        return False
    try:
        return datetime.fromisoformat(premio["plazo"]) <= ahora
    except ValueError:
        return False


def motivo_bloqueo_eliminar(torneo: Optional[dict]) -> Optional[str]:
    """Texto para el admin si el torneo no se puede eliminar todavía por su sorteo; None si se puede."""
    sorteo = (torneo or {}).get("sorteo")
    if not sorteo_abierto(sorteo):
        return None
    if sorteo.get("estado") == PREGUNTA:
        return ("el dueño del servidor aún no ha dicho si hay sorteo. Que conteste al mensaje privado del bot "
                "(«No hay sorteo» desbloquea el torneo).")
    premios = sorteo.get("premios", [])
    resueltos = sum(1 for p in premios if p.get("estado") in (ACEPTADO, DESIERTO))
    return (f"tiene un sorteo en curso ({resueltos}/{len(premios)} premios resueltos). Se podrá eliminar cuando "
            f"todos los ganadores acepten o renuncien (plazo de {int(PLAZO_ACEPTACION.total_seconds() // 3600)} h).")


def resumen_premios(sorteo: dict) -> str:
    lineas = []
    for p in sorteo.get("premios", []):
        if p.get("estado") == ACEPTADO:
            lineas.append(f"✅ **{p['nombre']}** → <@{p['ganador']}>")
        elif p.get("estado") == DESIERTO:
            lineas.append(f"➖ **{p['nombre']}** → desierto (no quedan participantes)")
        else:
            lineas.append(f"⏳ **{p['nombre']}** → <@{p['ganador']}> (pendiente de aceptar)")
    return "\n".join(lineas) or "Sin premios."


# ============================================================
# ACCESO A DISCORD
# ============================================================

def _servidor(bot) -> Optional[discord.Guild]:
    return bot.get_guild(config.GUILD_ID_ADMISION) or (bot.guilds[0] if bot.guilds else None)


async def _dueno(guild: discord.Guild) -> Optional[discord.abc.User]:
    if guild.owner:
        return guild.owner
    try:
        return await guild.fetch_member(guild.owner_id)
    except discord.HTTPException:
        return None


def _es_gestor(guild: Optional[discord.Guild], usuario) -> bool:
    """Puede gestionar sorteos: el dueño del servidor, el rol admin o el permiso de administrador."""
    if guild is None:
        return False
    if usuario.id == guild.owner_id:
        return True
    miembro = guild.get_member(usuario.id)
    if miembro is None:
        return False
    rol_admin = canales.get_rol(guild, canales.ROL_ADMIN)
    return miembro.guild_permissions.administrator or (rol_admin is not None and rol_admin in miembro.roles)


def canal_premios_seguro(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """
    #premios solo si es privado: si @everyone o algún rol de jugador puede verlo, no se usa (los datos irían por DM
    al dueño) para que un permiso mal puesto no deje las direcciones a la vista de todos.
    """
    canal = canales.get_canal(guild, canales.PREMIOS)
    if canal is None:
        return None
    roles = [guild.default_role] + [r for r in (canales.get_rol(guild, n) for n in canales.ROLES_JUGADORES) if r]
    if any(canal.permissions_for(r).view_channel for r in roles):
        log.warning("⚠️ #%s lo pueden ver @everyone o los jugadores: los datos de envío irán por DM al dueño", canal.name)
        return None
    return canal


async def _participantes(bot, codigo: str, torneo: dict) -> List[str]:
    if torneo.get("tipo") == "battle":
        from utils.battle import participantes   # import local: evita el ciclo battle → swiss_handle → ... → sorteos
        return [str(p) for p in await participantes(bot, codigo)]
    return ids_participantes(torneo)


async def _guardar(bot, codigo: str, sorteo: Optional[dict]):
    await actualizar_torneo_estado(bot, codigo, {"sorteo": sorteo})


async def _avisar(usuario, texto: str, **kwargs) -> bool:
    if usuario is None:
        return False
    try:
        await usuario.send(texto, **kwargs)
        return True
    except discord.HTTPException:
        return False


async def _avisar_gestores(bot, guild: discord.Guild, sorteo: dict, texto: str):
    """Al responsable del sorteo y al dueño (una sola vez si son la misma persona)."""
    destinatarios = {guild.owner_id}
    if sorteo.get("responsable"):
        destinatarios.add(int(sorteo["responsable"]))
    for uid in destinatarios:
        usuario = guild.get_member(uid) or bot.get_user(uid)
        await _avisar(usuario, texto, allowed_mentions=SIN_MENCIONES)


def _nombre_torneo(torneo: dict, codigo: str) -> str:
    return torneo.get("nombre") or codigo


# ============================================================
# 1) PREGUNTA: ¿HAY SORTEO?
# ============================================================

def _vista_pregunta(codigo: str) -> discord.ui.View:
    vista = discord.ui.View(timeout=None)
    vista.add_item(BotonHaySorteo(codigo))
    vista.add_item(BotonNoHaySorteo(codigo))
    return vista


async def preguntar_si_hay_sorteo(bot, codigo: str, guild: discord.Guild = None, destinatario=None) -> Tuple[bool, str]:
    """
    Pregunta por DM si hay sorteo en el torneo: al dueño del servidor (al finalizar) o a `destinatario` (a mano).
    No hace nada si el torneo ya tiene un sorteo abierto o cerrado.
    """
    guild = guild or _servidor(bot)
    if guild is None:
        return False, "No encuentro el servidor."
    async with _lock(codigo):
        torneo = await obtener_torneo_estado(bot, codigo)
        if not torneo:
            return False, f"El torneo `{codigo}` no existe."
        sorteo = torneo.get("sorteo") or {}
        if sorteo.get("estado") in (EN_CURSO, CERRADO):
            return False, f"El torneo `{codigo}` ya tiene un sorteo ({'en curso' if sorteo['estado'] == EN_CURSO else 'cerrado'})."
        destinatario = destinatario or await _dueno(guild)
        if destinatario is None:
            return False, "No encuentro al dueño del servidor."
        # Primero se guarda (bloquea eliminar el torneo) y luego se pregunta; si el DM falla se deshace
        await _guardar(bot, codigo, {"estado": PREGUNTA, "responsable": str(destinatario.id)})
        try:
            await destinatario.send(
                f"🏁 El torneo **{_nombre_torneo(torneo, codigo)}** (`{codigo}`) ha terminado.\n"
                "🎁 **¿Hay sorteo de premios?**\n"
                "Hasta que contestes no se podrá eliminar el torneo (se perdería la lista de participantes).",
                view=_vista_pregunta(codigo), allowed_mentions=SIN_MENCIONES)
        except discord.HTTPException:
            await _guardar(bot, codigo, sorteo or None)
            return False, f"No pude escribir por privado a {destinatario}: que active los DMs del servidor."
    return True, f"Pregunta de sorteo enviada por privado a {destinatario}."


async def al_finalizar_torneo(bot, codigo: str, guild: discord.Guild = None):
    """Gancho del suizo al terminar: nunca rompe la finalización aunque falle."""
    try:
        ok, msg = await preguntar_si_hay_sorteo(bot, codigo, guild)
        if not ok:
            log.info("Sorteo de %s: %s", codigo, msg)
    except Exception:
        log.exception("❌ No se pudo preguntar por el sorteo de %s", codigo)


class BotonHaySorteo(discord.ui.DynamicItem[discord.ui.Button], template=rf"sorteo:si:(?P<codigo>{PATRON_CODIGO})"):
    def __init__(self, codigo: str):
        super().__init__(discord.ui.Button(label="Sí, hay sorteo", emoji="🎁", style=discord.ButtonStyle.success,
                                           custom_id=f"sorteo:si:{codigo}"))
        self.codigo = codigo

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["codigo"])

    async def callback(self, interaction: discord.Interaction):
        if not _es_gestor(_servidor(interaction.client), interaction.user):
            await interaction.response.send_message("❌ Solo el dueño o un admin pueden gestionar el sorteo.")
            return
        await interaction.response.send_modal(FormularioPremios(self.codigo))


class BotonNoHaySorteo(discord.ui.DynamicItem[discord.ui.Button], template=rf"sorteo:no:(?P<codigo>{PATRON_CODIGO})"):
    def __init__(self, codigo: str):
        super().__init__(discord.ui.Button(label="No hay sorteo", style=discord.ButtonStyle.secondary,
                                           custom_id=f"sorteo:no:{codigo}"))
        self.codigo = codigo

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["codigo"])

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        if not _es_gestor(_servidor(bot), interaction.user):
            await interaction.response.send_message("❌ Solo el dueño o un admin pueden gestionar el sorteo.")
            return
        await interaction.response.defer()
        async with _lock(self.codigo):
            torneo = await obtener_torneo_estado(bot, self.codigo)
            sorteo = (torneo or {}).get("sorteo") or {}
            if not torneo or sorteo.get("estado") != PREGUNTA:
                await interaction.followup.send("ℹ️ Esta pregunta ya no está activa (el sorteo ya se hizo o el torneo no existe).")
                return
            await _guardar(bot, self.codigo, {"estado": SIN_SORTEO, "responsable": str(interaction.user.id)})
        await _quitar_botones(interaction)
        await interaction.followup.send(f"👍 Sin sorteo. El torneo `{self.codigo}` ya se puede eliminar cuando quieras.")


class FormularioPremios(discord.ui.Modal, title="Premios del sorteo"):
    premios = discord.ui.TextInput(
        label="Premios (uno por línea)", style=discord.TextStyle.paragraph, max_length=600,
        placeholder="Tapete\nToken x4")

    def __init__(self, codigo: str):
        super().__init__()
        self.codigo = codigo

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nombres = parsear_premios(self.premios.value)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e} Pulsa otra vez «Sí, hay sorteo» para corregirlo.")
            return
        await interaction.response.defer(thinking=True)
        ok, msg = await iniciar_sorteo(interaction.client, self.codigo, nombres, interaction.user)
        if ok:
            await _quitar_botones(interaction)
        await interaction.followup.send(f"{'✅' if ok else '❌'} {msg}", allowed_mentions=SIN_MENCIONES)


# ============================================================
# 2) SORTEO Y AVISO A LOS GANADORES
# ============================================================

def _vista_ganador(codigo: str, idx: int, uid: str) -> discord.ui.View:
    vista = discord.ui.View(timeout=None)
    vista.add_item(BotonAceptarPremio(codigo, idx, uid))
    vista.add_item(BotonRenunciarPremio(codigo, idx, uid))
    return vista


def _texto_ganador(nombre_torneo: str, premio: str, plazo: datetime) -> str:
    limite = discord.utils.format_dt(plazo, "F")
    return (
        f"🎉 **¡Enhorabuena!** Te ha tocado **{premio}** en el sorteo del torneo **{nombre_torneo}**.\n\n"
        f"Tienes hasta el {limite} para aceptarlo; si no, se sorteará de nuevo.\n\n"
        "🔒 **Sobre tus datos:** al aceptar te pediremos los datos de envío en un formulario. Solo se usan para "
        "mandarte el premio, solo los ven los organizadores en un canal privado y se borran en cuanto se envía "
        f"(como mucho a los {DIAS_CONSERVACION} días). El bot no los guarda en ningún otro sitio."
    )


async def _asignar(bot, guild: discord.Guild, codigo: str, torneo: dict, sorteo: dict, idx: int, participantes: List[str]):
    """
    Sortea el premio `idx` entre los candidatos y avisa al ganador. Si no se le puede escribir, se descarta y se
    prueba con otro; si no queda nadie, el premio queda desierto. Modifica `sorteo` (lo guarda quien llama).
    """
    premio = sorteo["premios"][idx]
    presentes = {str(m.id) for m in guild.members}
    while True:
        opciones = candidatos(participantes, sorteo, presentes)
        if not opciones:
            premio.update({"ganador": None, "estado": DESIERTO, "plazo": None})
            return
        elegido = _rng.choice(opciones)
        plazo = _ahora() + PLAZO_ACEPTACION
        premio.update({"ganador": elegido, "estado": PENDIENTE, "plazo": plazo.isoformat()})
        miembro = guild.get_member(int(elegido))
        if await _avisar(miembro, _texto_ganador(_nombre_torneo(torneo, codigo), premio["nombre"], plazo),
                         view=_vista_ganador(codigo, idx, elegido)):
            return
        log.info("Sorteo %s: no se pudo escribir al ganador %s; se vuelve a sortear", codigo, elegido)
        sorteo.setdefault("descartados", []).append(elegido)


async def iniciar_sorteo(bot, codigo: str, nombres_premios: List[str], responsable) -> Tuple[bool, str]:
    guild = _servidor(bot)
    if guild is None:
        return False, "No encuentro el servidor."
    async with _lock(codigo):
        torneo = await obtener_torneo_estado(bot, codigo)
        if not torneo:
            return False, f"El torneo `{codigo}` ya no existe."
        if (torneo.get("sorteo") or {}).get("estado") in (EN_CURSO, CERRADO):
            return False, f"El torneo `{codigo}` ya tiene un sorteo hecho."
        participantes = await _participantes(bot, codigo, torneo)
        sorteo = {"estado": EN_CURSO, "responsable": str(responsable.id), "descartados": [],
                  "premios": [{"nombre": n, "ganador": None, "estado": PENDIENTE, "plazo": None} for n in nombres_premios]}
        if not candidatos(participantes, sorteo, {str(m.id) for m in guild.members}):
            return False, "No hay participantes válidos (inscritos no retirados que sigan en el servidor)."
        # Se guarda antes de escribir a nadie: así un botón pulsado al instante ya encuentra el sorteo
        await _guardar(bot, codigo, sorteo)
        for idx in range(len(sorteo["premios"])):
            await _asignar(bot, guild, codigo, torneo, sorteo, idx, participantes)
        sorteo = await _cerrar_si_resuelto(bot, guild, codigo, torneo, sorteo)
        await _guardar(bot, codigo, sorteo)
    sin_dm = ", ".join(f"<@{d}>" for d in sorteo.get("descartados", []))
    aviso_dm = f"\n⚠️ Quedan fuera por tener los DMs cerrados: {sin_dm}" if sin_dm else ""
    return True, (f"Sorteo del torneo `{codigo}` hecho. Los ganadores tienen "
                  f"{int(PLAZO_ACEPTACION.total_seconds() // 3600)} h para aceptar; te iré avisando.\n"
                  f"{resumen_premios(sorteo)}{aviso_dm}")


async def _cerrar_si_resuelto(bot, guild, codigo: str, torneo: dict, sorteo: dict) -> dict:
    if sorteo.get("estado") == EN_CURSO and todo_resuelto(sorteo):
        sorteo["estado"] = CERRADO
        await _avisar_gestores(bot, guild, sorteo,
                               f"🏁 Sorteo del torneo **{_nombre_torneo(torneo, codigo)}** cerrado. "
                               f"Ya se puede eliminar el torneo.\n{resumen_premios(sorteo)}")
    return sorteo


async def _descartar_y_resortear(bot, guild, codigo: str, torneo: dict, sorteo: dict, idx: int, motivo: str):
    """El ganador del premio `idx` lo pierde (renuncia o plazo vencido) y se sortea de nuevo."""
    premio = sorteo["premios"][idx]
    anterior = premio.get("ganador")
    sorteo.setdefault("descartados", []).append(anterior)
    await _asignar(bot, guild, codigo, torneo, sorteo, idx, await _participantes(bot, codigo, torneo))
    nuevo = f"nuevo ganador: <@{premio['ganador']}>" if premio["estado"] == PENDIENTE else "queda desierto"
    await _avisar_gestores(bot, guild, sorteo,
                           f"🔁 Sorteo de **{_nombre_torneo(torneo, codigo)}**: <@{anterior}> {motivo} "
                           f"**{premio['nombre']}**; {nuevo}.")


def _premio_del_ganador(torneo: Optional[dict], idx: int, uid: int) -> Optional[dict]:
    """El premio `idx` si sigue pendiente, es de `uid` y está en plazo."""
    sorteo = (torneo or {}).get("sorteo") or {}
    premios = sorteo.get("premios", [])
    if sorteo.get("estado") != EN_CURSO or not 0 <= idx < len(premios):
        return None
    premio = premios[idx]
    if premio.get("estado") != PENDIENTE or str(premio.get("ganador")) != str(uid) or plazo_vencido(premio, _ahora()):
        return None
    return premio


NO_DISPONIBLE = "ℹ️ Este premio ya no está disponible (se aceptó, se renunció o venció el plazo)."


class BotonAceptarPremio(discord.ui.DynamicItem[discord.ui.Button],
                         template=rf"sorteo:acepto:(?P<codigo>{PATRON_CODIGO}):(?P<idx>\d+):(?P<uid>\d+)"):
    def __init__(self, codigo: str, idx: int, uid):
        super().__init__(discord.ui.Button(label="Aceptar premio", emoji="✅", style=discord.ButtonStyle.success,
                                           custom_id=f"sorteo:acepto:{codigo}:{idx}:{uid}"))
        self.codigo, self.idx, self.uid = codigo, int(idx), int(uid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["codigo"], match["idx"], match["uid"])

    async def callback(self, interaction: discord.Interaction):
        # El formulario tiene que abrirse en <3 s: aquí solo se comprueba quién pulsa; el resto, al enviarlo
        if interaction.user.id != self.uid:
            await interaction.response.send_message("❌ Este premio no es tuyo.")
            return
        await interaction.response.send_modal(FormularioEnvio(self.codigo, self.idx))


class BotonRenunciarPremio(discord.ui.DynamicItem[discord.ui.Button],
                           template=rf"sorteo:renuncio:(?P<codigo>{PATRON_CODIGO}):(?P<idx>\d+):(?P<uid>\d+)"):
    def __init__(self, codigo: str, idx: int, uid):
        super().__init__(discord.ui.Button(label="Renunciar", style=discord.ButtonStyle.secondary,
                                           custom_id=f"sorteo:renuncio:{codigo}:{idx}:{uid}"))
        self.codigo, self.idx, self.uid = codigo, int(idx), int(uid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["codigo"], match["idx"], match["uid"])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("❌ Este premio no es tuyo.")
            return
        # Confirmación: renunciar no tiene vuelta atrás
        await interaction.response.send_message("⚠️ ¿Seguro que renuncias al premio? Se sorteará entre los demás.",
                                                view=ConfirmarRenuncia(self.codigo, self.idx, interaction.message))


class ConfirmarRenuncia(discord.ui.View):
    def __init__(self, codigo: str, idx: int, mensaje_premio: Optional[discord.Message]):
        super().__init__(timeout=120)
        self.codigo, self.idx, self.mensaje_premio = codigo, idx, mensaje_premio

    @discord.ui.button(label="Sí, renuncio", style=discord.ButtonStyle.danger)
    async def si(self, interaction: discord.Interaction, _boton):
        await interaction.response.edit_message(content="⏳ Procesando…", view=None)
        bot = interaction.client
        guild = _servidor(bot)
        async with _lock(self.codigo):
            torneo = await obtener_torneo_estado(bot, self.codigo)
            if guild is None or _premio_del_ganador(torneo, self.idx, interaction.user.id) is None:
                await interaction.edit_original_response(content=NO_DISPONIBLE)
                return
            sorteo = torneo["sorteo"]
            await _descartar_y_resortear(bot, guild, self.codigo, torneo, sorteo, self.idx, "ha renunciado a")
            sorteo = await _cerrar_si_resuelto(bot, guild, self.codigo, torneo, sorteo)
            await _guardar(bot, self.codigo, sorteo)
        if self.mensaje_premio:
            try:
                await self.mensaje_premio.edit(view=None)
            except discord.HTTPException:
                pass
        await interaction.edit_original_response(content="👍 Has renunciado al premio. ¡Gracias por avisar!")

    @discord.ui.button(label="No, me lo quedo", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, _boton):
        await interaction.response.edit_message(content="👍 Perfecto, sigue pudiendo aceptarlo con el botón de arriba.", view=None)


# ============================================================
# 3) DATOS DE ENVÍO -> #premios
# ============================================================

class FormularioEnvio(discord.ui.Modal, title="Datos de envío del premio"):
    nombre = discord.ui.TextInput(label="Nombre y apellidos", max_length=100)
    direccion = discord.ui.TextInput(label="Dirección (calle, número, piso)", style=discord.TextStyle.paragraph,
                                     max_length=200)
    codigo_postal = discord.ui.TextInput(label="Código postal", min_length=4, max_length=10)
    localidad = discord.ui.TextInput(label="Localidad y provincia", max_length=100)
    telefono = discord.ui.TextInput(label="Teléfono (lo pide la mensajería)", min_length=6, max_length=20)

    def __init__(self, codigo: str, idx: int):
        super().__init__()
        self.codigo, self.idx = codigo, idx

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        bot = interaction.client
        guild = _servidor(bot)
        async with _lock(self.codigo):
            torneo = await obtener_torneo_estado(bot, self.codigo)
            premio = _premio_del_ganador(torneo, self.idx, interaction.user.id)
            if guild is None or premio is None:
                await interaction.followup.send(NO_DISPONIBLE + " Tus datos no se han guardado.")
                return
            # Primero los datos llegan a los organizadores; solo entonces el premio cuenta como aceptado
            if not await _publicar_datos(bot, guild, self.codigo, torneo, self.idx, premio, interaction.user, self):
                await interaction.followup.send("❌ No pude entregar tus datos a los organizadores. Inténtalo de "
                                                "nuevo en un rato con el botón «Aceptar premio».")
                return
            premio.update({"estado": ACEPTADO, "plazo": None})
            sorteo = await _cerrar_si_resuelto(bot, guild, self.codigo, torneo, torneo["sorteo"])
            await _guardar(bot, self.codigo, sorteo)
        await _quitar_botones(interaction)
        await interaction.followup.send(f"✅ ¡Premio aceptado! Los organizadores te mandarán **{premio['nombre']}**. "
                                        "Tus datos se borrarán en cuanto se envíe.")
        await _anunciar_ganador(guild, torneo, self.codigo, premio, interaction.user)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        # Sin los valores del formulario: son datos personales y no deben acabar en el log
        log.error("❌ Error procesando los datos de envío del sorteo %s (premio %s): %s",
                  self.codigo, self.idx, type(error).__name__)
        try:
            await interaction.followup.send("❌ Algo ha fallado. Inténtalo de nuevo con el botón «Aceptar premio».")
        except discord.HTTPException:
            pass


def _limpio(valor: str) -> str:
    """Texto del usuario sin formato Markdown ni menciones, para mostrarlo tal cual."""
    return discord.utils.escape_mentions(discord.utils.escape_markdown(" ".join(str(valor).split())))


def _embed_datos(torneo: dict, codigo: str, premio: dict, usuario, form: FormularioEnvio) -> discord.Embed:
    embed = discord.Embed(title=f"🎁 {premio['nombre']}", color=discord.Color.gold(),
                          description=f"Sorteo del torneo **{_limpio(_nombre_torneo(torneo, codigo))}** (`{codigo}`)")
    embed.add_field(name="Ganador", value=f"{usuario.mention} (`{usuario.id}`)", inline=False)
    embed.add_field(name="Nombre", value=_limpio(form.nombre.value), inline=False)
    embed.add_field(name="Dirección", value=_limpio(form.direccion.value), inline=False)
    embed.add_field(name="Código postal", value=_limpio(form.codigo_postal.value), inline=True)
    embed.add_field(name="Localidad", value=_limpio(form.localidad.value), inline=True)
    embed.add_field(name="Teléfono", value=_limpio(form.telefono.value), inline=True)
    embed.set_footer(text=f"Pulsa «Enviado» al mandarlo y se borran estos datos. Si no, se borran solos a los "
                          f"{DIAS_CONSERVACION} días.")
    return embed


async def _publicar_datos(bot, guild, codigo: str, torneo: dict, idx: int, premio: dict, usuario, form) -> bool:
    vista = discord.ui.View(timeout=None)
    vista.add_item(BotonEnviado(codigo, idx))
    embed = _embed_datos(torneo, codigo, premio, usuario, form)
    canal = canal_premios_seguro(guild)
    destino = canal or await _dueno(guild)
    if destino is None:
        return False
    try:
        await destino.send(embed=embed, view=vista, allowed_mentions=SIN_MENCIONES)
        return True
    except discord.HTTPException as e:
        log.warning("Sorteo %s: no se pudieron publicar los datos de envío (%s)", codigo, type(e).__name__)
        return False


async def _anunciar_ganador(guild, torneo: dict, codigo: str, premio: dict, usuario):
    canal = canales.canal_anuncios(guild)
    if canal is None:
        return
    try:
        await canal.send(f"🎁 {usuario.mention} se lleva **{_limpio(premio['nombre'])}** en el sorteo del torneo "
                         f"**{_limpio(_nombre_torneo(torneo, codigo))}**. ¡Enhorabuena!", allowed_mentions=SOLO_USUARIOS)
    except discord.HTTPException:
        log.warning("Sorteo %s: no se pudo anunciar al ganador", codigo)


def _texto_sin_datos(embed: Optional[discord.Embed], estado: str) -> str:
    """Lo que queda del mensaje de #premios cuando se borran los datos: premio, torneo y ganador."""
    if embed is None:
        return estado
    ganador = next((f.value.split(" ")[0] for f in embed.fields if f.name == "Ganador"), "")
    return f"{embed.title} — {embed.description} → {ganador}\n{estado}"


class BotonEnviado(discord.ui.DynamicItem[discord.ui.Button],
                   template=rf"sorteo:enviado:(?P<codigo>{PATRON_CODIGO}):(?P<idx>\d+)"):
    def __init__(self, codigo: str, idx: int):
        super().__init__(discord.ui.Button(label="Enviado (borrar datos)", emoji="📦",
                                           style=discord.ButtonStyle.primary,
                                           custom_id=f"sorteo:enviado:{codigo}:{idx}"))
        self.codigo, self.idx = codigo, int(idx)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["codigo"], match["idx"])

    async def callback(self, interaction: discord.Interaction):
        if not _es_gestor(_servidor(interaction.client), interaction.user):
            await interaction.response.send_message("❌ Solo el dueño o un admin pueden marcarlo.", ephemeral=True)
            return
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
        fecha = discord.utils.format_dt(_ahora(), "d")
        await interaction.response.edit_message(
            content=_texto_sin_datos(embed, f"📦 Enviado el {fecha} por {interaction.user.mention}. Datos borrados."),
            embed=None, view=None, allowed_mentions=SIN_MENCIONES)


# ============================================================
# 4) REVISIÓN PERIÓDICA: PLAZOS VENCIDOS Y DATOS CADUCADOS
# ============================================================

async def revisar_plazos(bot):
    guild = _servidor(bot)
    if guild is None:
        return
    ahora = _ahora()
    for torneo in (await leer_estado(bot)).get("torneos", []):
        if ((torneo.get("sorteo") or {}).get("estado")) != EN_CURSO:
            continue
        codigo = torneo["codigo"]
        async with _lock(codigo):
            torneo = await obtener_torneo_estado(bot, codigo)       # releído dentro del lock
            sorteo = (torneo or {}).get("sorteo") or {}
            vencidos = [i for i, p in enumerate(sorteo.get("premios", [])) if plazo_vencido(p, ahora)]
            if sorteo.get("estado") != EN_CURSO or not vencidos:
                continue
            for idx in vencidos:
                anterior = sorteo["premios"][idx]["ganador"]
                await _avisar(guild.get_member(int(anterior)),
                              f"⌛ Se acabó el plazo para aceptar **{sorteo['premios'][idx]['nombre']}** y se ha "
                              "sorteado de nuevo. ¡Otra vez será!")
                await _descartar_y_resortear(bot, guild, codigo, torneo, sorteo, idx, "no contestó a tiempo y pierde")
            sorteo = await _cerrar_si_resuelto(bot, guild, codigo, torneo, sorteo)
            await _guardar(bot, codigo, sorteo)


def _es_mensaje_de_datos(bot, msg: discord.Message) -> bool:
    if msg.author != bot.user or not msg.embeds:
        return False
    return any(getattr(c, "custom_id", "") and c.custom_id.startswith("sorteo:enviado:")
               for fila in msg.components for c in getattr(fila, "children", []))


async def borrar_datos_caducados(bot):
    """Borra de #premios (y del DM del dueño, si se usó) los datos de envío con más de DIAS_CONSERVACION días."""
    guild = _servidor(bot)
    if guild is None:
        return
    limite = _ahora() - timedelta(days=DIAS_CONSERVACION)
    lugares = [canales.get_canal(guild, canales.PREMIOS)]
    dueno = await _dueno(guild)
    if dueno is not None:
        try:
            lugares.append(dueno.dm_channel or await dueno.create_dm())
        except discord.HTTPException:
            pass
    for lugar in filter(None, lugares):
        async for msg in lugar.history(limit=None, before=limite):
            if not _es_mensaje_de_datos(bot, msg):
                continue
            try:
                await msg.edit(content=_texto_sin_datos(msg.embeds[0], f"🗑️ Datos borrados automáticamente "
                                                                       f"({DIAS_CONSERVACION} días sin marcar como enviado)."),
                               embed=None, view=None, allowed_mentions=SIN_MENCIONES)
            except discord.HTTPException as e:
                log.warning("No se pudieron borrar unos datos de envío caducados (%s)", type(e).__name__)


@tasks.loop(minutes=INTERVALO_REVISION_MIN)
async def _revision_periodica():
    for tarea in (revisar_plazos, borrar_datos_caducados):
        try:
            await tarea(_bot)
        except Exception:
            log.exception("❌ %s falló", tarea.__name__)


@_revision_periodica.before_loop
async def _antes_de_revision():
    await _bot.wait_until_ready()


_bot = None


# ============================================================
# UTILIDADES Y ARRANQUE
# ============================================================

async def _quitar_botones(interaction: discord.Interaction):
    """Quita los botones del mensaje que abrió el formulario o del que se pulsó (para no responder dos veces)."""
    if interaction.message is None:
        return
    try:
        await interaction.message.edit(view=None)
    except discord.HTTPException:
        pass


def registrar(bot):
    """En setup_hook: botones persistentes (siguen funcionando tras un reinicio) y revisión periódica."""
    global _bot
    bot.add_dynamic_items(BotonHaySorteo, BotonNoHaySorteo, BotonAceptarPremio, BotonRenunciarPremio, BotonEnviado)
    if not _revision_periodica.is_running():
        _bot = bot
        _revision_periodica.start()
