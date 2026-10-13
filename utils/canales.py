######## canales.py #######
"""
Nombres de los canales y roles del servidor, en un solo sitio (antes había 73 búsquedas con el nombre escrito
a mano). Si se renombra un canal en Discord, solo hay que cambiarlo aquí.

Ojo: varios nombres llevan el guion especial U+2010 ("‐"), no el guion normal; se copian tal cual.
"""
from typing import Optional

import discord

# ============================================================
# CANALES
# ============================================================

# Comandos y peticiones
COMANDOS = "preguntale-a-el-barbas"
PETICIONES = "peticiones-de-usuarios"
RESOLUCION_PETICIONES = "resolucion-de-peticiones"
SOLICITUDES_ADMISION = "solicitudes-admision"

# Torneos
TORNEOS_ACTIVOS = "torneos-activos"
CARTELERA_TORNEOS = "📰-cartelera‐torneos"
CITAS = "🍸-citas‐a‐ciegas"
RESULTADOS = "🍺-quién‐se‐lleva‐la‐ronda"
RANKING = "🍺-el‐ranking‐de‐la‐barra"
DECKS = "submitted-decks"
ANALISIS_TORNEOS = "🧠📈analisis-torneos"

# Agenda de partidas
AGENDA = "partidos-agendados"
CARTELERA_PARTIDAS = "🎭-cartelera‐proximas-partidas"

# Sorteos
SORTEOS_ACTIVOS = "sorteos-activos"
INSCRITOS_SORTEOS = "inscritos-sorteos"

# Estado interno del bot (mensajes JSON)
ESTADO_TORNEOS = "torneos-estado"
RONDAS_TORNEOS = "rondas-torneo"
CLASIFICACIONES_TORNEOS = "clasificaciones-torneo"

# Moderación y registros
REGISTRO_USUARIOS = "registro-de-usuarios"
USUARIOS_QUE_SE_FUERON = "usuarios-que-nos-dejaron"
MENSAJES_BORRADOS = "mensajes-borrados"
BLACKLIST = "blacklist"
VESTIBULO = "🪞-vestíbulo‐"
REGISTRO_VOZ = "registro-canales-voz"
OYENTES = "oyentes-en-canales"

# Log de comandos ejecutados y errores (cogs/eventos.py -> events.log_comando_handle); solo por ID
LOG_COMANDOS_ID = 1413079518440198206

# Anuncios: por ID y, si no, por nombre (con el guion especial U+2010 o con guion normal)
ANUNCIOS_ID = 1387389356464934993
ANUNCIOS_NOMBRES = ("📰-tablon‐anuncios", "📰-tablon-anuncios")

# ============================================================
# ROLES
# ============================================================

ROL_ADMIN = "admin"
ROL_MIEMBRO = "miembro"
ROL_OUT = "Out"
ROL_STRIKE = "Strike"
ROL_ACEPTA_BIENVENIDA = "Accept Welcome"
ROL_ACEPTA_REGLAS = "Accept Rules"
ROL_SOCIO = "socio"
ROL_SOCIO_2C = "second-chance-socio"
ROL_MIEMBRO_2C = "second-chance-miembro"

# Grupos
ROLES_JUGADORES = (ROL_SOCIO, ROL_SOCIO_2C, ROL_MIEMBRO, ROL_MIEMBRO_2C)   # pueden usar los comandos de jugador
ROLES_BIENVENIDA = (ROL_ACEPTA_BIENVENIDA, ROL_ACEPTA_REGLAS)


# ============================================================
# BÚSQUEDA
# ============================================================

def get_canal(guild, nombre: str) -> Optional[discord.TextChannel]:
    """Canal de texto por nombre exacto, o None (también si no hay servidor, p. ej. en un DM)."""
    if guild is None:
        return None
    return discord.utils.get(guild.text_channels, name=nombre)


def get_rol(guild, nombre: str) -> Optional[discord.Role]:
    if guild is None:
        return None
    return discord.utils.get(guild.roles, name=nombre)


def canal_anuncios(guild) -> Optional[discord.TextChannel]:
    """Tablón de anuncios: por ID y, si no existe, por cualquiera de sus nombres."""
    if guild is None:
        return None
    canal = guild.get_channel(ANUNCIOS_ID)
    if canal:
        return canal
    for nombre in ANUNCIOS_NOMBRES:
        canal = get_canal(guild, nombre)
        if canal:
            return canal
    return None
