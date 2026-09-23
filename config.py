######## config.py #######

import os

import secrets

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
    print(f"⚠️ JWT_SECRET generada y guardada en .jwt_secret: {secret}")
    print("📌 Cópiala y añádela como variable de entorno para mantenerla entre despliegues.")
    return secret

# Leer variables de entorno
CHALLONGE_USERNAME = os.environ.get("CHALLONGE_USERNAME")
CHALLONGE_API_KEY = os.environ.get("CHALLONGE_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
OPENROUTER_API_KEY =  os.environ.get("OPENROUTER_API_KEY")
GUILD_ID_ADMISION = os.environ.get("GUILD_ID_ADMISION")
CACHE_PATH = os.environ.get("CACHE_PATH")
JWT_SECRET = JWT_SECRET = get_jwt_secret()

if not CHALLONGE_USERNAME or not CHALLONGE_API_KEY or not DISCORD_TOKEN or not OPENROUTER_API_KEY or not JWT_SECRET:
    try:
        from config_token import (
            CHALLONGE_USERNAME as LOCAL_USER,
            CHALLONGE_API_KEY as LOCAL_KEY,
            DISCORD_TOKEN as LOCAL_TOKEN,
            OPENROUTER_API_KEY as LOCAL_OPENROUTER,
            GUILD_ID_ADMISION as LOCAL_GUILD_ID,
            JWT_SECRET as LOCAL_JWT_SECRET  # <--- Añadir esta línea
        )
        CHALLONGE_USERNAME = CHALLONGE_USERNAME or LOCAL_USER
        CHALLONGE_API_KEY = CHALLONGE_API_KEY or LOCAL_KEY
        DISCORD_TOKEN = DISCORD_TOKEN or LOCAL_TOKEN
        OPENROUTER_API_KEY = OPENROUTER_API_KEY or LOCAL_OPENROUTER
        GUILD_ID_ADMISION = GUILD_ID_ADMISION or LOCAL_GUILD_ID
        JWT_SECRET = JWT_SECRET or LOCAL_JWT_SECRET  # <--- Añadir esta línea
    except ImportError:
        pass

# 🔹 Validación final
if not CHALLONGE_USERNAME or not CHALLONGE_API_KEY:
    raise ValueError(
        "❌ No se encontraron las credenciales de Challonge. "
        "Define CHALLONGE_USERNAME y CHALLONGE_API_KEY en las variables de entorno o en config_token.py."
    )

if not DISCORD_TOKEN:
    raise ValueError(
        "❌ No se encontró el token del bot. "
        "Define DISCORD_TOKEN en las variables de entorno o en config_token.py."
    )
if not OPENROUTER_API_KEY:
    raise ValueError(
        "❌ No se encontró la clave de OpenRouter. "
        "Define OPENROUTER_API_KEY en las variables de entorno."
    )
# 🔹 GUILD_ID_ADMISION debe ser un entero, no un string
if GUILD_ID_ADMISION:
    GUILD_ID_ADMISION = int(GUILD_ID_ADMISION)
else:
    raise ValueError(
        "❌ No se encontró GUILD_ID_ADMISION. "
        "Define esta variable de entorno en Railway con el ID de tu servidor de Discord."
    )

# 🔹 CACHE_PATH con valor por defecto razonable si no se define
if not CACHE_PATH:
    CACHE_PATH = "cache/torneos.json"

if not JWT_SECRET:
    raise ValueError(
        "❌ No se encontró JWT_SECRET. "
        "Define JWT_SECRET en las variables de entorno o en config_token.py."
    )
SESSION_EXPIRATION_SECONDS = 7 * 24 * 3600  
CHALLONGE_API_URL = "https://api.challonge.com/v1/tournaments.json"
ROLES_TODOS = {"miembro", "socio", "second-chance-socio", "second-chance-miembro", "admin"}
ROLES_BORRADOS = {"miembro", "socio", "second-chance-socio", "second-chance-miembro"}
CANALES_EXCLUIDOS = {"preguntale-a-el-barbas", "🍺-el‐ranking‐de‐la‐barra"}
ROLES_BIENVENIDA = {"Accept Welcome", "Accept Rules"}
ROLES_SOCIOS = {"socio", "second-chance-socio", "admin"}
COMANDOS_INFO = [
    # ============================================================
    # ADMIN - MODERACIÓN
    # ============================================================
    {
        "comando": "strike",
        "aliases": [],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Aplica un strike a un miembro del servidor",
        "tutorial": [
            "Escribe `!strike` en `#preguntale-a-el-barbas` (o con mención: `!strike @usuario`).",
            "Si no pasas mención, el bot te preguntará por DM a quién quieres aplicar el strike.",
            "El bot asignará el rol `Strike` al usuario y le enviará un mensaje privado explicándole la situación."
        ]
    },
    {
        "comando": "out",
        "aliases": [],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Aplica el rol 'Out' a un miembro del servidor",
        "tutorial": [
            "Escribe `!out` (o `!out @usuario`) en `#preguntale-a-el-barbas`.",
            "El bot asignará el rol `Out` y le enviará un mensaje privado de expulsión.",
            "Se registrará el evento en el canal `#blacklist`."
        ]
    },
    {
        "comando": "eliminar-mensajes",
        "aliases": ["eliminar mensajes", "eliminar_mensajes"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Elimina una cantidad específica de mensajes en un canal",
        "tutorial": [
            "Escribe `!eliminar-mensajes` en `#preguntale-a-el-barbas`.",
            "El bot te preguntará por DM: canal, cantidad (1-1000), orden (recientes/antiguos) y si incluir fijados.",
            "Los mensajes se eliminan y se registra el evento en `#mensajes-borrados`."
        ]
    },
    {
        "comando": "cerrar-peticion",
        "aliases": ["cerrar peticion", "cerrar_peticion"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Cierra una petición y envía la respuesta al usuario",
        "tutorial": [
            "Escribe `!cerrar-peticion` en `#preguntale-a-el-barbas`.",
            "El bot te pedirá por DM el código de la petición y la respuesta.",
            "Se envía la respuesta por DM al autor, se borra del canal `#peticiones-de-usuarios` y se publica el resumen en `#resolucion-de-peticiones`."
        ]
    },
    {
        "comando": "nuevo-comunicado",
        "aliases": ["nuevo_comunicado"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Envía un comunicado al canal 📰-tablón-anuncios",
        "tutorial": [
            "Escribe `!nuevo-comunicado <mensaje>` o solo `!nuevo-comunicado` (el bot te lo pedirá por DM).",
            "El mensaje se publica como embed en `#📰-tablon-anuncios` con `@everyone`."
        ]
    },

    # ============================================================
    # ADMIN - SORTEOS
    # ============================================================
    {
        "comando": "nuevo-sorteo",
        "aliases": ["nuevo sorteo", "nuevo_sorteo"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_guild"],
        "descripcion": "Crea un nuevo sorteo con sus datos",
        "tutorial": [
            "Escribe `!nuevo-sorteo` en `#preguntale-a-el-barbas`.",
            "El bot te pedirá por DM: código, fecha límite y regalo del sorteo.",
            "El sorteo se publica en `#📰-tablon-anuncios` y `#sorteos-activos`."
        ]
    },
    {
        "comando": "realizar-sorteo",
        "aliases": ["realizar sorteo", "realizar_sorteo"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_guild"],
        "descripcion": "Ejecuta un sorteo ya creado por su código",
        "tutorial": [
            "Escribe `!realizar-sorteo <código>` en `#preguntale-a-el-barbas`.",
            "El bot elegirá un ganador aleatorio entre los inscritos en `#inscritos-sorteos`.",
            "Se notifica por DM al ganador y se publica el resultado en `#tablon-anuncios`."
        ]
    },

    # ============================================================
    # ADMIN - TORNEOS SWISS
    # ============================================================
    {
        "comando": "nuevo-swiss",
        "aliases": ["nuevo torneo", "nuevo_torneo", "nuevo-torneo"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Crea un nuevo torneo suizo (Swiss)",
        "tutorial": [
            "Escribe `!nuevo-swiss` en `#preguntale-a-el-barbas`.",
            "El bot te preguntará por DM: nombre, formato (Premodern/Pauper), jugadores máximos, nivel (`todos`/`socios`) y fecha de inicio (DD/MM/YYYY).",
            "El torneo se publica en `#torneos-activos` y `#📰-cartelera-torneos`."
        ]
    },
    {
        "comando": "iniciar-swiss",
        "aliases": ["iniciar torneo", "iniciar_torneo", "iniciar-torneo"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Inicia un torneo suizo tras verificar los decks subidos",
        "tutorial": [
            "Escribe `!iniciar-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo entre los activos.",
            "El bot te muestra quién subió deck y quién no. Puedes eliminarlos o continuar.",
            "Se genera la Ronda 1 y se publican los emparejamientos en `#🍸-citas-a-ciegas`."
        ]
    },
    {
        "comando": "siguiente-ronda-swiss",
        "aliases": [],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Genera la siguiente ronda del torneo suizo",
        "tutorial": [
            "Escribe `!siguiente-ronda-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo. Se calculan los emparejamientos según la clasificación actual.",
            "Se publica la nueva ronda y se actualiza la clasificación."
        ]
    },
    {
        "comando": "reiniciar-swiss",
        "aliases": ["reiniciar torneo", "reiniciar_torneo", "reiniciar-torneo"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Reinicia un torneo suizo (borra rondas y clasificación)",
        "tutorial": [
            "Escribe `!reiniciar-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo y confirma.",
            "Se borran las rondas, la clasificación y los mensajes de citas a ciegas. El torneo queda en estado `abierto`."
        ]
    },
    {
        "comando": "eliminar-swiss",
        "aliases": ["eliminar torneo", "eliminar_torneo", "eliminar-torneo"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Elimina un torneo suizo permanentemente",
        "tutorial": [
            "Escribe `!eliminar-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo y confirma.",
            "Se borran todos los datos del torneo (estado, rondas, clasificación)."
        ]
    },
    {
        "comando": "modificar-resultado-swiss",
        "aliases": ["modificar resultado swiss", "modificar_resultado_swiss", "modificar-resultado", "modificar resultado", "modificar_resultado"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Modifica un resultado ya reportado en un torneo suizo",
        "tutorial": [
            "Escribe `!modificar-resultado-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo y el partido a modificar (se muestra una lista de los ya reportados).",
            "Introduce el nuevo resultado en formato `X-Y` y confirma.",
            "La clasificación se recalcula automáticamente."
        ]
    },

    # ============================================================
    # ADMIN - CHALLONGE (legacy)
    # ============================================================
    {
        "comando": "actualizar-clasificacion",
        "aliases": ["actualizar clasificacion", "actualizar_clasificacion"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Actualiza la clasificación de un torneo y la publica",
        "tutorial": [
            "Escribe `!actualizar-clasificacion <código_torneo>` en `#preguntale-a-el-barbas`.",
            "El bot calcula OMW%, Buchholz y diferencia de games, y publica la tabla en `#🍺-el-ranking-de-la-barra`."
        ]
    },
    {
        "comando": "forzar-ronda",
        "aliases": ["forzar ronda", "forzar_ronda"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Termina la ronda actual con empates y comienza la siguiente",
        "tutorial": [
            "Escribe `!forzar-ronda <código_torneo>` en `#preguntale-a-el-barbas`.",
            "Todas las partidas pendientes se marcan como empate `0-0`.",
            "Se genera la siguiente ronda automáticamente."
        ]
    },
    {
        "comando": "reportar-torneo",
        "aliases": ["reportar torneo", "reportar_torneo"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Genera un informe completo del torneo con análisis IA",
        "tutorial": [
            "Escribe `!reportar-torneo` en `#preguntale-a-el-barbas`.",
            "Elige el torneo (debe estar completado).",
            "El bot analiza las cartas más jugadas, los mejores decks y genera un informe con IA que se publica en `#🧠📈analisis-torneos`."
        ]
    },
    {
        "comando": "actualizar-web",
        "aliases": ["actualizar web", "actualizar_web"],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages"],
        "descripcion": "Actualiza la caché de torneos para la web",
        "tutorial": [
            "Escribe `!actualizar-web` en `#preguntale-a-el-barbas`.",
            "El bot regenera `cache/torneos.json` con la clasificación de los torneos finalizados.",
            "La web mostrará los datos actualizados."
        ]
    },
    {
        "comando": "sincronizar-estado",
        "aliases": [],
        "roles_permitidos": ["admin"],
        "permisos_discord": ["administrator"],
        "descripcion": "Reconstruye el estado interno de los torneos desde #torneos-activos",
        "tutorial": [
            "Escribe `!sincronizar-estado` en cualquier canal (solo admins).",
            "El bot borra el estado interno y lo reconstruye a partir de los torneos visibles en `#torneos-activos`.",
            "⚠️ Es una operación destructiva: se pierden inscritos, rondas y clasificación."
        ]
    },

    # ============================================================
    # JUGADOR - INSCRIPCIONES
    # ============================================================
    {
        "comando": "inscribir-swiss",
        "aliases": ["inscribir swiss", "inscribir_swiss", "inscribirse", "inscribir"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Te inscribe en un torneo suizo",
        "tutorial": [
            "Escribe `!inscribir-swiss` en `#preguntale-a-el-barbas`.",
            "El bot te muestra los torneos abiertos. Elige el número.",
            "Se te inscribe y el bot te pregunta por DM si quieres subir tu deck ahora."
        ]
    },
    {
        "comando": "desinscribir-swiss",
        "aliases": ["desinscribir swiss", "desinscribir_swiss", "desinscribirse", "desinscribir"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Te desinscribe de un torneo suizo",
        "tutorial": [
            "Escribe `!desinscribir-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo de la lista de tus inscripciones.",
            "Se te desinscribe y se elimina tu deck si lo habías subido."
        ]
    },
    {
        "comando": "ver-inscritos",
        "aliases": ["ver inscritos", "ver_inscritos"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra los inscritos en un torneo (con estado de deck para admin)",
        "tutorial": [
            "Escribe `!ver-inscritos` en `#preguntale-a-el-barbas`.",
            "Elige el torneo.",
            "Si eres admin, verás la lista completa con ✅/❌ según si cada uno ha subido deck.",
            "Si eres jugador, verás solo tu estado (inscrito y si has subido deck)."
        ]
    },

    # ============================================================
    # JUGADOR - DECKS
    # ============================================================
    {
        "comando": "subir-deck",
        "aliases": ["subir deck", "subir_deck"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Sube tu decklist para un torneo",
        "tutorial": [
            "Escribe `!subir-deck` en `#preguntale-a-el-barbas`.",
            "Elige el torneo (debes estar inscrito y no tener deck subido ya).",
            "El bot te pedirá por DM: nombre, formato, arquetipo, decklist (mín. 60) y sideboard (máx. 15 o N/A).",
            "El deck se publica en `#submitted-decks`."
        ]
    },
    {
        "comando": "editar-deck",
        "aliases": ["editar deck", "editar_deck"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Edita tu decklist para un torneo",
        "tutorial": [
            "Escribe `!editar-deck` en `#preguntale-a-el-barbas`.",
            "Elige el torneo. Si ya subiste deck, podrás modificar sus campos.",
            "Si el torneo ya comenzó, solo tienes **1 edición disponible** (post-inicio).",
            "Si el torneo no ha comenzado, puedes editar todas las veces que quieras."
        ]
    },

    # ============================================================
    # JUGADOR - RESULTADOS
    # ============================================================
    {
        "comando": "reportar-swiss",
        "aliases": ["reportar resultado", "reportar_resultado", "reportar-resultado"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Reporta el resultado de un partido en un torneo suizo",
        "tutorial": [
            "Escribe `!reportar-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo, elige los jugadores y el resultado (X-Y).",
            "Solo pueden reportar los jugadores implicados o un admin.",
            "El bot actualiza la clasificación automáticamente."
        ]
    },
    {
        "comando": "clasificacion-swiss",
        "aliases": [],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra la clasificación actual del torneo suizo",
        "tutorial": [
            "Escribe `!clasificacion-swiss` en `#preguntale-a-el-barbas`.",
            "Elige el torneo.",
            "Se te muestra la clasificación por DM."
        ]
    },
    {
        "comando": "partidos-pendientes",
        "aliases": ["partidos pendientes", "partidos_pendientes"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra los partidos pendientes de la ronda actual",
        "tutorial": [
            "Escribe `!partidos-pendientes` en `#preguntale-a-el-barbas`.",
            "Elige el torneo.",
            "El bot lista los partidos sin resultado de la ronda actual."
        ]
    },

    # ============================================================
    # JUGADOR - AGENDA
    # ============================================================
    {
        "comando": "agendar-partida",
        "aliases": ["agendar partida", "agendar_partida"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Agenda una partida entre dos jugadores",
        "tutorial": [
            "Escribe `!agendar-partida` en `#preguntale-a-el-barbas`.",
            "El bot te pedirá por DM: fecha (DD/MM/YYYY), hora (HH:MM) y los dos jugadores.",
            "La partida se publica en `#partidos-agendados` y se notifica por DM a los implicados."
        ]
    },
    {
        "comando": "modificar-agenda",
        "aliases": ["modificar agenda", "modificar_agenda"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Modifica o elimina una partida agendada",
        "tutorial": [
            "Escribe `!modificar-agenda` en `#preguntale-a-el-barbas`.",
            "El bot te muestra tus partidas agendadas. Elige una.",
            "Podrás modificar fecha, hora, jugadores, o eliminarla."
        ]
    },
    {
        "comando": "eventos-hoy",
        "aliases": ["eventos hoy", "eventos_hoy"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra los eventos programados para hoy",
        "tutorial": [
            "Escribe `!eventos-hoy` en `#preguntale-a-el-barbas`.",
            "El bot te envía por DM la lista de partidas agendadas para hoy."
        ]
    },

    # ============================================================
    # JUGADOR - BATTLE ROYALE
    # ============================================================
    {
        "comando": "iniciar-battle",
        "aliases": ["iniciar battle", "iniciar_battle"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Inicia un enfrentamiento de tipo Battle Royale",
        "tutorial": [
            "Escribe `!iniciar-battle` en `#preguntale-a-el-barbas`.",
            "Elige el torneo Battle y los dos jugadores.",
            "El bot comprueba que no hayan jugado ya 2 veces y registra la batalla en `#batallas-iniciadas`."
        ]
    },
    {
        "comando": "reportar-resultado-battle",
        "aliases": ["reportar resultado battle", "reportar_resultado_battle"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Reporta el resultado de un enfrentamiento Battle Royale",
        "tutorial": [
            "Escribe `!reportar-resultado-battle` en `#preguntale-a-el-barbas`.",
            "Elige el torneo, los jugadores y el resultado (X-Y).",
            "El bot actualiza la clasificación del Battle."
        ]
    },

    # ============================================================
    # JUGADOR - ESTADÍSTICAS
    # ============================================================
    {
        "comando": "cartas-mas-jugadas",
        "aliases": ["cartas mas jugadas", "cartas_mas_jugadas"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra las cartas más jugadas en un torneo o en todos",
        "tutorial": [
            "Escribe `!cartas-mas-jugadas` en `#preguntale-a-el-barbas`.",
            "Elige un torneo completado o `todos`.",
            "El bot genera un gráfico tipo donut con las cartas más jugadas (sin tierras básicas)."
        ]
    },
    {
        "comando": "best-decks",
        "aliases": ["best decks", "best_decks"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Analiza los mejores decks de un torneo (top 4 + último)",
        "tutorial": [
            "Escribe `!best-decks` en `#preguntale-a-el-barbas`.",
            "Elige el torneo.",
            "El bot muestra los decks del top 4 y del último clasificado."
        ]
    },
    {
        "comando": "stats",
        "aliases": [],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra tus estadísticas globales en los torneos",
        "tutorial": [
            "Escribe `!stats` en `#preguntale-a-el-barbas`.",
            "El bot genera gráficos (winrate, arquetipos, oponentes) y un análisis personalizado."
        ]
    },

    # ============================================================
    # JUGADOR - PETICIONES
    # ============================================================
    {
        "comando": "nueva-peticion",
        "aliases": ["nueva peticion", "nueva_peticion"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Crea una nueva petición o sugerencia al equipo",
        "tutorial": [
            "Escribe `!nueva-peticion <descripción>` en `#preguntale-a-el-barbas`.",
            "Si no incluyes descripción, el bot te la pedirá por DM.",
            "Se publica en `#peticiones-de-usuarios` con un código único."
        ]
    },

    # ============================================================
    # GENERAL
    # ============================================================
    {
        "comando": "mis-comandos",
        "aliases": ["mis comandos", "mis_comandos", "comandos", "comandios", "comandiox"],
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": [],
        "descripcion": "Abre el asistente para buscar un comando y ver su tutorial",
        "tutorial": [
            "Escribe `!mis-comandos` en `#preguntale-a-el-barbas`.",
            "El bot te abre un asistente por DM: te muestra la lista de comandos disponibles.",
            "Responde con el número o nombre del comando.",
            "El bot te muestra su descripción y te pregunta si quieres un tutorial paso a paso."
        ]
    },
]

BLACKLIST_USERS = [
    690865294117306398,
    747176417745305672,
    310844957026025472,
    683015920150380595,
    551129539451813904,
    740682453840035840,
    1210156421598158871,
    375285399926472704,
    388809346210856972,
    375782464871858177,
    1342595938644131920,
    771791460542185533,
    960605627770630214,
    303098896744185858,
    336174154984325120,
    691061830818332733
]
ARQUETIPOS_PREMODERN = [
  { "id": 1, "nombre": "4c Control" },
  { "id": 2, "nombre": "Aluren" },
  { "id": 3, "nombre": "Angry Ghoul" },
  { "id": 4, "nombre": "Angry Hermit" },
  { "id": 5, "nombre": "Astral Slide" },
  { "id": 6, "nombre": "Balancing Tings" },
  { "id": 7, "nombre": "Battle of Wits" },
  { "id": 8, "nombre": "Broccoli Soup" },
  { "id": 9, "nombre": "Burn" },
  { "id": 10, "nombre": "BW Control" },
  { "id": 11, "nombre": "Cephalid Breakfast" },
  { "id": 12, "nombre": "Clerics" },
  { "id": 13, "nombre": "Contamination" },
  { "id": 14, "nombre": "Dance Academy" },
  { "id": 15, "nombre": "Deadguy Ale" },
  { "id": 16, "nombre": "Devourer" },
  { "id": 17, "nombre": "Devourer Combo" },
  { "id": 18, "nombre": "Doomsday" },
  { "id": 19, "nombre": "Draco Blast" },
  { "id": 20, "nombre": "Drake Combo" },
  { "id": 21, "nombre": "Dream Halls" },
  { "id": 22, "nombre": "Dredgeless Dredge" },
  { "id": 23, "nombre": "El Delicioso 69" },
  { "id": 24, "nombre": "Elfos" },
  { "id": 25, "nombre": "Elves" },
  { "id": 26, "nombre": "Enchantress" },
  { "id": 27, "nombre": "False Cure" },
  { "id": 28, "nombre": "Fires" },
  { "id": 29, "nombre": "Fluctuator" },
  { "id": 30, "nombre": "Frenetic Encounter" },
  { "id": 31, "nombre": "Full English Breakfast" },
  { "id": 32, "nombre": "Gamekeeper" },
  { "id": 33, "nombre": "Goblins" },
  { "id": 34, "nombre": "Great Combo" },
  { "id": 35, "nombre": "Gro-A-Tog" },
  { "id": 36, "nombre": "Iggy Pop" },
  { "id": 37, "nombre": "Lands" },
  { "id": 38, "nombre": "Landstill" },
  { "id": 39, "nombre": "Life" },
  { "id": 40, "nombre": "Machine Head" },
  { "id": 41, "nombre": "Madness" },
  { "id": 42, "nombre": "Merfolks" },
  { "id": 43, "nombre": "Mono Black" },
  { "id": 44, "nombre": "Mono Black Control" },
  { "id": 45, "nombre": "Mono Blue" },
  { "id": 46, "nombre": "Mono Green" },
  { "id": 47, "nombre": "Montañas Y Algún Instat" },
  { "id": 48, "nombre": "MUD" },
  { "id": 49, "nombre": "Oath" },
  { "id": 50, "nombre": "Oath Ponza" },
  { "id": 51, "nombre": "Oath Spec" },
  { "id": 52, "nombre": "Pandeburst" },
  { "id": 53, "nombre": "Parallax Replenish" },
  { "id": 54, "nombre": "Parfait" },
  { "id": 55, "nombre": "Pattern Combo" },
  { "id": 56, "nombre": "Pebbles" },
  { "id": 57, "nombre": "Pink Prison" },
  { "id": 58, "nombre": "Pit Rack" },
  { "id": 59, "nombre": "Ponza" },
  { "id": 60, "nombre": "Pox" },
  { "id": 61, "nombre": "Psychatog" },
  { "id": 62, "nombre": "Pyrostatic Oath" },
  { "id": 63, "nombre": "Reanimator" },
  { "id": 64, "nombre": "Rebels" },
  { "id": 65, "nombre": "Red Control" },
  { "id": 66, "nombre": "Rogue" },
  { "id": 67, "nombre": "Slivers" },
  { "id": 68, "nombre": "Stasis" },
  { "id": 69, "nombre": "Stiflenought" },
  { "id": 70, "nombre": "Storm" },
  { "id": 71, "nombre": "Survival" },
  { "id": 72, "nombre": "Survival (Other)" },
  { "id": 73, "nombre": "Survival Infestation" },
  { "id": 74, "nombre": "Survival Recurring" },
  { "id": 75, "nombre": "Survival Tradewind" },
  { "id": 76, "nombre": "Survival Welder" },
  { "id": 77, "nombre": "Tax Rack Aggro" },
  { "id": 78, "nombre": "Terrageddon" },
  { "id": 79, "nombre": "The Rock" },
  { "id": 80, "nombre": "The Solution" },
  { "id": 81, "nombre": "Threshold" },
  { "id": 82, "nombre": "Tide Control" },
  { "id": 83, "nombre": "Tireless Tribe" },
  { "id": 84, "nombre": "Tribal" },
  { "id": 85, "nombre": "Trinity" },
  { "id": 86, "nombre": "Trix" },
  { "id": 87, "nombre": "Tron" },
  { "id": 88, "nombre": "Turbo Lands" },
  { "id": 89, "nombre": "Turtle Splash" },
  { "id": 90, "nombre": "UR Control" },
  { "id": 91, "nombre": "UW Control" },
  { "id": 92, "nombre": "UW Midrange" },
  { "id": 93, "nombre": "UWB Control" },
  { "id": 94, "nombre": "UWG Control" },
  { "id": 95, "nombre": "Wake Control" },
  { "id": 96, "nombre": "White Control" },
  { "id": 97, "nombre": "White Weenie" },
  { "id": 98, "nombre": "Ya Ni Se Porque Juego Sligh" },
  { "id": 99, "nombre": "Zombie Infestation" },
  { "id": 100, "nombre": "Zombies" },
  { "id": 101, "nombre": "Zoo" }
]
ARQUETIPOS_PAUPER = [
  { "id": 1, "nombre": "4 Color Ephemerate" },
  { "id": 2, "nombre": "Abzan Initiative" },
  { "id": 3, "nombre": "Abzan Lifegain" },
  { "id": 4, "nombre": "Altar Tron" },
  { "id": 5, "nombre": "Azorius Faeries" },
  { "id": 6, "nombre": "Azorius Gates" },
  { "id": 7, "nombre": "Azorius Tribe" },
  { "id": 8, "nombre": "Boros Bully" },
  { "id": 9, "nombre": "Boros Gates" },
  { "id": 10, "nombre": "Boros Heroic" },
  { "id": 11, "nombre": "Boros Metalcraft" },
  { "id": 12, "nombre": "Boros Synthesizer" },
  { "id": 13, "nombre": "Boros Tribe" },
  { "id": 14, "nombre": "Cascade Tron" },
  { "id": 15, "nombre": "Cycling Storm" },
  { "id": 16, "nombre": "Defender Combo" },
  { "id": 17, "nombre": "Dimir Abjure" },
  { "id": 18, "nombre": "Dimir Affinity" },
  { "id": 19, "nombre": "Dimir Control" },
  { "id": 20, "nombre": "Dimir Familiar" },
  { "id": 21, "nombre": "Dimir Spirits" },
  { "id": 22, "nombre": "Dimir Terror" },
  { "id": 23, "nombre": "Dredge" },
  { "id": 24, "nombre": "Eggs Tron" },
  { "id": 25, "nombre": "Elves" },
  { "id": 26, "nombre": "Esper Affinity" },
  { "id": 27, "nombre": "Esper Ephemerate" },
  { "id": 28, "nombre": "Esper Gates" },
  { "id": 29, "nombre": "Esper Metalcraft" },
  { "id": 30, "nombre": "Flicker Tron" },
  { "id": 31, "nombre": "Goblin Combo (MoggWarts)" },
  { "id": 32, "nombre": "Goblins" },
  { "id": 33, "nombre": "Golgari Auras" },
  { "id": 34, "nombre": "Golgari Gardens" },
  { "id": 35, "nombre": "Golgari Ponza" },
  { "id": 36, "nombre": "Golgari Sacrifice" },
  { "id": 37, "nombre": "Grixis Affinity" },
  { "id": 38, "nombre": "Grixis Control" },
  { "id": 39, "nombre": "Grixis Wildfire" },
  { "id": 40, "nombre": "Gruul Eldrazi" },
  { "id": 41, "nombre": "Gruul Landfall" },
  { "id": 42, "nombre": "Gruul Ponza" },
  { "id": 43, "nombre": "Gruul Ramp" },
  { "id": 44, "nombre": "GW Bogles" },
  { "id": 45, "nombre": "Infect" },
  { "id": 46, "nombre": "Izzet Affinity" },
  { "id": 47, "nombre": "Izzet Blitz" },
  { "id": 48, "nombre": "Izzet Faeries" },
  { "id": 49, "nombre": "Izzet Ponza" },
  { "id": 50, "nombre": "Izzet Skred" },
  { "id": 51, "nombre": "Izzet Terror" },
  { "id": 52, "nombre": "Jeskai Affinity" },
  { "id": 53, "nombre": "Jeskai Ephemerate" },
  { "id": 54, "nombre": "Jeskai Metalcraft" },
  { "id": 55, "nombre": "Jund Bowseeker" },
  { "id": 56, "nombre": "Jund Gardens" },
  { "id": 57, "nombre": "Jund Wildfire" },
  { "id": 58, "nombre": "Mardu Initiative" },
  { "id": 59, "nombre": "Mardu Metalcraft" },
  { "id": 60, "nombre": "Mono Black Affinity" },
  { "id": 61, "nombre": "Mono Black Burn" },
  { "id": 62, "nombre": "Mono Black Control" },
  { "id": 63, "nombre": "Mono Black Food" },
  { "id": 64, "nombre": "Mono Black Pactdoll" },
  { "id": 65, "nombre": "Mono Black Sacrifice" },
  { "id": 66, "nombre": "Mono Blue Faeries" },
  { "id": 67, "nombre": "Mono Blue Terror" },
  { "id": 68, "nombre": "Mono Green Counters" },
  { "id": 69, "nombre": "Mono Green Stompy" },
  { "id": 70, "nombre": "Mono Red Burn" },
  { "id": 71, "nombre": "Mono Red Dredge" },
  { "id": 72, "nombre": "Mono Red Equipments" },
  { "id": 73, "nombre": "Mono Red Kiln Fiend" },
  { "id": 74, "nombre": "Mono Red Madness" },
  { "id": 75, "nombre": "Mono Red Rally" },
  { "id": 76, "nombre": "Mono Red Synthesizer" },
  { "id": 77, "nombre": "Mono White Heroic" },
  { "id": 78, "nombre": "Monster Tron" },
  { "id": 79, "nombre": "Naya Auras" },
  { "id": 80, "nombre": "Naya Bowseeker" },
  { "id": 81, "nombre": "Naya Gates" },
  { "id": 82, "nombre": "Naya Initiative" },
  { "id": 83, "nombre": "Orzhov Blade" },
  { "id": 84, "nombre": "Orzhov Food" },
  { "id": 85, "nombre": "Persistent Petitioners" },
  { "id": 86, "nombre": "Pili-Pala Combo" },
  { "id": 87, "nombre": "Pizza Combo" },
  { "id": 88, "nombre": "Poison Storm" },
  { "id": 89, "nombre": "Rakdos Exhume" },
  { "id": 90, "nombre": "Rakdos Madness" },
  { "id": 91, "nombre": "Rakdos Metalcraft" },
  { "id": 92, "nombre": "Reanimator" },
  { "id": 93, "nombre": "Red Storm" },
  { "id": 94, "nombre": "Retriever Combo" },
  { "id": 95, "nombre": "Rogue" },
  { "id": 96, "nombre": "Selesnya Gates" },
  { "id": 97, "nombre": "Selesnya Ramp" },
  { "id": 98, "nombre": "Simic Slime" },
  { "id": 99, "nombre": "Slivers" },
  { "id": 100, "nombre": "Soul Sisters" },
  { "id": 101, "nombre": "Spy Combo" },
  { "id": 102, "nombre": "Spy Elves" },
  { "id": 103, "nombre": "Sultai Midrange" },
  { "id": 104, "nombre": "Temur Cascade" },
  { "id": 105, "nombre": "Temur Control" },
  { "id": 106, "nombre": "Temur Wildfire" },
  { "id": 107, "nombre": "Turbo Fog" },
  { "id": 108, "nombre": "UB Faeries" },
  { "id": 109, "nombre": "UWx Familiar" },
  { "id": 110, "nombre": "Whale Combo" },
  { "id": 111, "nombre": "White Weenie" },
  { "id": 112, "nombre": "Zombies" },
]
headers = {
   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}
