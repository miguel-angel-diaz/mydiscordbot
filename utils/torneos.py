import discord
from discord.ext import commands
import aiohttp
import asyncio
import os
import re
import config
from datetime import datetime
import random
import string


from utils.admin import moderador_permisos_handle

CHALLONGE_API_KEY = "DwMmC03iVa5UKm377ZaScn6omJ3EA6jWRcPvzZOJ"

def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))

async def asignar_strike_automatico(ctx):
    rol = discord.utils.get(ctx.guild.roles, name="Strike")
    if rol and rol not in ctx.author.roles:
        await ctx.author.add_roles(rol)
        await ctx.send(f"⚠️ {ctx.author.mention} ha recibido el rol **Strike** por intentar ejecutar un comando sin permisos.")

def slugify_challonge(value: str) -> str:
    # Convierte a minúsculas y elimina cualquier carácter que no sea letra o número
    value = value.lower()
    return re.sub(r'[^a-z0-9]', '', value)

async def nuevo_torneo(ctx, *, args: str):
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")
    
      # Verificar permisos
    if not await moderador_permisos_handle(ctx):
      return

    partes = [p.strip() for p in args.split("|")]
    if len(partes) != 7:
        await ctx.author.send("❌ Formato incorrecto. Usa:\n`!nuevo-torneo Nombre | Formato | tipo | Jugadores | Fecha | Nivel | DeckURL`")
        return

    nombre, formato, tipo_challonge, jugadores, fecha, nivel, deck_url = partes

    try:
        jugadores = int(jugadores)
    except ValueError:
        await ctx.author.send("❌ El número de jugadores debe ser un número entero.")
        return

    try:
        fecha_obj = datetime.strptime(fecha, "%d/%m/%Y")
    except ValueError:
        await ctx.author.send("❌ La fecha debe tener el formato `DD/MM/AAAA` (ej. 20/08/2025).")
        return

    # 🔢 Generar código único y construir URL de Challonge
    slug_formato = slugify_challonge(formato)
    slug_nivel = slugify_challonge(nivel)
    codigo = generar_codigo_unico()
    url_challonge = f"{slug_formato}{slug_nivel}{codigo}"

    # 📦 Payload para Challonge
    payload = {
        "api_key": config.CHALLONGE_API_KEY,
        "tournament": {
            "name": nombre,
            "url": url_challonge,
            "tournament_type": tipo_challonge,
            "description": f"Torneo {formato} - {nivel}",
            "signup_cap": jugadores,
            "start_at": fecha_obj.isoformat()
        }
    }

    # 🌐 Llamada a Challonge
    async with aiohttp.ClientSession() as session:
        async with session.post(config.CHALLONGE_API_URL, json=payload, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as response:
            if response.status in (200, 201):
                data = await response.json()
                tournament = data["tournament"]

                # ✅ DM al creador
                await ctx.author.send(
                    f"✅ Torneo creado con éxito: **{tournament['name']}**\n"
                    f"🌐 URL: https://challonge.com/{url_challonge}\n"
                    f"📥 Decklists: {deck_url}"
                )

                # 📣 Anuncio en canal de torneos
                canal_anuncios = discord.utils.get(ctx.guild.text_channels, name="anuncios-torneos")
                if canal_anuncios:
                    await canal_anuncios.send(
                        f"📢 **Nuevo torneo creado!**\n"
                        f"🏷️ **Nombre:** {nombre}\n"
                        f"🎮 **Formato:** {formato}\n"
                        f"👥 **Jugadores máximos:** {jugadores}\n"
                        f"📅 **Inicio:** {fecha}\n"
                        f"🔒 **Nivel:** {nivel}\n"
                        f"📥 **Decks:** {deck_url}\n"
                        f" **Código:** {url_challonge}\n"
                        f"🌐 **Challonge:** https://challonge.com/{url_challonge}"
                    )
                else:
                    await ctx.author.send("⚠️ No se encontró el canal `anuncios-torneos` en este servidor.")
                            # Buscar el canal de torneos activos
                canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
                if canal_torneos is None:
                    await ctx.author.send("⚠️ No encontré el canal `#torneos-activos`. Por favor, créalo.")
                    return

                # Crear el mensaje público
                mensaje_torneo = (
                    f"🎮 **Torneo creado:** {nombre}\n"
                    f"🏷️ **Código:** `{url_challonge}`\n"
                    f"📋 **Formato:** {formato}\n"
                    f"👥 **Jugadores:** {jugadores}\n"
                    f"📅 **Inicio:** {fecha}\n"
                    f"🎯 **Nivel:** {nivel}\n"
                    f"📥 **Decks:** {deck_url}"
                )

                await canal_torneos.send(mensaje_torneo)
            else:
                error = await response.text()
                await ctx.author.send(f"❌ Error al crear el torneo:\n```{error}```")