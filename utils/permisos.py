######## permisos.py #######
"""
Permisos de los comandos: cada Cog declara sus roles y los comprueba en cog_check (antes un decorador por comando
en main.py). Los comandos que exigen el permiso de administrador de Discord llevan su propio has_permissions y se
marcan con extras={"solo_admin": True} para que el cog_check no los filtre por rol.
"""
import unicodedata
from typing import Optional, Tuple

import discord
from discord.ext import commands

from utils import canales


def normalize_string(s: str) -> str:
    """Convierte a minúsculas y elimina acentos"""
    s = s.lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


ROL_ADMIN = normalize_string(canales.ROL_ADMIN)
ROLES_SANCIONADOS = {normalize_string(canales.ROL_OUT), normalize_string(canales.ROL_STRIKE)}  # bloquean los comandos aunque se tenga un rol permitido
SOLO_ADMIN = {"solo_admin": True}


async def _denegar_comando(ctx, mensaje: str) -> bool:
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass
    try:
        await ctx.author.send(mensaje)
    except discord.Forbidden:
        pass
    return False


async def comprobar_roles(ctx, roles) -> bool:
    """
    Permite el comando a los roles indicados (sin distinguir mayúsculas ni tildes).
    El dueño del servidor y los admins siempre pueden usarlo; quien tenga un rol
    de sanción (Out/Strike) no puede, aunque tenga un rol permitido.
    """
    comando = f"!{ctx.command.qualified_name}"
    if ctx.guild is None:
        return await _denegar_comando(ctx, f"❌ El comando `{comando}` solo se puede usar en el servidor.")

    autor = ctx.author
    roles_autor = {normalize_string(r.name) for r in getattr(autor, "roles", [])}

    es_admin = (
        autor == ctx.guild.owner
        or ROL_ADMIN in roles_autor
        or autor.guild_permissions.administrator
    )
    if es_admin:
        return True

    if roles_autor & ROLES_SANCIONADOS:
        return await _denegar_comando(ctx, f"🚫 No puedes usar `{comando}` mientras tengas una sanción activa.")

    if roles_autor & {normalize_string(r) for r in roles}:
        return True

    return await _denegar_comando(
        ctx,
        f"❌ Necesitas uno de estos roles para usar `{comando}`: {', '.join(sorted(roles))}."
    )


class CogConRoles(commands.Cog):
    """Cog cuyos comandos exigen uno de `roles_permitidos` (None = sin restricción). Lo lee utils/ayuda.py."""
    roles_permitidos: Optional[Tuple[str, ...]] = None

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx) -> bool:
        if self.roles_permitidos is None or ctx.command.extras.get("solo_admin"):
            return True     # sin restricción, o la pone su propio has_permissions(administrator=True)
        return await comprobar_roles(ctx, self.roles_permitidos)
