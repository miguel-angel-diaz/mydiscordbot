######## ayuda.py #######
"""
Lista de comandos para la ayuda (!mis-comandos, bienvenida...), generada desde los comandos registrados:
  - nombre, alias y roles salen del propio comando (no se pueden desincronizar);
  - descripción, tutorial y sección salen de data/ayuda_comandos.json (texto redactado a mano).
Antes era una lista fija en config.py: se quedaba atrás (5 comandos sin ayuda y uno que ya no existía).
"""
import logging
from typing import Dict, List

import config
from utils import canales

log = logging.getLogger(__name__)
EXCLUIDOS = {"help"}       # el comando de ayuda por defecto de discord.py
_bot = None


def registrar_bot(bot):
    """main.py registra el bot al crearlo (como set_bot_instance para la web)."""
    global _bot
    _bot = bot


def roles_de(comando) -> List[str]:
    """Roles que ven el comando: los del decorador comando_roles_permitidos (+ admin), solo admin si exige
    permiso de administrador, o todos los roles si no tiene restricción."""
    for check in comando.checks:
        roles = getattr(check, "roles_permitidos", None)
        if roles is not None:
            return sorted({*roles, canales.ROL_ADMIN})
    if any(getattr(c, "__qualname__", "").startswith("has_permissions") for c in comando.checks):
        return [canales.ROL_ADMIN]
    return sorted(config.ROLES_TODOS)


def comandos_info(bot=None) -> List[Dict]:
    """[{comando, aliases, roles_permitidos, descripcion, tutorial, seccion, permisos_discord}] en el orden del JSON."""
    bot = bot or _bot
    if bot is None:
        log.warning("⚠️ Ayuda pedida sin bot registrado: lista de comandos vacía.")
        return []
    textos = config.AYUDA_COMANDOS
    comandos = {c.qualified_name: c for c in bot.walk_commands() if c.qualified_name not in EXCLUIDOS}
    orden = [n for n in textos if n in comandos] + sorted(n for n in comandos if n not in textos)
    resultado = []
    for nombre in orden:
        comando, texto = comandos[nombre], textos.get(nombre, {})
        resultado.append({
            "comando": nombre,
            "aliases": list(comando.aliases),
            "roles_permitidos": roles_de(comando),
            "descripcion": texto.get("descripcion") or (comando.help or nombre).split(" - ")[0].strip(),
            "tutorial": texto.get("tutorial", []),
            "seccion": texto.get("seccion", ""),
            "permisos_discord": texto.get("permisos_discord", []),
        })
    return resultado


def comandos_sin_ayuda(bot) -> List[str]:
    """Comandos registrados sin texto en data/ayuda_comandos.json (para detectar olvidos)."""
    return sorted(c.qualified_name for c in bot.walk_commands()
                  if c.qualified_name not in EXCLUIDOS and c.qualified_name not in config.AYUDA_COMANDOS)
