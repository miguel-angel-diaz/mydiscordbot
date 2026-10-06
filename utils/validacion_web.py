"""
Validación y saneado de todo lo que llega desde la web antes de tocar Discord.

Los validadores lanzan `EntradaInvalida`, que el middleware de la API convierte en
un 400 con el mensaje de error, así los handlers quedan en una línea por campo.
"""
import re
import time
import unicodedata
from collections import defaultdict, deque
from datetime import date, datetime, timedelta

import discord
from aiohttp import web

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = None

# -------------------------------------------------------------
# LÍMITES
# -------------------------------------------------------------
MAX_CUERPO_BYTES = 64 * 1024        # una decklist completa ocupa ~3 KB
MAX_NOMBRE = 100
MAX_EMAIL = 254
MAX_COMENTARIO = 1000
MAX_DECKLIST = 4000
MAX_CODIGO_ACCESO = 32
DIAS_MAX_AGENDA = 365

PATRON_CODIGO_TORNEO = re.compile(r"^[A-Za-z0-9]{1,40}$")  # generar_codigo_unico / slugify solo producen [A-Za-z0-9]
PATRON_DISCORD_ID = re.compile(r"^\d{15,21}$")
PATRON_RESULTADO = re.compile(r"^([0-3])-([0-3])$")
PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FORMATOS_VALIDOS = {"premodern": "Premodern", "pauper": "Pauper"}


class EntradaInvalida(Exception):
    """Dato de la web no válido; el middleware responde 400 con este mensaje."""
    def __init__(self, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status = status


# -------------------------------------------------------------
# CUERPO JSON
# -------------------------------------------------------------
async def leer_json(request) -> dict:
    try:
        body = await request.json()
    except web.HTTPRequestEntityTooLarge:
        raise EntradaInvalida("Petición demasiado grande", status=413)
    except Exception:
        raise EntradaInvalida("JSON inválido")
    if not isinstance(body, dict):
        raise EntradaInvalida("JSON inválido")
    return body


# -------------------------------------------------------------
# TEXTO
# -------------------------------------------------------------
def _sin_controles(texto: str, multilinea: bool) -> str:
    permitidos = {"\n"} if multilinea else set()
    limpio = "".join(
        c for c in texto
        if c in permitidos or unicodedata.category(c)[0] != "C"  # Cc/Cf/Cs/Co/Cn: control, formato, etc.
    )
    if multilinea:
        limpio = re.sub(r"\n{3,}", "\n\n", limpio.replace("\r\n", "\n"))
    return limpio.strip()


def texto(valor, campo: str, max_len: int, obligatorio: bool = True, multilinea: bool = False,
          markdown: bool = False) -> str:
    """
    Texto libre seguro para publicar en Discord: sin caracteres de control, con longitud
    máxima y con las menciones (@everyone, @here, <@id>, <@&rol>) neutralizadas.
    Con markdown=False también se escapa el formato (*, _, ~, `, |, >).
    """
    if valor is None:
        valor = ""
    if not isinstance(valor, (str, int, float)):
        raise EntradaInvalida(f"{campo} no válido")
    limpio = _sin_controles(str(valor), multilinea)
    if not limpio:
        if obligatorio:
            raise EntradaInvalida(f"Falta {campo}")
        return ""
    if len(limpio) > max_len:
        raise EntradaInvalida(f"{campo} demasiado largo (máximo {max_len} caracteres)")
    if not markdown:
        limpio = discord.utils.escape_markdown(limpio)
    return discord.utils.escape_mentions(limpio)


def email(valor) -> str:
    limpio = _sin_controles(str(valor or ""), multilinea=False)
    if not limpio or len(limpio) > MAX_EMAIL or not PATRON_EMAIL.match(limpio):
        raise EntradaInvalida("Email no válido")
    return discord.utils.escape_mentions(discord.utils.escape_markdown(limpio))


# -------------------------------------------------------------
# IDENTIFICADORES
# -------------------------------------------------------------
def codigo_torneo(valor, obligatorio: bool = True) -> str:
    limpio = str(valor or "").strip()
    if not limpio and not obligatorio:
        return ""
    if not PATRON_CODIGO_TORNEO.match(limpio):
        raise EntradaInvalida("Código de torneo no válido")
    return limpio


def discord_id(valor, campo: str = "ID de jugador") -> int:
    limpio = str(valor if valor is not None else "").strip()
    if not PATRON_DISCORD_ID.match(limpio):
        raise EntradaInvalida(f"{campo} no válido")
    return int(limpio)


def formato(valor, por_defecto: str = "Premodern") -> str:
    limpio = str(valor or "").strip().lower()
    return FORMATOS_VALIDOS.get(limpio, por_defecto)


def resultado(valor) -> str:
    limpio = str(valor or "").strip().replace(" ", "")
    if not PATRON_RESULTADO.match(limpio):
        raise EntradaInvalida("Resultado no válido (formato esperado: 2-1)")
    return limpio


# -------------------------------------------------------------
# FECHAS
# -------------------------------------------------------------
def _hoy() -> date:
    return datetime.now(TZ).date() if TZ else date.today()


def fecha(valor, campo: str = "fecha", futura: bool = True) -> str:
    """DD/MM/YYYY real. Con futura=True no admite fechas pasadas ni a más de un año."""
    limpio = str(valor or "").strip()
    try:
        f = datetime.strptime(limpio, "%d/%m/%Y").date()
    except ValueError:
        raise EntradaInvalida(f"{campo.capitalize()} no válida (formato DD/MM/AAAA)")
    if futura:
        hoy = _hoy()
        if f < hoy:
            raise EntradaInvalida(f"La {campo} no puede ser anterior a hoy")
        if f > hoy + timedelta(days=DIAS_MAX_AGENDA):
            raise EntradaInvalida(f"La {campo} no puede ser a más de un año vista")
    return f.strftime("%d/%m/%Y")


def hora(valor, campo: str = "hora") -> str:
    limpio = str(valor or "").strip()
    try:
        h = datetime.strptime(limpio, "%H:%M")
    except ValueError:
        raise EntradaInvalida(f"{campo.capitalize()} no válida (formato HH:MM)")
    return h.strftime("%H:%M")


# -------------------------------------------------------------
# LÍMITE DE PETICIONES (por IP, en memoria)
# -------------------------------------------------------------
# (método, ruta) -> (máximo, ventana en segundos). Lo que no aparece usa LIMITE_GENERAL.
LIMITE_GENERAL = (120, 60)
LIMITE_ESCRITURA = (20, 60)          # cualquier POST no listado abajo
LIMITES_RUTA = {
    ("POST", "/api/solicitar-acceso"): (3, 3600),     # publica en el canal de admins sin login
    ("POST", "/auth/solicitar-codigo"): (5, 600),     # manda DMs sin login
    ("POST", "/auth/verificar-codigo"): (15, 600),
    ("POST", "/api/agendar-partida"): (10, 600),
}

_peticiones = defaultdict(deque)     # (ip, clave_limite) -> timestamps
_ultima_purga = 0.0


def ip_cliente(request) -> str:
    """IP real detrás del proxy de Railway: el último salto de X-Forwarded-For (el que añade el proxy)."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.remote or "desconocida"


def _limite_para(request):
    clave = (request.method, request.path)
    if clave in LIMITES_RUTA:
        return clave, LIMITES_RUTA[clave]
    if request.method == "POST":
        return ("POST", "*"), LIMITE_ESCRITURA
    return ("*", "*"), LIMITE_GENERAL


def _purgar(ahora: float):
    global _ultima_purga
    if ahora - _ultima_purga < 300:
        return
    _ultima_purga = ahora
    ventana_max = max(v for _, v in [LIMITE_GENERAL, LIMITE_ESCRITURA, *LIMITES_RUTA.values()])
    for k in [k for k, q in _peticiones.items() if not q or q[-1] < ahora - ventana_max]:
        del _peticiones[k]


def comprobar_limite(request):
    """Lanza EntradaInvalida(429) si la IP supera el límite de su ruta (y siempre cuenta el general)."""
    ahora = time.time()
    _purgar(ahora)
    ip = ip_cliente(request)
    limites = [(("*", "*"), LIMITE_GENERAL)]
    clave, limite = _limite_para(request)
    if clave != ("*", "*"):
        limites.append((clave, limite))

    for clave, (maximo, ventana) in limites:
        q = _peticiones[(ip, clave)]
        while q and q[0] < ahora - ventana:
            q.popleft()
        if len(q) >= maximo:
            espera = int(q[0] + ventana - ahora) + 1
            raise EntradaInvalida(f"Demasiadas peticiones. Inténtalo de nuevo en {espera} s.", status=429)

    for clave, _ in limites:
        _peticiones[(ip, clave)].append(ahora)


def respuesta_error(e: EntradaInvalida):
    return web.json_response({"error": e.mensaje}, status=e.status)
