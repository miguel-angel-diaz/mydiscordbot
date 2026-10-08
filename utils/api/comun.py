"""Lo que comparten los módulos de la API: la instancia del bot, el servidor y las respuestas de error."""
import logging

from aiohttp import web

import config
from utils import servicios
from utils.torneos_estado import leer_estado

log = logging.getLogger(__name__)

_bot_instance = None


def set_bot_instance(bot):
    global _bot_instance
    _bot_instance = bot


def obtener_bot():
    return _bot_instance


def servidor():
    """Servidor de Discord del club, o None si el bot aún no está listo."""
    return _bot_instance.get_guild(config.GUILD_ID_ADMISION) if _bot_instance else None


def no_disponible():
    return web.json_response({"error": "Servicio no disponible"}, status=503)


def error_interno(contexto: str, status: int = 500):
    """Registra el traceback completo en los logs y responde un mensaje genérico (sin detalles internos)."""
    log.exception(f"❌ Error en API ({contexto})")   # se llama desde un except: con traceback
    mensaje = "Servicio no disponible" if status == 503 else "Error interno"
    return web.json_response({"error": mensaje}, status=status)


# Motivos de fallo de utils/servicios.py con código propio; el resto es un 400
_HTTP_POR_MOTIVO = {servicios.SIN_PERMISO: 403, servicios.YA_EXISTE: 409, servicios.SIN_CANAL: 500}


def respuesta_servicio(resultado: servicios.Resultado):
    if resultado.ok:
        return web.json_response({"ok": True, "mensaje": resultado.mensaje})
    return web.json_response({"error": resultado.mensaje}, status=_HTTP_POR_MOTIVO.get(resultado.motivo, 400))


async def torneo_del_estado(codigo: str) -> dict | None:
    estado = await leer_estado(_bot_instance)
    return next((t for t in estado.get("torneos", []) if t.get("codigo") == codigo), None)
