# utils/torneos_estado.py
import discord
import json
import re
import random
import string
from datetime import datetime, timezone
from typing import List, Dict, Optional

CANAL_ESTADO = "torneos-estado"
MARCADOR = "📊 ESTADO TORNEOS"

# ============================================================
# FUNCIONES DE ESTADO (LECTURA/ESCRITURA)
# ============================================================

async def get_mensaje_estado(bot):
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=CANAL_ESTADO)
        if channel:
            async for msg in channel.history(limit=50):
                if msg.author == bot.user and msg.content.startswith(MARCADOR):
                    return msg
            estado = {"torneos": []}
            json_str = json.dumps(estado, indent=2)
            content = f"{MARCADOR}\n```json\n{json_str}\n```"
            return await channel.send(content)
    return None

async def leer_estado(bot):
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
    msg = await get_mensaje_estado(bot)
    if not msg:
        return
    json_str = json.dumps(estado, indent=2)
    content = f"{MARCADOR}\n```json\n{json_str}\n```"
    await msg.edit(content=content)

async def actualizar_torneo_estado(bot, codigo_torneo, datos):
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
    estado = await leer_estado(bot)
    estado["torneos"] = [t for t in estado.get("torneos", []) if t.get("codigo") != codigo_torneo]
    await guardar_estado(bot, estado)

async def obtener_inscritos_ids(bot, codigo_torneo) -> List[str]:
    estado = await leer_estado(bot)
    for t in estado.get("torneos", []):
        if t.get("codigo") == codigo_torneo:
            return t.get("inscritos_ids", [])
    return []

async def obtener_torneos_activos_estado(bot):
    estado = await leer_estado(bot)
    return estado.get("torneos", [])

# ============================================================
# UTILIDADES (independientes)
# ============================================================

def slugify_challonge(value: str) -> str:
    value = value.lower()
    return re.sub(r'[^a-z0-9]', '', value)

def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))

# ============================================================
# COMANDO DE SINCRONIZACIÓN (desde admin)
# ============================================================

async def sincronizar_estado_handle(ctx):
    await ctx.author.send("🔄 Sincronizando estado de torneos desde #torneos-activos...")

    from utils.commons import obtener_torneos_activos_canal

    guild = ctx.guild
    torneos_activos = await obtener_torneos_activos_canal(guild)
    if not torneos_activos:
        await ctx.author.send("❌ No hay torneos activos en el canal #torneos-activos.")
        return

    torneos_estado = []
    for torneo in torneos_activos:
        total_maximo = torneo.get("total_maximo")
        if total_maximo is not None:
            try:
                total_maximo = int(total_maximo)
            except (ValueError, TypeError):
                total_maximo = None

        torneos_estado.append({
            "codigo": torneo["codigo"],
            "nombre": torneo.get("nombre", "Torneo sin nombre"),
            "nivel": torneo["nivel"],
            "total_maximo": total_maximo,
            "inscritos_ids": [],
            "tipo": "challonge"
        })

    await guardar_estado(ctx.bot, {"torneos": torneos_estado})
    await ctx.author.send(f"✅ Estado sincronizado con {len(torneos_estado)} torneos activos (sin participantes).")