"""
API web del club (aiohttp), usada por theklubmtg.es:
- comun: instancia del bot, servidor y respuestas de error.
- auth: sesiones JWT, decorador @requiere_sesion, login con código por DM y solicitud de admisión.
- torneos: caché de Challonge, listado, estado, inscripción, rondas y clasificación.
- decks: decks del usuario, subir y editar, y deck del rival.
- partidas: agenda, emparejamientos pendientes, reportar resultados y enfrentamientos.
- contenido: podcast y artículos (RSS).
- routes: middleware, rutas y arranque del servidor.
"""
from utils.api.comun import set_bot_instance
from utils.api.routes import iniciar_servidor_web
from utils.api.torneos import regenerar_cache, refrescar_cache_al_arrancar

__all__ = ["set_bot_instance", "iniciar_servidor_web", "regenerar_cache", "refrescar_cache_al_arrancar"]
