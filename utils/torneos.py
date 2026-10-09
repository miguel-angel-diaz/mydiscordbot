######## torneos.py #######

from utils.commons import (
    obtener_torneo_usuario,
    cartas_mas_jugadas,
    best_decks_handle,
    analizar_torneo_con_ia
)
from utils.admin import moderador_permisos_handle


async def tournament_report_handle(ctx, codigo_torneo: str = None):
    # Solo moderadores
    if not await moderador_permisos_handle(ctx):
        return
    # 🔹 Obtener código de torneo
    if not codigo_torneo:
        codigo_torneo = await obtener_torneo_usuario(
            ctx,
            mensaje_inicial="📩 No escribiste el código del torneo.\nElige el torneo del informe:",
            complete=True
        )
        if not codigo_torneo:
            return
    if isinstance(codigo_torneo, list):     # "todos": el informe es de un torneo concreto
        await ctx.author.send("❌ El informe se hace de un torneo concreto: elige uno, no 'todos'.")
        return

    # 🔹 Obtener datos
    cartas_data = await cartas_mas_jugadas(ctx, codigo_torneo, '🧠📈analisis-torneos')
    decks_data = await best_decks_handle(ctx, codigo_torneo, '🧠📈analisis-torneos')

    if not cartas_data or not decks_data:
        return await ctx.send("❌ No se pudo generar el informe del torneo.")

    # 🔹 Analizar con IA
    await analizar_torneo_con_ia(ctx, cartas_data, decks_data)


