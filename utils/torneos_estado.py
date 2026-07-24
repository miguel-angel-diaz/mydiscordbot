# utils/torneos_estado.py
import discord
import json
import re
import aiohttp
import config
from datetime import datetime, timezone
from typing import List, Dict, Optional

CANAL_ESTADO = "torneos-estado"  # Canal donde se guardará el estado
MARCADOR = "📊 ESTADO TORNEOS"

async def get_mensaje_estado(bot):
    """Obtiene el mensaje de estado en el canal correspondiente."""
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=CANAL_ESTADO)
        if channel:
            async for msg in channel.history(limit=50):
                if msg.author == bot.user and msg.content.startswith(MARCADOR):
                    return msg
            # Si no existe, crearlo con estado vacío
            estado = {"torneos": []}
            json_str = json.dumps(estado, indent=2)
            content = f"{MARCADOR}\n```json\n{json_str}\n```"
            return await channel.send(content)
    return None

async def leer_estado(bot):
    """Lee el JSON del mensaje de estado."""
    msg = await get_mensaje_estado(bot)
    if not msg:
        return {"torneos": []}
    match = re.search(r'```json\n(.*?)\n```', msg.content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    return {"torneos": []}

async def guardar_estado(bot, estado):
    """Guarda el JSON en el mensaje de estado."""
    msg = await get_mensaje_estado(bot)
    if not msg:
        return
    json_str = json.dumps(estado, indent=2)
    content = f"{MARCADOR}\n```json\n{json_str}\n```"
    await msg.edit(content=content)

async def actualizar_torneo_estado(bot, codigo_torneo, datos):
    """Actualiza o añade un torneo al estado con los datos proporcionados."""
    estado = await leer_estado(bot)
    torneos = estado.get("torneos", [])
    encontrado = False
    for t in torneos:
        if t.get("codigo") == codigo_torneo:
            t.update(datos)
            encontrado = True
            break
    if not encontrado:
        torneos.append({"codigo": codigo_torneo, **datos})
    estado["torneos"] = torneos
    estado["actualizado"] = datetime.now(timezone.utc).isoformat()
    await guardar_estado(bot, estado)

async def eliminar_torneo_estado(bot, codigo_torneo):
  """Elimina un torneo del estado (cuando finaliza)."""
  estado = await leer_estado(bot)
  estado["torneos"] = [t for t in estado.get("torneos", []) if t.get("codigo") != codigo_torneo]
  await guardar_estado(bot, estado)

async def obtener_inscritos_ids(bot, codigo_torneo) -> List[str]:
  """Devuelve la lista de IDs de Discord inscritos en un torneo según el estado."""
  estado = await leer_estado(bot)
  for t in estado.get("torneos", []):
      if t.get("codigo") == codigo_torneo:
          return t.get("inscritos_ids", [])
  return []

async def sincronizar_estado_handle(ctx):


    """Sincroniza el estado de torneos activos SIN llamar a Challonge."""
    await ctx.author.send("🔄 Sincronizando estado de torneos desde #torneos-activos...")

    from utils.torneos_estado import guardar_estado
    from utils.commons import obtener_torneos_activos_canal

    guild = ctx.guild
    torneos_activos = await obtener_torneos_activos_canal(guild)
    if not torneos_activos:
        await ctx.author.send("❌ No hay torneos activos en el canal #torneos-activos.")
        return

    # Crear estado SIN llamar a Challonge
    torneos_estado = []
    for torneo in torneos_activos:
        torneos_estado.append({
            "codigo": torneo["codigo"],
            "nombre": torneo.get("nombre", "Torneo sin nombre"),
            "nivel": torneo["nivel"],
            "total_maximo": torneo["total_maximo"],
            "inscritos_ids": []  # Vacío, se irá llenando con inscripciones
        })

    # Guardar en el canal de estado
    await guardar_estado(ctx.bot, {"torneos": torneos_estado})
    await ctx.author.send(f"✅ Estado sincronizado con {len(torneos_estado)} torneos activos (sin participantes).")


async def obtener_torneos_activos_estado(bot):
    """Devuelve la lista de torneos activos desde el estado (sin llamar a Challonge)."""
    estado = await leer_estado(bot)
    return estado.get("torneos", [])
