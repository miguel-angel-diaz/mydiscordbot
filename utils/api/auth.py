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
from utils import validacion_web as v
from utils.commons import buscar_usuario_en_servidor, nombre_miembro
from utils.api import comun

# ============================================================
# JWT (configuración centralizada en config.py)
# ============================================================
SECRET_KEY = config.JWT_SECRET
SESSION_EXPIRATION_SECONDS = config.SESSION_EXPIRATION_SECONDS


def crear_token(discord_id: str) -> str:
    payload = {
        'discord_id': discord_id,
        'exp': time.time() + SESSION_EXPIRATION_SECONDS
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')


def obtener_token(request, body: dict | None = None) -> str | None:
    """
    Token de sesión de la petición. Prioridad: cabecera `Authorization: Bearer <token>`,
    luego `session` en el cuerpo JSON y por último `?session=` (compatibilidad con la web actual).
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    if body and body.get("session"):
        return body.get("session")
    return request.query.get("session")


def verificar_token(token: str) -> dict | None:
    if not token:
        return None
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except jwt.InvalidTokenError:
        return None


# ============================================================
# DECORADOR DE SESIÓN
# ============================================================
@dataclass
class Sesion:
    discord_id: str
    body: dict = field(default_factory=dict)       # cuerpo JSON (vacío en los GET)
    guild: discord.Guild | None = None
    miembro: discord.Member | None = None


def requiere_sesion(handler=None, *, servidor: bool = False, miembro: bool = False):
    """
    Endpoint con sesión: lee el cuerpo JSON (en los POST) y el token, y responde 401 si no es válido.
    Con `servidor=True` exige el servidor de Discord (503 si no está) y con `miembro=True` además que el usuario
    siga en él (403). El handler recibe `(request, sesion)`.
    """
    def decorador(handler):
        @functools.wraps(handler)
        async def envoltura(request):
            body = await v.leer_json(request) if request.method == "POST" else {}
            payload = verificar_token(obtener_token(request, body))
            if not payload:
                return web.json_response({"error": "Sesión no válida"}, status=401)
            sesion = Sesion(str(payload["discord_id"]), body)
            if servidor or miembro:
                sesion.guild = comun.servidor()
                if not sesion.guild:
                    return comun.no_disponible()
            if miembro:
                sesion.miembro = sesion.guild.get_member(int(sesion.discord_id))
                if not sesion.miembro:
                    return web.json_response({"error": "No se pudo verificar tu membresía"}, status=403)
            return await handler(request, sesion)
        return envoltura
    return decorador(handler) if handler else decorador


# ============================================================
# CÓDIGOS PENDIENTES PARA AUTENTICACIÓN POR DM
# ============================================================
codigos_pendientes = {}        # nombre_key -> {codigo, discord_id, username, expira, enviado_en, intentos}
bloqueos_login = {}            # discord_id -> timestamp hasta el que no puede pedir ni verificar códigos
CODIGO_EXPIRA_SEGUNDOS = 300
CODIGO_REENVIO_MINIMO = 60
CODIGO_LONGITUD = 8
CODIGO_MAX_INTENTOS = 3        # como el PIN de una tarjeta
CODIGO_BLOQUEO_SEGUNDOS = 900  # 15 minutos tras agotar los intentos

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
    for clave in [k for k, p in codigos_pendientes.items() if p["expira"] < ahora]:
        del codigos_pendientes[clave]
    for uid in [k for k, hasta in bloqueos_login.items() if hasta < ahora]:
        del bloqueos_login[uid]


def _minutos_bloqueo_restantes(discord_id: str) -> int:
    hasta = bloqueos_login.get(discord_id)
    if not hasta:
        return 0
    return max(1, int((hasta - time.time() + 59) // 60))


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

    nombre_key = nombre.lower()
    pendiente_actual = codigos_pendientes.get(nombre_key)
    if pendiente_actual:
        segundos_desde_envio = time.time() - pendiente_actual.get("enviado_en", 0)
        if segundos_desde_envio < CODIGO_REENVIO_MINIMO:
            espera = int(CODIGO_REENVIO_MINIMO - segundos_desde_envio)
            return web.json_response(
                {"error": f"Espera {espera}s antes de pedir un nuevo código"},
                status=429
            )

    miembro = buscar_usuario_en_servidor(guild, nombre)
    if not miembro:
        return web.json_response(
            {"error": "No hemos podido verificarte. Comprueba tu usuario."},
            status=404
        )

    discord_id = str(miembro.id)
    minutos = _minutos_bloqueo_restantes(discord_id)
    if minutos:
        return web.json_response(
            {"error": f"Acceso bloqueado por demasiados intentos fallidos. Inténtalo de nuevo en {minutos} min."},
            status=429
        )

    # Un único código activo por usuario (aunque lo pida con otra variante del nombre)
    for clave in [k for k, p in codigos_pendientes.items() if p["discord_id"] == discord_id]:
        del codigos_pendientes[clave]

    codigo = generar_codigo_acceso()
    codigos_pendientes[nombre_key] = {
        "codigo": codigo,
        "discord_id": discord_id,
        "username": miembro.display_name,
        "expira": time.time() + CODIGO_EXPIRA_SEGUNDOS,
        "enviado_en": time.time(),
        "intentos": 0,
    }

    try:
        await miembro.send(
            f"🔐 Tu código de acceso para **The Klub** es: `{codigo}`\n"
            f"Distingue mayúsculas y minúsculas. Caduca en 5 minutos y tienes {CODIGO_MAX_INTENTOS} intentos.\n"
            f"Si no has solicitado esto, ignora este mensaje."
        )
    except Exception:
        del codigos_pendientes[nombre_key]
        return web.json_response(
            {"error": "No hemos podido enviarte el código. Revisa que tienes los DMs abiertos para miembros del servidor."},
            status=400
        )

    return web.json_response({"ok": True, "mensaje": "Código enviado por Discord"})


async def _avisar_bloqueo_login(discord_id: str):
    """Avisa por DM al usuario de que alguien ha agotado los intentos con su código."""
    guild = comun.servidor()
    miembro = guild.get_member(int(discord_id)) if guild else None
    if not miembro:
        return
    try:
        await miembro.send(
            f"⚠️ Se ha introducido mal tu código de acceso a **The Klub** {CODIGO_MAX_INTENTOS} veces. "
            f"Por seguridad, el acceso queda bloqueado {CODIGO_BLOQUEO_SEGUNDOS // 60} minutos.\n"
            f"Si no has sido tú, no compartas nunca tus códigos."
        )
    except discord.HTTPException:
        pass


async def auth_verificar_codigo(request):
    body = await v.leer_json(request)

    nombre = str(body.get("nombre", "")).strip().lower()[:v.MAX_NOMBRE]
    codigo_introducido = str(body.get("codigo", "")).strip()[:v.MAX_CODIGO_ACCESO]

    pendiente = codigos_pendientes.get(nombre)
    if pendiente and time.time() > pendiente["expira"]:
        del codigos_pendientes[nombre]
        return web.json_response({"error": "El código ha caducado, solicita uno nuevo"}, status=400)

    _purgar_codigos_y_bloqueos()
    if not pendiente:
        return web.json_response({"error": "No hay ningún código pendiente para ese usuario"}, status=400)

    discord_id = pendiente["discord_id"]
    if _minutos_bloqueo_restantes(discord_id):
        del codigos_pendientes[nombre]
        return web.json_response({"error": "Acceso bloqueado por demasiados intentos fallidos."}, status=429)

    if not secrets.compare_digest(codigo_introducido.encode(), pendiente["codigo"].encode()):
        pendiente["intentos"] = pendiente.get("intentos", 0) + 1
        restantes = CODIGO_MAX_INTENTOS - pendiente["intentos"]
        if restantes > 0:
            return web.json_response(
                {"error": f"Código incorrecto. Te quedan {restantes} intento(s).", "intentos_restantes": restantes},
                status=400
            )

        # Intentos agotados: se invalida el código y se bloquea al usuario un tiempo
        del codigos_pendientes[nombre]
        bloqueos_login[discord_id] = time.time() + CODIGO_BLOQUEO_SEGUNDOS
        await _avisar_bloqueo_login(discord_id)
        return web.json_response(
            {
                "error": f"Has agotado los {CODIGO_MAX_INTENTOS} intentos. "
                         f"Acceso bloqueado {CODIGO_BLOQUEO_SEGUNDOS // 60} minutos.",
                "intentos_restantes": 0,
            },
            status=429
        )

    token = crear_token(discord_id)
    del codigos_pendientes[nombre]

    guild = comun.servidor()
    username = pendiente.get("username", "Usuario")
    if guild:
        username = await nombre_miembro(guild, discord_id, username)

    return web.json_response({
        "ok": True,
        "session": token,
        "username": username,
    })


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

    embed = discord.Embed(
        title="📩 Nueva solicitud de admisión",
        color=0xff8800
    )
    embed.add_field(name="Discord", value=discord_nick, inline=True)
    embed.add_field(name="Email", value=email, inline=True)
    embed.add_field(name="Comentario", value=comentario, inline=False)
    embed.timestamp = datetime.now(timezone.utc)

    await canal.send(embed=embed)

    return web.json_response({"ok": True})
