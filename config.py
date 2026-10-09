######## config.py #######
"""
Configuración del bot: credenciales (variables de entorno o config_token.py en local) y constantes.
Los datos (ayuda de los comandos, arquetipos y blacklist) están en data/*.json.

Obligatorias: DISCORD_TOKEN y GUILD_ID_ADMISION. Opcionales: CHALLONGE_USERNAME / CHALLONGE_API_KEY (solo la
consulta del histórico): si faltan, el bot arranca igual y esa función avisa de que no está configurada.
"""
import json
import logging
import os
import secrets

from utils import canales

log = logging.getLogger(__name__)
DIR_DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def get_jwt_secret():
    # 1. Intentar desde variable de entorno (prioridad máxima)
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret

    # 2. Intentar leer de archivo local
    try:
        with open(".jwt_secret", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        pass

    # 3. Generar nueva y guardar en archivo
    secret = secrets.token_urlsafe(32)
    with open(".jwt_secret", "w") as f:
        f.write(secret)
    log.warning(
        "⚠️ JWT_SECRET no definida: se ha generado una nueva y se ha guardado en .jwt_secret (no se muestra en el log).\n"
        "📌 Define la variable de entorno JWT_SECRET para mantener las sesiones entre despliegues.")
    return secret


def _valor(nombre: str):
    """Variable de entorno o, si no está, la de config_token.py (cada una por separado: antes, si a
    config_token.py le faltaba UNA clave, se ignoraban todas)."""
    valor = os.environ.get(nombre)
    if valor:
        return valor
    try:
        import config_token
    except ImportError:
        return None
    return getattr(config_token, nombre, None) or None


CHALLONGE_USERNAME = _valor("CHALLONGE_USERNAME")
CHALLONGE_API_KEY = _valor("CHALLONGE_API_KEY")
DISCORD_TOKEN = _valor("DISCORD_TOKEN")
GUILD_ID_ADMISION = _valor("GUILD_ID_ADMISION")
CACHE_PATH = os.environ.get("CACHE_PATH") or "cache/torneos.json"
JWT_SECRET = get_jwt_secret()

# 🔹 Obligatorias
if not DISCORD_TOKEN:
    raise ValueError(
        "❌ No se encontró el token del bot. "
        "Define DISCORD_TOKEN en las variables de entorno o en config_token.py."
    )
if not GUILD_ID_ADMISION:
    raise ValueError(
        "❌ No se encontró GUILD_ID_ADMISION. "
        "Define esta variable de entorno en Railway con el ID de tu servidor de Discord."
    )
GUILD_ID_ADMISION = int(GUILD_ID_ADMISION)   # debe ser un entero, no un string

# 🔹 Opcionales: se avisa, pero el bot arranca
if not CHALLONGE_USERNAME or not CHALLONGE_API_KEY:
    log.warning("⚠️ Sin credenciales de Challonge: la consulta de torneos antiguos no estará disponible.")

SESSION_EXPIRATION_SECONDS = 24 * 3600        # sesión de la web: un token robado deja de valer en un día
ROLES_TODOS = {*canales.ROLES_JUGADORES, canales.ROL_ADMIN}
CANALES_EXCLUIDOS = {canales.COMANDOS, canales.RANKING}
ROLES_SOCIOS = {canales.ROL_SOCIO, canales.ROL_SOCIO_2C, canales.ROL_ADMIN}


# ============================================================
# DATOS (data/*.json)
# ============================================================

def _cargar_json(nombre: str):
    with open(os.path.join(DIR_DATOS, nombre), encoding="utf-8") as f:
        return json.load(f)


_ARQUETIPOS = _cargar_json("arquetipos.json")
ARQUETIPOS_PREMODERN = _ARQUETIPOS["Premodern"]
ARQUETIPOS_PAUPER = _ARQUETIPOS["Pauper"]
BLACKLIST_USERS = _cargar_json("blacklist.json")
# Descripción y tutorial de cada comando; los alias y los roles salen del propio comando (utils/ayuda.py)
AYUDA_COMANDOS = _cargar_json("ayuda_comandos.json")
