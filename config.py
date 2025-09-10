TOKEN = "MTM4NTEzMDg4Mjc3OTcxMzc0Ng.GktO2Y.FWoFmecTUEOYV0jqBkvpuWvxq3HrBJIJzIwr_Q"
CHALLONGE_USERNAME = "TheKlub"
CHALLONGE_API_KEY = "WfdVp0bApiTGP3OTiOsM4hhuSNPgsUDrndBCVzaG"
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
headers = {
   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}
