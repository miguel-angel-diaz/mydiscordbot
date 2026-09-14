import discord
import asyncio
import aiohttp
import re
import uuid
from typing import Optional, List, Dict, Any

from utils.cardtrader_api import CardTraderAPI, AlertStorage
from utils.commons import borrar_mensaje_seguro, validar_canal_correcto

# Expansiones Premodern para autocompletar (opcional)
PREMONERN_EXPANSIONS = [
    "4th Edition", "Ice Age", "Chronicles", "Homelands", "Alliances",
    "Mirage", "Visions", "5th Edition", "Weatherlight", "Tempest",
    "Stronghold", "Exodus", "Urza's Saga", "Urza's Legacy", "Urza's Destiny",
    "Mercadian Masques", "Nemesis", "Prophecy", "Invasion", "Planeshift",
    "Apocalypse", "Odyssey", "Torment", "Judgment", "Onslaught", "Legions",
    "Scourge"
]

# Estados (condición) de CardTrader (ordenados de mejor a peor)
CONDITIONS = ["Mint", "Near Mint", "Excellent", "Good", "Lightly Played", "Played", "Poor"]

async def iniciar_seguimiento_handle(ctx):
    """Comando !seguir-precio: inicia el wizard para crear una alerta de precio."""
    # Eliminar mensaje original si es posible
    await borrar_mensaje_seguro(ctx)
    # No validamos canal específico, se puede usar en cualquier canal (se responde por DM)
    author = ctx.author

    # Crear instancias de API y almacenamiento
    api = CardTraderAPI()
    storage = AlertStorage(ctx.bot)

    def dm_check(m):
        return m.author == author and isinstance(m.channel, discord.DMChannel)

    try:
        # Paso 1: Pedir nombre de la carta
        await author.send("🔍 **Iniciando seguimiento de precio.**\nEscribe el nombre de la carta que quieres seguir (puede ser parcial):")
        msg_nombre = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        nombre_busqueda = msg_nombre.content.strip()
        if not nombre_busqueda:
            await author.send("❌ Nombre no válido. Cancelo.")
            return

        # Paso 2: Buscar productos
        await author.send("🔎 Buscando en CardTrader...")
        productos = await api.search_products(nombre_busqueda, limit=20)
        if not productos:
            await author.send("❌ No se encontraron cartas con ese nombre. Intenta con otro término.")
            return

        # Mostrar lista de productos (hasta 10)
        opciones = []
        for i, prod in enumerate(productos[:10], start=1):
            nombre = prod.get('name', 'Sin nombre')
            expansion = prod.get('expansion_name', 'Sin edición')
            rarity = prod.get('rarity', '')
            opciones.append(f"{i}. **{nombre}** ({expansion}) {rarity}")
        await author.send("📋 **Selecciona el número de la carta que te interesa:**\n" + "\n".join(opciones))

        msg_seleccion = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        try:
            idx = int(msg_seleccion.content.strip()) - 1
            if idx < 0 or idx >= len(productos):
                raise ValueError
            producto_seleccionado = productos[idx]
        except:
            await author.send("❌ Selección no válida. Cancelo.")
            return

        # Paso 3: Mostrar ediciones disponibles (si hay más de una)
        product_id = producto_seleccionado['id']
        detalles = await api.get_product_details(product_id)
        if not detalles:
            await author.send("❌ No se pudieron obtener detalles del producto.")
            return

        # Obtener las ediciones (expansiones) de este producto (puede haber varias versiones)
        # La API devuelve un array de "prints" o similar, pero en el endpoint /products/{id} puede haber un campo "expansion"
        # Usamos la expansión del producto seleccionado, pero si hay varias, podríamos mostrar opciones.
        # Por simplicidad, tomamos la expansión que viene en el producto.
        expansion_seleccionada = producto_seleccionado.get('expansion_name')
        if not expansion_seleccionada:
            await author.send("⚠️ No se pudo determinar la edición. Usaré la que tenga.")
            expansion_seleccionada = "Unknown"

        # Paso 4: Idiomas disponibles (simulamos, ya que la API no devuelve idiomas fácilmente)
        # Podríamos permitir elegir idioma, pero para simplificar ofrecemos "Cualquiera" o "Inglés"
        await author.send("🌐 **Idiomas disponibles:**\n1. Cualquiera\n2. Inglés\n3. Español\n4. Francés\n5. Alemán\nElige el número (o escribe '1' para cualquiera):")
        msg_idioma = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        idioma_opcion = msg_idioma.content.strip()
        idioma_map = {"1": None, "2": "English", "3": "Spanish", "4": "French", "5": "German"}
        idioma_seleccionado = idioma_map.get(idioma_opcion)
        if idioma_seleccionado is None and idioma_opcion != "1":
            await author.send("❌ Opción no válida. Usaré 'Cualquiera'.")
            idioma_seleccionado = None

        # Paso 5: Estado (condición) mínimo
        await author.send("📦 **Elige el estado mínimo que aceptas:**\n" + "\n".join([f"{i+1}. {c}" for i, c in enumerate(CONDITIONS)]))
        msg_estado = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        try:
            estado_idx = int(msg_estado.content.strip()) - 1
            if estado_idx < 0 or estado_idx >= len(CONDITIONS):
                raise ValueError
            estado_minimo = CONDITIONS[estado_idx]
        except:
            await author.send("❌ Opción no válida. Usaré 'Near Mint'.")
            estado_minimo = "Near Mint"

        # Paso 6: Obtener precio actual y trending
        precio_info = await api.get_product_price(product_id)
        if not precio_info:
            await author.send("❌ No se pudo obtener el precio actual.")
            return
        precio_actual = precio_info.get('price', 0.0)
        trending = precio_info.get('trend', 'desconocida')

        # Mostrar precio y trending
        await author.send(f"💰 **Precio actual:** {precio_actual:.2f}€\n📈 **Tendencia:** {trending}")

        # Paso 7: Preguntar si quiere seguimiento
        await author.send("❓ **¿Quieres hacer seguimiento de este precio?** Responde **sí** o **no**.")
        msg_seguir = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        if msg_seguir.content.lower() not in ("sí", "si", "s", "yes", "y"):
            # No quiere seguimiento: devolver enlace
            await author.send(f"🔗 Puedes ver la carta en CardTrader: https://www.cardtrader.com/es/products/{product_id}")
            await api.close()
            return

        # Paso 8: Pedir precios mínimo y máximo
        await author.send("📊 **Indica el precio mínimo y máximo (separados por espacio) entre los que quieres ser notificado.**\nEjemplo: `2.50 5.00` (puedes poner solo mínimo o solo máximo, ej: `2.50` para solo mínimo, o `5.00` para solo máximo).")
        msg_rango = await ctx.bot.wait_for("message", check=dm_check, timeout=60.0)
        partes = msg_rango.content.strip().split()
        precio_min = None
        precio_max = None
        try:
            if len(partes) >= 1:
                precio_min = float(partes[0]) if partes[0] else None
            if len(partes) >= 2:
                precio_max = float(partes[1]) if partes[1] else None
            if len(partes) == 1:
                # Si solo un número, lo tomamos como mínimo (o máximo según contexto, pero mejor preguntar)
                # Para simplificar, si solo un número, lo usamos como mínimo.
                precio_min = float(partes[0])
        except ValueError:
            await author.send("❌ Precios no válidos. Usa números. Ejemplo: `2.50 5.00`")
            return

        if precio_min is None and precio_max is None:
            await author.send("❌ Debes indicar al menos un precio (mínimo o máximo).")
            return

        # Paso 9: Crear alerta
        alert_id = str(uuid.uuid4())[:8]
        alert = {
            "id": alert_id,
            "user_id": author.id,
            "product_id": product_id,
            "nombre": producto_seleccionado.get('name', 'Carta'),
            "precio_min": precio_min,
            "precio_max": precio_max,
            "expansion": expansion_seleccionada,
            "foil": False,  # Podríamos preguntar si es foil, pero no en este flujo
            "idioma": idioma_seleccionado,
            "estado": "active",
            "ultimo_precio": precio_actual,
            "ultima_notificacion": None
        }

        await storage.add_alert(alert)
        await author.send(f"✅ **Alerta creada con ID `{alert_id}`.**\nTe notificaré cuando el precio de **{alert['nombre']}** esté entre {precio_min or 'sin mínimo'}€ y {precio_max or 'sin máximo'}€.")

        # Limpiar
        await api.close()

    except asyncio.TimeoutError:
        await author.send("⏰ Tiempo agotado. Vuelve a intentarlo con `!seguir-precio`.")
    except Exception as e:
        await author.send(f"❌ Ocurrió un error inesperado: {e}")
        raise e
    finally:
        await api.close()