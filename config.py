######## config.py #######

import os

# Leer variables de entorno
CHALLONGE_USERNAME = os.environ.get("CHALLONGE_USERNAME")
CHALLONGE_API_KEY = os.environ.get("CHALLONGE_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
OPENROUTER_API_KEY =  os.environ.get("OPENROUTER_API_KEY")
GUILD_ID_ADMISION = os.environ.get("GUILD_ID_ADMISION")
CACHE_PATH = os.environ.get("CACHE_PATH")
JWT_SECRET = os.environ.get("JWT_SECRET")

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
    {
        "comando": "strike",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Aplica un strike a un miembro del servidor"
    },
    {
        "comando": "out",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Aplica el rol 'Out' a un miembro del servidor"
    },
    {
        "comando": "eliminar-mensajes",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Elimina una cantidad específica de mensajes en un canal"
    },
    {
        "comando": "cerrar-peticion",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Cierra una petición y envía la respuesta al usuario"
    },
    {
        "comando": "sorteo-torneo",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Realiza un sorteo entre los inscritos de un torneo"
    },
    {
        "comando": "nuevo-sorteo",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_guild"],
        "descripcion": "Crea un nuevo sorteo con sus datos"
    },
    {
        "comando": "realizar-sorteo",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_guild"],
        "descripcion": "Ejecuta un sorteo ya creado por su código"
    },
    {
        "comando": "agendar-partida",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Agenda una partida entre dos jugadores"
    },
    {
        "comando": "modificar-agenda",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "permite modificar o eliminar una partida agendada"
    },
    {
        "comando": "eventos-hoy",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra los eventos programados para hoy"
    },
    {
        "comando": "nueva-peticion",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Crea una nueva petición"
    },
    {
        "comando": "inscribirse",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Inscribe a un usuario en un torneo"
    },
    {
        "comando": "desinscribirse",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Desinscribe a un usuario de un torneo"
    },
    {
        "comando": "ver-inscritos",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra los inscritos en un torneo"
    },
    {
        "comando": "subir-deck",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "permite subir el decklist de un jugador para un torneo"
    },
    {
        "comando": "editar-deck",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "permite modificar el decklist de un jugador para un torneo"
    },
    {
        "comando": "reportar-resultado",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Reporta el resultado de un partido de un torneo"
    },
    {
        "comando": "modificar-resultado",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "permite modificar o eliminar el resultado de un partido mientras la ronda esté abierta"
    },
    {
        "comando": "partidos-pendientes",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Muestra los partidos pendientes de esa ronda de un torneo"
    },
    {
        "comando": "inscribirse-sorteo",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Inscribe a un usuario en un sorteo"
    }, {
        "comando": "cartas-mas-jugadas",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "nos muestra las cartas más jugadas en un torneo o en todos los torneos completados"
        
    },
    {
        "comando": "stats",
        "roles_permitidos": ["socio", "second-chance-socio", "miembro", "admin", "second-chance-miembro"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Permite al usuario ver sus estadísticas en un torneo"
    },
    {
        "comando": "nuevo-torneo",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Crea un nuevo torneo en Challonge"
    },
    {
        "comando": "iniciar-torneo",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Inicia un torneo con el código proporcionado"
    },
    {
        "comando": "actualizar-clasificacion",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Actualiza la clasificación y la publica"
    },
    {
        "comando": "forzar-ronda",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "Termina la ronda actual y comienza la siguiente"
    },
    {
        "comando": "eliminar-decks",
        "roles_permitidos": ["admin"],
        "permisos_discord": ["manage_messages", "manage_roles"],
        "descripcion": "elimina los decks submiteados para un torneo especificado"
    }
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
headers = {
   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}
