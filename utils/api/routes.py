"""Servidor web: middleware (CORS, límites y errores en JSON), log de accesos y registro de rutas."""
import os

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

from utils import validacion_web as v
from utils.api import auth, contenido, decks, partidas, torneos
from utils.api import comun

# Orígenes que pueden llamar a la API desde el navegador. Se puede sobrescribir en Railway con
# CORS_ORIGENES="https://theklubmtg.es,https://www.theklubmtg.es" (separados por comas).
# "null" es el origen que envía el navegador al abrir la web como archivo local (file://).
CORS_ORIGENES_PERMITIDOS = {
    o.strip() for o in os.environ.get(
        "CORS_ORIGENES", "https://theklubmtg.es,https://www.theklubmtg.es,null"
    ).split(",") if o.strip()
}


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        # Preflight del navegador (p. ej. POST JSON o GET con cabecera Authorization): se responde en cualquier ruta
        response = web.Response()
    else:
        try:
            v.comprobar_limite(request)
            response = await handler(request)
        except v.EntradaInvalida as e:
            response = v.respuesta_error(e)
        except web.HTTPRequestEntityTooLarge:
            response = web.json_response({"error": "Petición demasiado grande"}, status=413)
        except web.HTTPException as e:
            # 404/405 del router y demás errores HTTP: se mantiene su código, en JSON
            mensajes = {404: "No encontrado", 405: "Método no permitido"}
            response = web.json_response({"error": mensajes.get(e.status, e.reason)}, status=e.status)
        except Exception:
            response = comun.error_interno(f"{request.method} {request.path}")
    origen = request.headers.get("Origin")
    if origen in CORS_ORIGENES_PERMITIDOS:
        response.headers['Access-Control-Allow-Origin'] = origen
        response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Max-Age'] = '600'
    response.headers['Vary'] = 'Origin'
    return response


class AccessLoggerSinQuery(AbstractAccessLogger):
    """Log de accesos sin la query string, para que el token (?session=) no acabe en los logs."""
    def log(self, request, response, time):
        self.logger.info(
            '%s "%s %s" %s %.3fs',
            request.remote, request.method, request.path, response.status, time
        )


RUTAS_GET = {
    # Públicas
    '/api/torneos': torneos.api_torneos,
    '/api/podcast': contenido.api_podcast,
    '/api/articulos': contenido.api_articulos,
    '/api/arquetipos': decks.api_arquetipos,
    '/auth/verificar-sesion': auth.auth_verificar_sesion,
    # Con sesión
    '/api/mis-torneos': torneos.api_mis_torneos,
    '/api/torneos-disponibles': torneos.api_torneos_disponibles,
    '/api/estado-torneos': torneos.api_estado_torneos,
    '/api/torneo-enfrentamientos': torneos.api_torneo_enfrentamientos,
    '/api/clasificacion-torneo': torneos.api_clasificacion_torneo,
    '/api/mis-decks': decks.api_mis_decks,
    '/api/deck-rival': decks.api_deck_rival,
    '/api/todas-partidas': partidas.api_todas_partidas,
    '/api/mis-torneos-pendientes': partidas.api_mis_torneos_pendientes,
    '/api/mis-enfrentamientos': partidas.api_mis_enfrentamientos,
}

RUTAS_POST = {
    # Públicas
    '/api/solicitar-acceso': auth.api_solicitar_acceso,
    '/auth/solicitar-codigo': auth.auth_solicitar_codigo,
    '/auth/verificar-codigo': auth.auth_verificar_codigo,
    # Con sesión
    '/api/inscribirse': torneos.api_inscribirse,
    '/api/desinscribirse': torneos.api_desinscribirse,
    '/api/subir-deck': decks.api_subir_deck,
    '/api/editar-deck': decks.api_editar_deck,
    '/api/reportar-resultado': partidas.api_reportar_resultado,
    '/api/agendar-partida': partidas.api_agendar_partida,
    '/api/modificar-partida': partidas.api_modificar_partida,
    '/api/eliminar-partida': partidas.api_eliminar_partida,
}


def crear_app():
    # Los OPTIONS (preflight) los responde el middleware en cualquier ruta: no hace falta registrarlos
    app = web.Application(middlewares=[cors_middleware], client_max_size=v.MAX_CUERPO_BYTES)
    for ruta, handler in RUTAS_GET.items():
        app.router.add_get(ruta, handler)
    for ruta, handler in RUTAS_POST.items():
        app.router.add_post(ruta, handler)
    return app


async def iniciar_servidor_web():
    runner = web.AppRunner(crear_app(), access_log_class=AccessLoggerSinQuery)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
