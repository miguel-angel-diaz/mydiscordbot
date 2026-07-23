# utils/swiss_manager.py
import random
import math
from collections import defaultdict
from typing import List, Dict, Tuple, Optional
import discord
import asyncio

class SwissManager:
    """
    Gestiona torneos suizos sin Challonge, usando canales de Discord como almacenamiento.
    """

    def __init__(self, bot, guild):
        self.bot = bot
        self.guild = guild

    # ------------------------------------------------------------
    # 1. Lectura/Escritura en canales
    # ------------------------------------------------------------

    async def _get_channel(self, name: str) -> Optional[discord.TextChannel]:
        return discord.utils.get(self.guild.text_channels, name=name)

    async def _read_lines(self, channel_name: str) -> List[str]:
        channel = await self._get_channel(channel_name)
        if not channel:
            return []
        lines = []
        async for msg in channel.history(limit=100, oldest_first=True):
            if msg.author == self.bot.user:
                lines.extend(msg.content.splitlines())
        return [l.strip() for l in lines if l.strip()]

    async def _write_lines(self, channel_name: str, lines: List[str], clear: bool = True):
        channel = await self._get_channel(channel_name)
        if not channel:
            return
        if clear:
            async for msg in channel.history(limit=100):
                if msg.author == self.bot.user:
                    await msg.delete()
        content = "\n".join(lines)
        if content:
            # Partir en mensajes de 1900 caracteres
            for chunk in [content[i:i+1900] for i in range(0, len(content), 1900)]:
                await channel.send(chunk)

    async def _append_line(self, channel_name: str, line: str):
        channel = await self._get_channel(channel_name)
        if not channel:
            return
        await channel.send(line)

    # ------------------------------------------------------------
    # 2. Gestión de torneos
    # ------------------------------------------------------------

    async def crear_torneo(self, codigo: str, nombre: str, max_jugadores: int, nivel: str):
        """Crea los canales y registra el torneo en torneos-activos."""
        # Crear canales específicos del torneo
        for sufijo in ["participantes", "rondas", "clasificacion", "estado"]:
            channel_name = f"torneo-{codigo}-{sufijo}"
            if not await self._get_channel(channel_name):
                await self.guild.create_text_channel(channel_name)

        # Registrar en torneos-activos
        await self._append_line("torneos-activos", f"{codigo}|{nombre}|{max_jugadores}|{nivel}|0|0")
        # Estado: codigo|ronda_actual|jugadores_con_bye
        await self._write_lines(f"torneo-{codigo}-estado", [f"{codigo}|0|"])

    async def inscribir_jugador(self, codigo: str, user_id: int) -> bool:
        """Añade un jugador a la lista de participantes."""
        channel_name = f"torneo-{codigo}-participantes"
        lines = await self._read_lines(channel_name)
        if str(user_id) in lines:
            return False
        await self._append_line(channel_name, str(user_id))
        return True

    async def desinscribir_jugador(self, codigo: str, user_id: int) -> bool:
        channel_name = f"torneo-{codigo}-participantes"
        lines = await self._read_lines(channel_name)
        if str(user_id) not in lines:
            return False
        lines = [l for l in lines if l != str(user_id)]
        await self._write_lines(channel_name, lines)
        return True

    async def get_participantes(self, codigo: str) -> List[int]:
        lines = await self._read_lines(f"torneo-{codigo}-participantes")
        return [int(l) for l in lines if l.isdigit()]

    # ------------------------------------------------------------
    # 3. Algoritmo suizo
    # ------------------------------------------------------------

    async def generar_ronda(self, codigo: str, ronda_num: int):
        """
        Genera los emparejamientos para una ronda suiza.
        """
        participantes = await self.get_participantes(codigo)
        if len(participantes) < 2:
            return

        # Cargar historial de emparejamientos previos (para evitar repetidos)
        historial = await self._cargar_historial_emparejamientos(codigo)

        # Calcular puntuaciones actuales
        puntuaciones = await self._calcular_puntuaciones(codigo, ronda_num)

        # Ordenar participantes por puntuación descendente
        ordenados = sorted(puntuaciones.items(), key=lambda x: (-x[1], random.random()))

        # Emparejamiento Swiss
        emparejamientos = []
        usados = set()
        for i, (jugador, pts) in enumerate(ordenados):
            if jugador in usados:
                continue
            # Buscar oponente con misma puntuación o la más cercana, que no haya sido repetido
            oponente = self._buscar_oponente(jugador, ordenados, usados, historial, pts)
            if oponente:
                emparejamientos.append((jugador, oponente))
                usados.add(jugador)
                usados.add(oponente)
            else:
                # Bye
                emparejamientos.append((jugador, None))
                usados.add(jugador)

        # Guardar emparejamientos en el canal de rondas
        channel_name = f"torneo-{codigo}-rondas"
        mensaje = f"**Ronda {ronda_num}**\n"
        for p1, p2 in emparejamientos:
            if p2 is None:
                mensaje += f"{p1} → BYE\n"
            else:
                mensaje += f"{p1} vs {p2}\n"
        await self._append_line(channel_name, mensaje)

        # Actualizar estado
        await self._write_lines(f"torneo-{codigo}-estado", [f"{codigo}|{ronda_num}|"])

    def _buscar_oponente(self, jugador, ordenados, usados, historial, pts):
        """Busca el mejor oponente para un jugador."""
        # Buscar entre los que tienen la misma puntuación
        candidatos = [j for j, p in ordenados if j not in usados and j != jugador and abs(p - pts) <= 0.5]
        # Ordenar por menos enfrentamientos previos
        def prioridad(j):
            return historial.get(jugador, {}).get(j, 0)
        candidatos.sort(key=prioridad)
        if candidatos:
            return candidatos[0]
        # Si no, buscar el de menor puntuación posible
        candidatos = [j for j, p in ordenados if j not in usados and j != jugador]
        if candidatos:
            return min(candidatos, key=lambda j: (historial.get(jugador, {}).get(j, 0), -puntuaciones.get(j, 0)))
        return None

    async def _calcular_puntuaciones(self, codigo: str, ronda_actual: int) -> Dict[int, float]:
        """
        Calcula los puntos (MP) de cada jugador hasta la ronda anterior.
        """
        # Leer resultados de rondas anteriores
        channel = await self._get_channel(f"torneo-{codigo}-rondas")
        if not channel:
            return {}

        resultados = defaultdict(float)
        async for msg in channel.history(limit=100, oldest_first=True):
            if msg.author != self.bot.user:
                continue
            if "Ronda" not in msg.content:
                continue
            # Extraer ronda y resultados
            lines = msg.content.splitlines()
            for line in lines[1:]:  # Saltar el título
                if "BYE" in line:
                    p = line.split()[0]
                    resultados[int(p)] += 3.0
                    continue
                if " vs " in line:
                    p1, p2 = line.split(" vs ")
                    # Si hay resultado, se lee después, pero aquí solo contamos puntos
                    # Los puntos se añadirán cuando se reporte el resultado.
                    pass
        return resultados

    async def _cargar_historial_emparejamientos(self, codigo: str) -> Dict[int, Dict[int, int]]:
        historial = defaultdict(lambda: defaultdict(int))
        channel = await self._get_channel(f"torneo-{codigo}-rondas")
        if not channel:
            return historial

        async for msg in channel.history(limit=100, oldest_first=True):
            if msg.author != self.bot.user:
                continue
            if "Ronda" not in msg.content:
                continue
            lines = msg.content.splitlines()
            for line in lines[1:]:
                if " vs " in line:
                    p1, p2 = line.split(" vs ")
                    try:
                        p1 = int(p1.strip())
                        p2 = int(p2.strip())
                    except:
                        continue
                    historial[p1][p2] += 1
                    historial[p2][p1] += 1
        return historial

    # ------------------------------------------------------------
    # 4. Reporte de resultados
    # ------------------------------------------------------------

    async def reportar_resultado(self, codigo: str, jugador1: int, resultado: str, jugador2: int):
        """
        Registra el resultado de un partido en la ronda actual.
        """
        # Buscar el mensaje de la última ronda en el canal de rondas
        channel = await self._get_channel(f"torneo-{codigo}-rondas")
        if not channel:
            return False, "Canal de rondas no encontrado."

        # Localizar la última ronda no completada
        ronda_msg = None
        async for msg in channel.history(limit=10, oldest_first=False):
            if msg.author == self.bot.user and "Ronda" in msg.content:
                ronda_msg = msg
                break
        if not ronda_msg:
            return False, "No hay rondas activas."

        # Verificar si el partido existe en ese mensaje
        lines = ronda_msg.content.splitlines()
        encontrado = False
        nueva_lines = []
        for line in lines:
            if jugador1 in line and jugador2 in line:
                # Reemplazar con el resultado
                nueva_lines.append(line + f" → {resultado}")
                encontrado = True
            else:
                nueva_lines.append(line)
        if not encontrado:
            return False, "Ese partido no está en la ronda actual."

        # Actualizar el mensaje
        await ronda_msg.edit(content="\n".join(nueva_lines))

        # Verificar si todos los partidos de la ronda están reportados
        if await self._ronda_completa(codigo, ronda_msg):
            # Pasar a la siguiente ronda automáticamente
            await self._siguiente_ronda_automatica(codigo)

        return True, "Resultado reportado."

    async def _ronda_completa(self, codigo: str, ronda_msg: discord.Message) -> bool:
        lines = ronda_msg.content.splitlines()
        for line in lines[1:]:  # Saltar título
            if " vs " in line and "→" not in line:
                return False  # Hay partido sin reportar
        return True

    async def _siguiente_ronda_automatica(self, codigo: str):
        # Leer ronda actual del estado
        estado = await self._read_lines(f"torneo-{codigo}-estado")
        if not estado:
            return
        ronda_actual = int(estado[0].split("|")[1]) if "|" in estado[0] else 0
        nueva_ronda = ronda_actual + 1
        await self.generar_ronda(codigo, nueva_ronda)

    # ------------------------------------------------------------
    # 5. Clasificación final
    # ------------------------------------------------------------

    async def calcular_clasificacion(self, codigo: str):
        """
        Calcula la clasificación final del torneo.
        """
        # Leer todos los resultados de las rondas
        channel = await self._get_channel(f"torneo-{codigo}-rondas")
        if not channel:
            return

        # Recopilar datos por jugador
        stats = defaultdict(lambda: {
            "mp": 0.0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "opponents": [],
            "games_won": 0,
            "games_played": 0
        })

        async for msg in channel.history(limit=100, oldest_first=True):
            if msg.author != self.bot.user:
                continue
            if "Ronda" not in msg.content:
                continue
            lines = msg.content.splitlines()
            for line in lines[1:]:
                if "BYE" in line:
                    p1 = int(line.split()[0])
                    stats[p1]["mp"] += 3.0
                    stats[p1]["wins"] += 1
                    continue
                if " vs " in line and "→" in line:
                    part, res = line.split(" → ")
                    p1_str, p2_str = part.split(" vs ")
                    p1 = int(p1_str.strip())
                    p2 = int(p2_str.strip())
                    try:
                        s1, s2 = map(int, res.split("-"))
                    except:
                        continue
                    stats[p1]["opponents"].append(p2)
                    stats[p2]["opponents"].append(p1)
                    stats[p1]["games_won"] += s1
                    stats[p1]["games_played"] += s1 + s2
                    stats[p2]["games_won"] += s2
                    stats[p2]["games_played"] += s1 + s2
                    if s1 > s2:
                        stats[p1]["mp"] += 3.0
                        stats[p1]["wins"] += 1
                        stats[p2]["losses"] += 1
                    elif s2 > s1:
                        stats[p2]["mp"] += 3.0
                        stats[p2]["wins"] += 1
                        stats[p1]["losses"] += 1
                    else:
                        stats[p1]["mp"] += 1.0
                        stats[p2]["mp"] += 1.0
                        stats[p1]["draws"] += 1
                        stats[p2]["draws"] += 1

        # Calcular OMW y Buchholz
        for pid, data in stats.items():
            omw = 0.0
            buch = []
            for opp in data["opponents"]:
                opp_data = stats.get(opp)
                if opp_data:
                    total_matches = opp_data["wins"] + opp_data["losses"] + opp_data["draws"]
                    if total_matches > 0:
                        omw += opp_data["mp"] / (total_matches * 3)
                        buch.append(opp_data["mp"] / (total_matches * 3))
            data["omw"] = omw / len(data["opponents"]) if data["opponents"] else 0.0
            if buch:
                buch.sort()
                buch = buch[1:-1] if len(buch) > 2 else buch
                data["buchholz"] = sum(buch) / len(buch) if buch else 0.0
            else:
                data["buchholz"] = 0.0
            data["diff"] = data["games_won"] - (data["games_played"] - data["games_won"])

        # Ordenar
        ranking = sorted(stats.items(), key=lambda x: (-x[1]["mp"], -x[1]["omw"], -x[1]["diff"], -x[1]["buchholz"]))

        # Generar tabla
        lines = ["**Clasificación final**", "Rk | Jugador | Pts | W-L-D | OMW | Buchholz | Dif"]
        for i, (pid, data) in enumerate(ranking, 1):
            nombre = f"<@{pid}>"
            lines.append(f"{i:2} | {nombre:12} | {data['mp']:3.0f} | {data['wins']}-{data['losses']}-{data['draws']} | {data['omw']:.3f} | {data['buchholz']:.3f} | {data['diff']:+}")

        # Guardar en canal de clasificación
        await self._write_lines(f"torneo-{codigo}-clasificacion", lines)

        # También publicar en el canal de ranking
        canal_ranking = await self._get_channel("🍺-el‐ranking‐de‐la‐barra")
        if canal_ranking:
            await canal_ranking.send("\n".join(lines))

        return ranking