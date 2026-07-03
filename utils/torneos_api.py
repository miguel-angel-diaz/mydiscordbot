# torneos_api.py
# ============================================================
# Módulo autocontenido: obtiene todos los torneos finalizados
# de Challonge, calcula sus clasificaciones cruzando con
# Discord, y expone un endpoint HTTP para que la web consuma
# los datos ya procesados.
# ============================================================

import aiohttp
import discord
import json
import os
from datetime import datetime, timezone
from aiohttp import web

import config  # reutiliza tus credenciales ya existentes

CACHE_PATH = "cache/torneos.json"


# ============================================================
# 1. CHALLONGE — listar torneos finalizados
# ============================================================

async def obtener_torneos_finalizados():
    url = "https://api.challonge.com/v1/tournaments.json"
    params = {"state": "ended"}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            params=params,
            auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)
        ) as resp:
            if resp.status != 200:
                raise Exception(f"Error al obtener torneos ({resp.status})")
            torneos_raw = await resp.json()

    torneos = []
    for t in torneos_raw:
        torneo = t["tournament"]
        torneos.append({
            "codigo": torneo["url"],
            "nombre": torneo["name"],
            "fecha_inicio": torneo.get("started_at"),
            "fecha_fin": torneo.get("completed_at"),
            "participantes_count": torneo.get("participants_count"),
        })

    return torneos


# ============================================================
# 2. CHALLONGE + DISCORD — calcular clasificación de un torneo
# ============================================================

async def calcular_clasificacion(guild, codigo_torneo: str):
    url_participants = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/participants.json"
    url_matches = f"https://api.challonge.com/v1/tournaments/{codigo_torneo}/matches.json"

    async with aiohttp.ClientSession() as session:
        async with session.get(url_participants, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                raise Exception("Error al obtener participantes.")
            participantes_raw = await resp.json()

        async with session.get(url_matches, auth=aiohttp.BasicAuth(config.CHALLONGE_USERNAME, config.CHALLONGE_API_KEY)) as resp:
            if resp.status != 200:
                raise Exception("Error al obtener emparejamientos.")
            matches_raw = await resp.json()

    jugadores = {}
    for p in participantes_raw:
        part = p["participant"]
        jugadores[part["id"]] = {
            "name": part["name"],
            "mp": 0,
            "games_won": 0,
            "games_played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "opponents": []
        }

    for m in matches_raw:
        match = m["match"]
        if match["state"] != "complete":
            continue

        p1, p2 = match["player1_id"], match["player2_id"]
        scores = match.get("scores_csv", "").strip()

        if p1 and not p2 and p1 in jugadores:
            jugadores[p1]["mp"] += 3
            jugadores[p1]["wins"] += 1
            continue
        if p2 and not p1 and p2 in jugadores:
            jugadores[p2]["mp"] += 3
            jugadores[p2]["wins"] += 1
            continue

        try:
            s1, s2 = map(int, scores.split("-"))
        except Exception:
            continue

        if p1 not in jugadores or p2 not in jugadores:
            continue

        jugadores[p1]["opponents"].append(p2)
        jugadores[p2]["opponents"].append(p1)
        jugadores[p1]["games_won"] += s1
        jugadores[p1]["games_played"] += s1 + s2
        jugadores[p2]["games_won"] += s2
        jugadores[p2]["games_played"] += s1 + s2

        if s1 > s2:
            jugadores[p1]["mp"] += 3
            jugadores[p1]["wins"] += 1
            jugadores[p2]["losses"] += 1
        elif s2 > s1:
            jugadores[p2]["mp"] += 3
            jugadores[p2]["wins"] += 1
            jugadores[p1]["losses"] += 1
        else:
            jugadores[p1]["mp"] += 1
            jugadores[p2]["mp"] += 1
            jugadores[p1]["draws"] += 1
            jugadores[p2]["draws"] += 1

    clasificacion = []
    for pid, datos in jugadores.items():
        omw = 0.0
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            omw += opp["mp"] / (total_matches * 3)
        omw = omw / len(datos["opponents"]) if datos["opponents"] else 0.0

        buchholz_scores = []
        for o in datos["opponents"]:
            opp = jugadores.get(o)
            if not opp:
                continue
            total_matches = opp["wins"] + opp["losses"] + opp["draws"]
            if total_matches == 0:
                continue
            buchholz_scores.append(opp["mp"] / (total_matches * 3))
        if buchholz_scores:
            buchholz_scores_sorted = sorted(buchholz_scores)[1:-1] if len(buchholz_scores) > 2 else buchholz_scores
            buchholz = sum(buchholz_scores_sorted) / len(buchholz_scores_sorted)
        else:
            buchholz = 0.0

        diff = datos["games_won"] - (datos["games_played"] - datos["games_won"])

        nombre = datos["name"]
        avatar = None
        try:
            miembro = await guild.fetch_member(int(datos["name"]))
            nombre = miembro.display_name
            avatar = str(miembro.display_avatar.url)
        except (ValueError, discord.NotFound, AttributeError):
            pass

        clasificacion.append({
            "nombre": nombre,
            "avatar": avatar,
            "mp": datos["mp"],
            "omw": round(omw, 3),
            "buchholz": round(buchholz, 5),
            "diff": diff,
            "wins": datos["wins"],
            "losses": datos["losses"],
            "draws": datos["draws"]
        })

    clasificacion.sort(key=lambda x: (-x["mp"], -x["omw"], -x["diff"], -x["buchholz"]))

    for i, p in enumerate(clasificacion, 1):
        p["rank"] = i

    return clasificacion


# ============================================================
# 3. CACHÉ — evita golpear Challonge/Discord en cada visita web
# ============================================================

async def regenerar_cache(guild):
    torneos = await obtener_torneos_finalizados()

    resultado = []
    for torneo in torneos:
        try:
            clasificacion = await calcular_clasificacion(guild, torneo["codigo"])
            resultado.append({**torneo, "clasificacion": clasificacion})
        except Exception as e:
            print(f"⚠️ Error procesando {torneo['codigo']}: {e}")
            continue

    payload = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "torneos": resultado
    }

    os.makedirs("cache", exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"✅ Caché regenerado con {len(resultado)} torneo(s).")
    return payload


def leer_cache():
    if not os.path.exists(CACHE_PATH):
        return None
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 4. SERVIDOR WEB — endpoint que consume la web
# ============================================================

async def api_torneos(request):
    data = leer_cache()
    if data is None:
        return web.json_response({"error": "Caché no disponible todavía"}, status=503)

    response = web.json_response(data)
    response.headers['Access-Control-Allow-Origin'] = '*'  # permite fetch desde tu web
    return response


def crear_app():
    app = web.Application()
    app.router.add_get('/api/torneos', api_torneos)
    return app


async def iniciar_servidor_web():
    app = crear_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Servidor web escuchando en el puerto {port}")