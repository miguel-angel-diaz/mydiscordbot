import discord

async def borrar_mensaje_seguro(ctx):
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")

async def validar_canal_correcto(ctx, canal_valido: str, comando: str):
    """
    Verifica si el comando fue usado en el canal correcto. Si no lo fue:
    - Manda un mensaje privado al autor.
    - Elimina el mensaje del canal si es posible.
    - Retorna False para indicar que no se debe continuar.
    """
    if ctx.channel.name != canal_valido:
        try:
            await ctx.author.send(
                f"❌ El comando `{comando}` solo se puede usar en el canal `#{canal_valido}`.\n"
                f"Usa el comando allí para que funcione correctamente. primer aviso."
            )
        except discord.Forbidden:
            pass  # Usuario con DMs cerrados

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass  # Bot sin permisos para borrar mensajes

        return False
    
    return True