import aiohttp
import discord
import logging
from discord.ext import commands
from typing import Optional, List, Dict, Any


CARDTRADER_API_BASE = "https://api.cardtrader.com/api/v2"
ALERTS_CHANNEL_NAME = "price-alerts-db"

logger = logging.getLogger(__name__)

class CardTraderAPI:
    """Cliente para la API de CardTrader (sin autenticación)."""
    
    def __init__(self, session: aiohttp.ClientSession = None):
        self.session = session or aiohttp.ClientSession()
        self.base_url = CARDTRADER_API_BASE

    async def search_products(self, query: str, expansion: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Busca productos por nombre y opcionalmente expansión."""
        params = {
            "q": query,
            "limit": limit,
        }
        if expansion:
            params["expansion"] = expansion
        async with self.session.get(f"{self.base_url}/products", params=params) as resp:
            if resp.status != 200:
                logger.error(f"Error buscando productos: {resp.status} - {await resp.text()}")
                return []
            data = await resp.json()
            return data.get("products", [])

    async def get_product_price(self, product_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene el precio actual de un producto específico."""
        async with self.session.get(f"{self.base_url}/products/{product_id}/price") as resp:
            if resp.status != 200:
                logger.error(f"Error obteniendo precio: {resp.status} - {await resp.text()}")
                return None
            return await resp.json()

    async def get_product_details(self, product_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene detalles completos de un producto."""
        async with self.session.get(f"{self.base_url}/products/{product_id}") as resp:
            if resp.status != 200:
                logger.error(f"Error obteniendo detalles: {resp.status} - {await resp.text()}")
                return None
            return await resp.json()

    async def close(self):
        await self.session.close()

class AlertStorage:
    """Gestiona el almacenamiento de alertas en un canal de Discord."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel = None

    async def get_channel(self) -> Optional[discord.TextChannel]:
        if self.channel:
            return self.channel
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=ALERTS_CHANNEL_NAME)
            if channel:
                self.channel = channel
                return channel
        # Crear si no existe (en el primer gremio)
        if self.bot.guilds:
            guild = self.bot.guilds[0]
            try:
                category = guild.categories[0] if guild.categories else None
                self.channel = await guild.create_text_channel(ALERTS_CHANNEL_NAME, category=category)
                await self.channel.send("🔔 **BASE DE DATOS DE ALERTAS DE PRECIOS**\nFormato: id|user_id|product_id|nombre|precio_min|precio_max|expansion|foil|idioma|estado|activa")
                return self.channel
            except discord.Forbidden:
                logger.error("No tengo permisos para crear el canal de alertas.")
                return None
        return None

    async def read_alerts(self) -> List[Dict[str, Any]]:
        channel = await self.get_channel()
        if not channel:
            return []
        alerts = []
        async for message in channel.history(limit=200, oldest_first=True):
            if message.author != self.bot.user:
                continue
            if message.content.startswith("🔔 **BASE DE DATOS"):
                continue
            for line in message.content.splitlines():
                line = line.strip()
                if not line or line.startswith("🔔"):
                    continue
                parts = line.split("|")
                if len(parts) >= 11:
                    try:
                        alert = {
                            "id": parts[0],
                            "user_id": int(parts[1]),
                            "product_id": int(parts[2]) if parts[2].isdigit() else None,
                            "nombre": parts[3],
                            "precio_min": float(parts[4]) if parts[4] else None,
                            "precio_max": float(parts[5]) if parts[5] else None,
                            "expansion": parts[6] if parts[6] else None,
                            "foil": parts[7].lower() == "true",
                            "idioma": parts[8] if parts[8] else None,
                            "estado": parts[9],  # active, paused, triggered
                            "ultimo_precio": float(parts[10]) if parts[10] else None,
                            "ultima_notificacion": parts[11] if parts[11] else None
                        }
                        alerts.append(alert)
                    except Exception as e:
                        logger.error(f"Error parseando alerta: {line} - {e}")
        return alerts

    async def save_alerts(self, alerts: List[Dict[str, Any]]):
        channel = await self.get_channel()
        if not channel:
            return
        async for message in channel.history(limit=200):
            if message.author == self.bot.user:
                await message.delete()
        lines = ["🔔 **BASE DE DATOS DE ALERTAS DE PRECIOS**\nFormato: id|user_id|product_id|nombre|precio_min|precio_max|expansion|foil|idioma|estado|ultimo_precio|ultima_notificacion"]
        for alert in alerts:
            line = f"{alert['id']}|{alert['user_id']}|{alert.get('product_id', '')}|{alert['nombre']}|{alert.get('precio_min', '')}|{alert.get('precio_max', '')}|{alert.get('expansion', '')}|{alert.get('foil', False)}|{alert.get('idioma', '')}|{alert['estado']}|{alert.get('ultimo_precio', '')}|{alert.get('ultima_notificacion', '')}"
            lines.append(line)
        content = "\n".join(lines)
        if len(content) > 1900:
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                await channel.send(chunk)
        else:
            await channel.send(content)

    async def add_alert(self, alert: Dict[str, Any]):
        alerts = await self.read_alerts()
        alerts.append(alert)
        await self.save_alerts(alerts)

    async def update_alert(self, alert_id: str, updates: Dict[str, Any]):
        alerts = await self.read_alerts()
        for idx, alert in enumerate(alerts):
            if alert["id"] == alert_id:
                alerts[idx].update(updates)
                break
        await self.save_alerts(alerts)

    async def delete_alert(self, alert_id: str):
        alerts = await self.read_alerts()
        alerts = [a for a in alerts if a["id"] != alert_id]
        await self.save_alerts(alerts)

    async def get_user_alerts(self, user_id: int) -> List[Dict[str, Any]]:
        alerts = await self.read_alerts()
        return [a for a in alerts if a["user_id"] == user_id]