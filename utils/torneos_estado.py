# utils/torneos_estado.py
import discord
import json
import re
import random
import string
from datetime import datetime, timezone
from typing import List, Dict, Optional

CANALES = {
    "estado": "torneos-estado",
    "rondas": "rondas-torneo",
    "clasificacion": "clasificaciones-torneo"
}
PREFIX = "📊 TORNEO: "
PARTE_PATTERN = re.compile(r"\s*\|\s*PARTE\s*(\d+)/(\d+)")

# ============================================================
# FUNCIONES GENÉRICAS PARA CANALES
# ============================================================

async def _get_channel(bot, tipo: str):
    """Obtiene el canal correspondiente según el tipo."""
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=CANALES[tipo])
        if channel:
            return channel
    return None

async def _get_mensaje_torneo(bot, tipo: str, codigo: str):
    """Busca el mensaje principal de un torneo (sin parte)."""
    channel = await _get_channel(bot, tipo)
    if not channel:
        return None
    async for msg in channel.history(limit=200):
        if msg.author != bot.user:
            continue
        if msg.content.startswith(f"{PREFIX}{codigo}"):
            if "| PARTE" not in msg.content.splitlines()[0]:
                return msg
    async for msg in channel.history(limit=200):
        if msg.author == bot.user and msg.content.startswith(f"{PREFIX}{codigo}"):
            return msg
    return None

async def _guardar_dato_torneo(bot, tipo: str, codigo: str, datos: dict):
    """
    Guarda datos en el canal, dividiendo en partes si supera 1900 caracteres.
    """
    channel = await _get_channel(bot, tipo)
    if not channel:
        return

    datos["codigo"] = codigo
    json_str = json.dumps(datos, indent=2, separators=(',', ':'))
    content = f"{PREFIX}{codigo}\n```json\n{json_str}\n```"

    if len(content) <= 1900:
        msg = await _get_mensaje_torneo(bot, tipo, codigo)
        if msg:
            await msg.edit(content=content)
        else:
            await channel.send(content)
        return

    # Eliminar mensajes antiguos de este torneo
    async for msg in channel.history(limit=200):
        if msg.author == bot.user and msg.content.startswith(f"{PREFIX}{codigo}"):
            await msg.delete()

    # Usar JSON compacto para partes
    json_compact = json.dumps(datos, separators=(',', ':'))
    total_len = len(json_compact)
    max_chunk_size = 1800
    num_parts = max(1, (total_len // max_chunk_size) + 1)
    part_size = max(1, len(json_compact) // num_parts)
    parts = [json_compact[i:i+part_size] for i in range(0, len(json_compact), part_size)]

    for idx, part in enumerate(parts, 1):
        part_content = f"{PREFIX}{codigo} | PARTE {idx}/{len(parts)}\n```json\n{part}\n```"
        await channel.send(part_content)

async def _leer_dato_torneo(bot, tipo: str, codigo: str) -> Optional[dict]:
    """
    Lee datos de un torneo, combinando partes si están divididas.
    """
    channel = await _get_channel(bot, tipo)
    if not channel:
        return None

    mensajes = []
    async for msg in channel.history(limit=200):
        if msg.author != bot.user:
            continue
        if msg.content.startswith(f"{PREFIX}{codigo}"):
            mensajes.append(msg)

    if not mensajes:
        return None

    if len(mensajes) == 1:
        msg = mensajes[0]
        match = re.search(r'```json\n(.*?)\n```', msg.content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass
        return None

    partes = {}
    for msg in mensajes:
        lines = msg.content.splitlines()
        if not lines:
            continue
        first_line = lines[0]
        match = PARTE_PATTERN.search(first_line)
        if match:
            part_num = int(match.group(1))
            total_parts = int(match.group(2))
            json_match = re.search(r'```json\n(.*?)\n```', msg.content, re.DOTALL)
            if json_match:
                partes[part_num] = json_match.group(1)
        else:
            json_match = re.search(r'```json\n(.*?)\n```', msg.content, re.DOTALL)
            if json_match:
                partes[1] = json_match.group(1)

    if not partes:
        return None

    json_completo = ""
    for i in range(1, max(partes.keys()) + 1):
        if i in partes:
            json_completo += partes[i]

    if json_completo:
        try:
            return json.loads(json_completo)
        except:
            pass
    return None

async def _eliminar_mensaje_torneo(bot, tipo: str, codigo: str):
    """Elimina todos los mensajes de un torneo en un canal."""
    channel = await _get_channel(bot, tipo)
    if not channel:
        return
    async for msg in channel.history(limit=200):
        if msg.author == bot.user and msg.content.startswith(f"{PREFIX}{codigo}"):
            await msg.delete()

# ============================================================
# FUNCIONES ESPECÍFICAS PARA CADA TIPO
# ============================================================

# utils/torneos_estado.py
async def leer_estado(bot):
    channel = await _get_channel(bot, "estado")
    if not channel:
        return {"torneos": []}  
    torneos = []
    async for msg in channel.history(limit=200):
        if msg.author != bot.user:
            continue
        if not msg.content.startswith(PREFIX):
            continue
        codigo = msg.content.replace(PREFIX, "").split()[0]
        data = await _leer_dato_torneo(bot, "estado", codigo)
        if data:
            torneos.append(data)
    return {"torneos": torneos}  

async def guardar_estado(bot, torneos: list):
    channel = await _get_channel(bot, "estado")
    if not channel:
        return
    codigos_actuales = set()
    async for msg in channel.history(limit=200):
        if msg.author == bot.user and msg.content.startswith(PREFIX):
            codigo = msg.content.replace(PREFIX, "").split()[0]
            codigos_actuales.add(codigo)
    for t in torneos:
        codigo = t.get("codigo")
        if codigo:
            await _guardar_dato_torneo(bot, "estado", codigo, t)
            if codigo in codigos_actuales:
                codigos_actuales.remove(codigo)
    for codigo in codigos_actuales:
        await _eliminar_mensaje_torneo(bot, "estado", codigo)

async def actualizar_torneo_estado(bot, codigo: str, datos: dict):
    actual = await _leer_dato_torneo(bot, "estado", codigo)
    if actual:
        actual.update(datos)
        datos = actual
    await _guardar_dato_torneo(bot, "estado", codigo, datos)

async def eliminar_torneo_estado(bot, codigo: str):
    for tipo in ["estado", "rondas", "clasificacion"]:
        await _eliminar_mensaje_torneo(bot, tipo, codigo)

async def obtener_torneo_estado(bot, codigo: str) -> Optional[dict]:
    return await _leer_dato_torneo(bot, "estado", codigo)

async def obtener_inscritos_ids(bot, codigo: str) -> List[str]:
    data = await _leer_dato_torneo(bot, "estado", codigo)
    if data:
        return data.get("inscritos_ids", [])
    return []

# --- RONDAS ---
async def leer_rondas(bot, codigo: str) -> Optional[dict]:
    return await _leer_dato_torneo(bot, "rondas", codigo)

async def guardar_rondas(bot, codigo: str, datos: dict):
    await _guardar_dato_torneo(bot, "rondas", codigo, datos)

async def eliminar_rondas(bot, codigo: str):
    await _eliminar_mensaje_torneo(bot, "rondas", codigo)

# --- CLASIFICACIÓN ---
async def leer_clasificacion(bot, codigo: str) -> Optional[dict]:
    return await _leer_dato_torneo(bot, "clasificacion", codigo)

async def guardar_clasificacion(bot, codigo: str, datos: dict):
    await _guardar_dato_torneo(bot, "clasificacion", codigo, datos)

async def eliminar_clasificacion(bot, codigo: str):
    await _eliminar_mensaje_torneo(bot, "clasificacion", codigo)

# ============================================================
# UTILIDADES
# ============================================================

def slugify_challonge(value: str) -> str:
    value = value.lower()
    return re.sub(r'[^a-z0-9]', '', value)

def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))

# ============================================================
# SINCRONIZACIÓN (para migrar)
# ============================================================

async def sincronizar_estado_handle(ctx):
    await ctx.author.send("🔄 Sincronizando estado de torneos desde #torneos-activos...")

    from utils.commons import obtener_torneos_activos_canal

    guild = ctx.guild
    torneos_activos = await obtener_torneos_activos_canal(guild)
    if not torneos_activos:
        await ctx.author.send("❌ No hay torneos activos en el canal #torneos-activos.")
        return

    for tipo in ["estado", "rondas", "clasificacion"]:
        channel = await _get_channel(ctx.bot, tipo)
        if channel:
            async for msg in channel.history(limit=200):
                if msg.author == ctx.bot.user and msg.content.startswith(PREFIX):
                    await msg.delete()

    hoy = datetime.now().date()
    for torneo in torneos_activos:
        codigo = torneo["codigo"]
        estado_data = {
            "codigo": codigo,
            "nombre": torneo.get("nombre", "Torneo sin nombre"),
            "nivel": torneo["nivel"],
            "total_maximo": int(torneo.get("total_maximo", 0)) if torneo.get("total_maximo") else None,
            "tipo": "challonge",
            "fecha_inicio": torneo.get("fecha_inicio", datetime.now().strftime("%d/%m/%Y")),
            "estado": "abierto",
            "ronda_actual": 0,
            "inscritos_ids": []
        }
        await _guardar_dato_torneo(ctx.bot, "estado", codigo, estado_data)
        await _guardar_dato_torneo(ctx.bot, "rondas", codigo, {"codigo": codigo, "rondas": []})
        await _guardar_dato_torneo(ctx.bot, "clasificacion", codigo, {"codigo": codigo, "clasificacion": []})

    await ctx.author.send(f"✅ Estado sincronizado con {len(torneos_activos)} torneos activos.")