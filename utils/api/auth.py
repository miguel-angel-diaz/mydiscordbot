"""
Sesiones (JWT), el decorador @requiere_sesion, el login con código por DM y la solicitud de admisión.
"""
import functools
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord
import jwt
from aiohttp import web

import config
from utils import canales
from utils import permisos
from utils import validacion_web as v
from utils.commons import buscar_usuario_en_servidor, nombre_miembro
from utils.api import comun

# ============================================================
# JWT (configuración centralizada en config.py)
# ============================================================
SECRET_KEY = config.JWT_SECRET
SESSION_EXPIRATION_SECONDS = config.SESSION_EXPIRATION_SECONDS


# Cierre de sesión: discord_id -> momento del último logout. Se rechazan los tokens de ese usuario emitidos antes
# (cerrar sesión cierra todas sus sesiones). En memoria: tras reiniciar el bot se olvida, pero los tokens caducan
# en SESSION_EXPIRATION_SECONDS, así que el riesgo queda acotado a ese tiempo.
sesiones_cerradas = {}


def crear_token(discord_id: str) -> str:
    ahora = time.time()
    payload = {
        'discord_id': discord_id,
        'iat': ahora,
        'exp': ahora + SESSION_EXPIRATION_SECONDS
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')


def cerrar_sesiones(discord_id: str):
    """Invalida todos los tokens de ese usuario emitidos hasta ahora."""
    ahora = time.time()
    for uid in [u for u, t in sesiones_cerradas.items() if t < ahora - SESSION_EXPIRATION_SECONDS]:
        del sesiones_cerradas[uid]          # ya no queda ningún token tan antiguo sin caducar
    sesiones_cerradas[str(discord_id)] = ahora


def obtener_token(request) -> str | None:
    """
    Token de sesión, solo desde la cabecera `Authorization: Bearer <token>`. Ya no se acepta en `?session=` ni en el
    cuerpo (la web lo envía en la cabecera desde su commit 293af4e): en la URL acababa en historiales y logs.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def verificar_token(token: str) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except jwt.InvalidTokenError:
        return None
    # Los tokens anteriores a esta versión no llevan iat (0): un cierre de sesión también los invalida
    if payload.get('iat', 0) < sesiones_cerradas.get(str(payload.get('discord_id')), 0):
        return None
    return payload


# ============================================================
# DECORADOR DE SESIÓN
# ============================================================
@dataclass
class Sesion:
    discord_id: str
    body: dict = field(default_factory=dict)       # cuerpo JSON (vacío en los GET)
    guild: discord.Guild | None = None
    miembro: discord.Member | None = None


_MENSAJES_DENEGACION = {
    permisos.SANCIONADO: "No puedes hacer esto mientras tengas una sanción activa.",
    permisos.SIN_ROL: "Necesitas un rol de jugador del club para hacer esto.",
}


def requiere_sesion(handler=None, *, servidor: bool = False, miembro: bool = False, jugador: bool = False):
    """
    Endpoint con sesión: lee el cuerpo JSON (en los POST) y el token, y responde 401 si no es válido.
    Con `servidor=True` exige el servidor de Discord (503 si no está); con `miembro=True` además que el usuario
    siga en él (403), y con `jugador=True` que pueda usar los comandos de jugador (rol de jugador y sin sanción
    Out/Strike, la misma regla que el cog_check de Discord; 403). El handler recibe `(request, sesion)`.
    """
    def decorador(handler):
        @functools.wraps(handler)
        async def envoltura(request):
            body = await v.leer_json(request) if request.method == "POST" else {}
            payload = verificar_token(obtener_token(request))
            if not payload:
                return web.json_response({"error": "Sesión no válida"}, status=401)
            sesion = Sesion(str(payload["discord_id"]), body)
            if servidor or miembro or jugador:
                sesion.guild = comun.servidor()
                if not sesion.guild:
                    return comun.no_disponible()
            if miembro or jugador:
                sesion.miembro = sesion.guild.get_member(int(sesion.discord_id))
                if not sesion.miembro:
                    return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)
            if jugador:
                motivo = permisos.motivo_denegacion(sesion.miembro, canales.ROLES_JUGADORES)
                if motivo:
                    return web.json_response({"error": _MENSAJES_DENEGACION[motivo]}, status=403)
            return await handler(request, sesion)
        return envoltura
    return decorador(handler) if handler else decorador


# ============================================================
# CÓDIGOS PENDIENTES PARA AUTENTICACIÓN POR DM
# ============================================================
# Nadie puede perjudicar a otro desde fuera:
#   - Los intentos fallidos cuentan por IP: la IP que falla CODIGO_MAX_INTENTOS veces queda bloqueada un tiempo, pero
#     la cuenta no (antes cualquiera bloqueaba 15 minutos a otro fallando a propósito con su nombre). Con 3 intentos
#     cada 15 minutos por IP, adivinar un código de 8 caracteres es inviable.
#   - Pedir un código nuevo no anula los anteriores (hasta CODIGOS_ACTIVOS_MAX por usuario): antes se podía dejar a
#     alguien sin poder entrar pidiendo códigos a su nombre.
#   - La respuesta es la misma exista o no el usuario.
codigos_pendientes = {}        # discord_id -> [{codigo, username, expira, enviado_en}] (los más nuevos al final)
fallos_por_ip = {}             # ip -> {"fallos": n, "hasta": timestamp del bloqueo (0 si no está bloqueada)}
CODIGO_EXPIRA_SEGUNDOS = 300
CODIGO_REENVIO_MINIMO = 60
CODIGO_LONGITUD = 8
CODIGO_MAX_INTENTOS = 3        # fallos por IP antes del bloqueo
CODIGO_BLOQUEO_SEGUNDOS = 900  # 15 minutos
CODIGOS_ACTIVOS_MAX = 3
MENSAJE_CODIGO_ENVIADO = ("Si ese usuario es miembro del servidor, le hemos enviado un código por Discord. "
                          "Revisa tus mensajes directos.")

# Sin caracteres ambiguos (0/O, 1/l/I) ni los que Discord usa para formato (* _ ~ ` | \ >)
_CODIGO_MAYUS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_CODIGO_MINUS = "abcdefghijkmnpqrstuvwxyz"
_CODIGO_DIGITOS = "23456789"
_CODIGO_ESPECIALES = "!#$%&?+=@"
_CODIGO_TODOS = _CODIGO_MAYUS + _CODIGO_MINUS + _CODIGO_DIGITOS + _CODIGO_ESPECIALES


def generar_codigo_acceso() -> str:
    """Código aleatorio con al menos una mayúscula y un carácter especial."""
    chars = [secrets.choice(_CODIGO_MAYUS), secrets.choice(_CODIGO_ESPECIALES)]
    chars += [secrets.choice(_CODIGO_TODOS) for _ in range(CODIGO_LONGITUD - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _purgar_codigos_y_bloqueos():
    ahora = time.time()
    for uid in list(codigos_pendientes):
        codigos_pendientes[uid] = [c for c in codigos_pendientes[uid] if c["expira"] > ahora]
        if not codigos_pendientes[uid]:
            del codigos_pendientes[uid]
    for ip in [ip for ip, f in fallos_por_ip.items() if f["hasta"] and f["hasta"] < ahora]:
        del fallos_por_ip[ip]


def _minutos_bloqueo_ip(ip: str) -> int:
    hasta = fallos_por_ip.get(ip, {}).get("hasta", 0)
    if not hasta or hasta < time.time():
        return 0
    return max(1, int((hasta - time.time() + 59) // 60))


def _respuesta_bloqueo(minutos: int):
    return web.json_response(
        {"error": f"Demasiados intentos fallidos desde tu conexión. Inténtalo de nuevo en {minutos} min."}, status=429)


# ============================================================
# LOGIN — verificación de miembros vía código por DM
# ============================================================
async def auth_solicitar_codigo(request):
    body = await v.leer_json(request)

    nombre = str(body.get("nombre", "")).strip()
    if not nombre:
        return web.json_response({"error": "Escribe tu usuario de Discord"}, status=400)
    if len(nombre) > v.MAX_NOMBRE:
        return web.json_response({"error": "Usuario de Discord no válido"}, status=400)

    guild = comun.servidor()
    if not guild:
        return comun.no_disponible()

    _purgar_codigos_y_bloqueos()
    minutos = _minutos_bloqueo_ip(v.ip_cliente(request))
    if minutos:
        return _respuesta_bloqueo(minutos)

    # Exacto: con coincidencias parciales "a" mandaba el código al primer miembro que tuviera esa letra.
    # Si no existe se responde lo mismo que si se hubiera enviado: así no se puede saber quién es miembro.
    miembro = buscar_usuario_en_servidor(guild, nombre, exacto=True)
    if not isinstance(miembro, discord.Member):
        return web.json_response({"ok": True, "mensaje": MENSAJE_CODIGO_ENVIADO})

    discord_id = str(miembro.id)
    activos = codigos_pendientes.get(discord_id, [])
    if activos:
        segundos_desde_envio = time.time() - activos[-1]["enviado_en"]
        if segundos_desde_envio < CODIGO_REENVIO_MINIMO:
            espera = int(CODIGO_REENVIO_MINIMO - segundos_desde_envio)
            return web.json_response({"error": f"Espera {espera}s antes de pedir un nuevo código"}, status=429)

    codigo = generar_codigo_acceso()
    try:
        await miembro.send(
            f"🔐 Tu código de acceso para **The Klub** es: `{codigo}`\n"
            f"Distingue mayúsculas y minúsculas y caduca en 5 minutos.\n"
            f"Si no has solicitado esto, ignora este mensaje: nadie puede entrar sin el código."
        )
    except discord.HTTPException:
        return web.json_response(
            {"error": "No hemos podido enviarte el código. Revisa que tienes los DMs abiertos para miembros del servidor."},
            status=400
        )

    ahora = time.time()
    activos.append({"codigo": codigo, "username": miembro.display_name,
                    "expira": ahora + CODIGO_EXPIRA_SEGUNDOS, "enviado_en": ahora})
    codigos_pendientes[discord_id] = activos[-CODIGOS_ACTIVOS_MAX:]
    return web.json_response({"ok": True, "mensaje": MENSAJE_CODIGO_ENVIADO})


async def _avisar_intentos_fallidos(discord_id: str):
    """Avisa por DM al usuario de que alguien ha fallado varias veces su código (su cuenta no se bloquea)."""
    guild = comun.servidor()
    miembro = guild.get_member(int(discord_id)) if guild else None
    if not miembro:
        return
    try:
        await miembro.send(
            f"⚠️ Alguien ha introducido mal {CODIGO_MAX_INTENTOS} veces un código de acceso a **The Klub** con tu "
            f"usuario y su conexión ha quedado bloqueada {CODIGO_BLOQUEO_SEGUNDOS // 60} minutos. Tu cuenta sigue "
            f"funcionando con normalidad.\nSi no has sido tú, no compartas nunca tus códigos."
        )
    except discord.HTTPException:
        pass


async def auth_verificar_codigo(request):
    body = await v.leer_json(request)

    nombre = str(body.get("nombre", "")).strip()[:v.MAX_NOMBRE]
    codigo_introducido = str(body.get("codigo", "")).strip()[:v.MAX_CODIGO_ACCESO]
    ip = v.ip_cliente(request)

    _purgar_codigos_y_bloqueos()
    minutos = _minutos_bloqueo_ip(ip)
    if minutos:
        return _respuesta_bloqueo(minutos)

    guild = comun.servidor()
    if not guild:
        return comun.no_disponible()

    miembro = buscar_usuario_en_servidor(guild, nombre, exacto=True) if nombre else None
    discord_id = str(miembro.id) if isinstance(miembro, discord.Member) else None
    activos = codigos_pendientes.get(discord_id, []) if discord_id else []
    acierto = next((c for c in activos
                    if secrets.compare_digest(codigo_introducido.encode(), c["codigo"].encode())), None)

    if not acierto:
        fallo = fallos_por_ip.setdefault(ip, {"fallos": 0, "hasta": 0})
        fallo["fallos"] += 1
        restantes = CODIGO_MAX_INTENTOS - fallo["fallos"]
        if restantes > 0:
            return web.json_response(
                {"error": f"Código incorrecto o caducado. Te quedan {restantes} intento(s).",
                 "intentos_restantes": restantes},
                status=400
            )
        fallo["hasta"] = time.time() + CODIGO_BLOQUEO_SEGUNDOS
        if discord_id and activos:
            await _avisar_intentos_fallidos(discord_id)
        return web.json_response(
            {"error": f"Has agotado los {CODIGO_MAX_INTENTOS} intentos. Inténtalo de nuevo en "
                      f"{CODIGO_BLOQUEO_SEGUNDOS // 60} minutos.", "intentos_restantes": 0},
            status=429
        )

    # Código correcto: se gastan todos los del usuario y se olvidan los fallos de esa IP
    codigos_pendientes.pop(discord_id, None)
    fallos_por_ip.pop(ip, None)
    token = crear_token(discord_id)
    username = await nombre_miembro(guild, discord_id, acierto.get("username", "Usuario"))

    return web.json_response({
        "ok": True,
        "session": token,
        "username": username,
    })


async def auth_cerrar_sesion(request):
    """POST /auth/logout: invalida en el servidor todas las sesiones del usuario. Siempre responde ok."""
    payload = verificar_token(obtener_token(request))
    if payload:
        cerrar_sesiones(payload["discord_id"])
    return web.json_response({"ok": True})


async def auth_verificar_sesion(request):
    payload = verificar_token(obtener_token(request))
    if not payload:
        return web.json_response({"autenticado": False})

    discord_id = payload["discord_id"]
    username = "Usuario"
    guild = comun.servidor()
    if guild:
        username = await nombre_miembro(guild, discord_id, username)

    return web.json_response({
        "autenticado": True,
        "username": username,
        "discord_id": discord_id,
    })


# ============================================================
# ADMISIÓN
# ============================================================
async def api_solicitar_acceso(request):
    body = await v.leer_json(request)

    discord_nick = v.texto(body.get("discord_nick"), "usuario de Discord", v.MAX_NOMBRE)
    email = v.email(body.get("email"))
    comentario = v.texto(body.get("comentario"), "comentario", v.MAX_COMENTARIO, multilinea=True)

    guild = comun.servidor()
    if not guild:
        return comun.no_disponible()

    canal = canales.get_canal(guild, canales.SOLICITUDES_ADMISION)
    if not canal:
        return comun.no_disponible()

    # El comentario va en la descripción (hasta 4096 caracteres): escapar el markdown puede doblar su longitud y en
    # un campo (máximo 1024) Discord rechazaba el embed y la solicitud se perdía con un 500
    embed = discord.Embed(
        title="📩 Nueva solicitud de admisión",
        description=f"**Comentario**\n{comentario}",
        color=0xff8800
    )
    embed.add_field(name="Discord", value=discord_nick, inline=True)
    embed.add_field(name="Email", value=email, inline=True)
    embed.timestamp = datetime.now(timezone.utc)

    await canal.send(embed=embed)

    return web.json_response({"ok": True})
