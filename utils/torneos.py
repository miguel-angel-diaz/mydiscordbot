import discord
from discord.ext import commands
from datetime import datetime
import random
import string
import re

from utils.admin import moderador_permisos_handle

from utils.resultados import extraer_partidas, calcular_clasificacion, generar_embed_clasificacion, guardar_resultado


RONDAS_SUIZO = [
    (4, 2), (8, 3), (16, 4), (32, 5), (64, 6),
    (128, 7), (226, 8), (409, 9), (819, 10), (9999, 11)
]



def generar_codigo_unico(longitud=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=longitud))

async def asignar_strike_automatico(ctx):
    rol = discord.utils.get(ctx.guild.roles, name="Strike")
    if rol and rol not in ctx.author.roles:
        await ctx.author.add_roles(rol)
        await ctx.send(f"⚠️ {ctx.author.mention} ha recibido el rol **Strike** por intentar ejecutar un comando sin permisos.")

async def nuevo_torneo_handle(ctx, datos):
    if not await moderador_permisos_handle(ctx):
        return

    if ctx.channel.name != "anuncios-torneos":
        await ctx.send("❌ Este comando solo se puede usar en el canal #anuncios-torneos.")
        return

    if datos is None:
        await ctx.send(
            "❌ Debes ingresar los datos con el formato:\n"
            "`!nuevo-torneo Evento | tipo | jugadores | dd/mm/yyyy | acceso`\n"
            "Ejemplo: `!nuevo-torneo Liga Legacy | classic-legacy-suizo | 16 | 20/08/2025 | Socio`"
        )
        return

    partes = [p.strip() for p in datos.split("|")]
    if len(partes) != 5:
        await ctx.send(
            "❌ Formato incorrecto. Usa:\n"
            "`!nuevo-torneo Evento | tipo | jugadores | dd/mm/yyyy | acceso`\n"
            "Acceso permitido: `Miembro`, `Socio`, o `Todos`"
        )
        return

    evento, tipo, jugadores_str, fecha_limite, acceso = partes
    errores = []

    tipos_validos = ["premodern-suizo", "7pts-suizo", "classic-legacy-suizo", "premodern-bondage-suizo"]
    accesos_validos = ["Miembro", "Socio", "Todos"]

    if tipo not in tipos_validos:
        errores.append(f"• Tipo inválido (`{tipo}`). Tipos permitidos: {', '.join(tipos_validos)}")

    if acceso not in accesos_validos:
        errores.append(f"• Acceso inválido (`{acceso}`). Opciones válidas: {', '.join(accesos_validos)}")

    if not jugadores_str.isdigit() or int(jugadores_str) <= 0:
        errores.append("• El campo `jugadores` debe ser un número entero mayor a 0.")

    try:
        fecha_obj = datetime.strptime(fecha_limite, "%d/%m/%Y")
        if fecha_obj.date() <= datetime.now().date():
            errores.append("• La `fecha_límite` debe ser posterior al día de hoy.")
    except ValueError:
        errores.append("• Formato de `fecha_límite` inválido. Usa `dd/mm/yyyy`.")

    if errores:
        await ctx.send("❌ Errores en tu comando:\n" + "\n".join(errores))
        return

    # Strike si no tiene el rol
    rol_moderador = discord.utils.get(ctx.guild.roles, name="Moderador")
    if rol_moderador not in ctx.author.roles:
        await asignar_strike_automatico(ctx)
        return

    canal = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    if not canal:
        await ctx.send("❌ No se encontró el canal #torneos-activos.")
        return

    # Verifica duplicado
    async for m in canal.history(limit=100):
        if evento in m.content and fecha_limite in m.content:
            await ctx.send("⚠️ Ya existe un torneo con ese nombre y fecha.")
            return

    codigo = generar_codigo_unico()
    mensaje = (
        f"`{evento}` `{fecha_limite}` | `{jugadores_str}` | `{tipo}` | `{acceso}` | "
        f"código: `{codigo}` creado por {ctx.author.mention}"
    )
    await canal.send(mensaje)
    await ctx.send(f"✅ Torneo creado correctamente con código `{codigo}` y acceso `{acceso}`.")

async def comenzar_evento_handle(ctx, codigo):
    if not await moderador_permisos_handle(ctx):
        return
    
    if not codigo:
        await ctx.send("❌ Indica el código del torneo. Ej: `!empezar-torneo ABC123`")
        return

    codigo = codigo.upper()

    canal_torneos = discord.utils.get(ctx.guild.text_channels, name="torneos-activos")
    canal_iniciados = discord.utils.get(ctx.guild.text_channels, name="torneos-iniciados")
    if not canal_torneos or not canal_iniciados:
        await ctx.send("❌ No se encontraron los canales necesarios.")
        return

    # ✅ Verificar si ya fue iniciado leyendo #torneos-iniciados
    async for m in canal_iniciados.history(limit=100):
        if f"`{codigo}`" in m.content:
            await ctx.send("⚠️ El torneo ya ha sido iniciado anteriormente.")
            return

    # 🔍 Buscar el torneo en torneos-activos
    patron = re.compile(r"`(.+?)` `(\d{2}/\d{2}/\d{4})` \| `(\d+)` \| `(.+?)` \| código: `(\w{6})`")
    mensaje_torneo = None
    torneo = None

    async for msg in canal_torneos.history(limit=100):
        m = patron.search(msg.content)
        if m and m.group(5).upper() == codigo:
            torneo = {
                "nombre": m.group(1),
                "fecha": m.group(2),
                "jugadores": m.group(3),
                "tipo": m.group(4),
                "codigo": m.group(5)
            }
            mensaje_torneo = msg
            break

    if not torneo:
        await ctx.send("❌ No se encontró el torneo con ese código.")
        return

    # ▶️ Iniciar la primera ronda
    await nueva_ronda_handle(ctx, codigo)

    # 📝 Registrar en torneos-iniciados
    iniciado_txt = (
        f"Torneo `{torneo['nombre']}` (`{torneo['codigo']}`) iniciado el {datetime.now().strftime('%d/%m/%Y')} "
        f"con {torneo['jugadores']} jugadores. Tipo: {torneo['tipo']}"
    )
    await canal_iniciados.send(iniciado_txt)

    # 🧹 Eliminar mensaje de torneos-activos
    if mensaje_torneo:
        await mensaje_torneo.delete()

    await ctx.send(f"✅ Torneo `{torneo['nombre']}` iniciado correctamente.")



async def nueva_ronda_handle(ctx, codigo, empatar_faltantes=0):
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"[ERROR al borrar mensaje]: {e}")

    if not codigo:
        await ctx.send("❌ Indica el código del torneo.")
        return

    codigo = codigo.upper()
    canal_resultados = discord.utils.get(ctx.guild.text_channels, name="resultados-de-partidas")
    canal_emparejamientos = discord.utils.get(ctx.guild.text_channels, name="emparejamientos")
    canal_inscritos = discord.utils.get(ctx.guild.text_channels, name="inscritos-en-torneos")

    if not canal_resultados or not canal_emparejamientos or not canal_inscritos:
        await ctx.send("❌ Faltan canales necesarios.")
        return

    # 📌 Extraer IDs de los inscritos con el nuevo formato plano
    patron = re.compile(
        r"🎟️ Inscrito #\d+ \| .+? \(`" + re.escape(codigo) + r"`\) \| <@!?(\d+)>"
    )
    jugadores = set()
    async for m in canal_inscritos.history(limit=200):
        if f"(`{codigo}`)" in m.content:
            match = patron.search(m.content)
            if match:
                nombre_discord = match.group(1).strip()
                miembro = discord.utils.find(
                    lambda u: u.name == nombre_discord or (u.nick and u.nick == nombre_discord),
                    ctx.guild.members
                )
                if miembro:
                    jugadores.add(miembro.id)

    if len(jugadores) < 2:
        await ctx.send("⚠️ No hay suficientes jugadores.")
        return

    def rondas_maximas(num):
        return next((r for l, r in RONDAS_SUIZO if num <= l), 11)

    async def contar_rondas_previas():
        c = 0
        async for m in canal_emparejamientos.history(limit=200):
            if f"`{codigo}`" in m.content:
                c += 1
        return c

    ronda_actual = await contar_rondas_previas()
    if ronda_actual >= rondas_maximas(len(jugadores)):
        await ctx.send("🏁 El torneo ya finalizó.")
        return

    # Verificar si ya hay emparejamientos para esta ronda
    emparejados = []
    async for m in canal_emparejamientos.history(limit=100):
        if f"Ronda {ronda_actual}" in m.content and f"`{codigo}`" in m.content:
            emparejados += [(int(a), int(b)) for a, b in re.findall(r"<@!?(\d+)> vs <@!?(\d+)>", m.content)]
            break

    resultados = await extraer_partidas(canal_resultados, codigo)
    jugadas = {(p["jugador1"], p["jugador2"]) for p in resultados}
    jugadas |= {(p["jugador2"], p["jugador1"]) for p in resultados}

    no_reportadas = [m for m in emparejados if m not in jugadas]

    if no_reportadas and not empatar_faltantes:
        faltantes = "\n".join(f"<@{a}> vs <@{b}>" for a, b in no_reportadas)
        await ctx.send(f"❌ Partidas no reportadas:\n{faltantes}\nUsa `!nueva-ronda {codigo} 1` para contarlas como empate.")
        return

    if empatar_faltantes:
        for a, b in no_reportadas:
            await guardar_resultado(ctx, canal_resultados, ctx.guild.get_member(a), "1-1", ctx.guild.get_member(b), codigo)

    resultados = await extraer_partidas(canal_resultados, codigo)
    clasificacion = calcular_clasificacion(resultados, ctx.guild)
    ids_ordenados = [
        ctx.guild.get_member_named(p["jugador"]).id
        for p in clasificacion
        if ctx.guild.get_member_named(p["jugador"])
    ]

    usados = set()
    nuevos = []

    for i in range(len(ids_ordenados)):
        if ids_ordenados[i] in usados:
            continue
        for j in range(i + 1, len(ids_ordenados)):
            if ids_ordenados[j] in usados:
                continue
            if (ids_ordenados[i], ids_ordenados[j]) not in jugadas and (ids_ordenados[j], ids_ordenados[i]) not in jugadas:
                nuevos.append((ids_ordenados[i], ids_ordenados[j]))
                usados.add(ids_ordenados[i])
                usados.add(ids_ordenados[j])
                break

    mensaje = f"🎯 Emparejamientos Ronda {ronda_actual + 1} - Torneo `{codigo}`\n"
    for i, (a, b) in enumerate(nuevos, start=1):
        mensaje += f"Match #{i}\n<@{a}> vs <@{b}>\n"

    if len(usados) % 2 != 0:
        restantes = [i for i in ids_ordenados if i not in usados]
        if restantes:
            mensaje += f"Bye\n<@{restantes[0]}> descansa esta ronda\n"

    await canal_emparejamientos.send(mensaje)
    await ctx.send(f"✅ Ronda {ronda_actual + 1} generada correctamente.")



async def extraer_partidas(canal, codigo):
    patron = re.compile(r"<@!?(\d+)>\s*\*\*(\d+)-(\d+)\*\*\s*<@!?(\d+)>")
    partidas = []

    async for mensaje in canal.history(limit=500):
        if f"`{codigo}`" not in mensaje.content:
            continue
        match = patron.search(mensaje.content)
        if not match:
            continue
        p1_id, g1, g2, p2_id = match.groups()
        partidas.append({
            "jugador1": int(p1_id),
            "jugador2": int(p2_id),
            "g1": int(g1),
            "g2": int(g2)
        })
    return partidas

async def mostrar_clasificacion_handle(ctx, codigo):
    if not await moderador_permisos_handle(ctx):
        return
    if not codigo:
        await ctx.send("❌ Indica el código del torneo.")
        return

    codigo = codigo.upper()
    canal_resultados = discord.utils.get(ctx.guild.text_channels, name="resultados-de-partidas")
    canal_clasificacion = discord.utils.get(ctx.guild.text_channels, name="clasificaciones")

    partidas = await extraer_partidas(canal_resultados, codigo)
    if not partidas:
        await ctx.send("⚠️ No hay partidas registradas para este torneo.")
        return

    clasificacion = calcular_clasificacion(partidas, ctx.guild)
    embed = generar_embed_clasificacion(clasificacion, codigo)
    await canal_clasificacion.send(embed=embed)
    await ctx.send("📊 Clasificación actualizada.")

def calcular_mwp(pid, partidas):
    total = sum(1 for p in partidas if pid in [p["jugador1"], p["jugador2"]])
    wins = sum(1 for p in partidas if (p["jugador1"] == pid and p["g1"] > p["g2"]) or (p["jugador2"] == pid and p["g2"] > p["g1"]))
    draws = sum(1 for p in partidas if pid in [p["jugador1"], p["jugador2"]] and p["g1"] == p["g2"])
    if total == 0:
        return 0.33
    return max((wins + draws * 0.5) / total, 0.33)

def calcular_clasificacion(partidas, guild):
    puntos, juegos, oponentes = {}, {}, {}

    for p in partidas:
        j1, j2, g1, g2 = p["jugador1"], p["jugador2"], p["g1"], p["g2"]
        for j in (j1, j2):
            puntos.setdefault(j, 0)
            juegos.setdefault(j, [0, 0])
            oponentes.setdefault(j, set())

        if g1 > g2:
            puntos[j1] += 3
        elif g2 > g1:
            puntos[j2] += 3
        else:
            puntos[j1] += 1
            puntos[j2] += 1

        juegos[j1][0] += g1
        juegos[j1][1] += g1 + g2
        juegos[j2][0] += g2
        juegos[j2][1] += g1 + g2

        oponentes[j1].add(j2)
        oponentes[j2].add(j1)

    def calc_omwp(pid):
        opps = oponentes.get(pid, [])
        if not opps:
            return 0.33
        return max(sum(calcular_mwp(opp, partidas) for opp in opps) / len(opps), 0.33)

    clasificacion = []
    for j in puntos.keys():
        miembro = guild.get_member(j)
        nombre = miembro.display_name if miembro else f"<@{j}>"
        mwp = calcular_mwp(j, partidas)
        omwp = calc_omwp(j)
        gw, gt = juegos[j]
        gwp = gw / gt if gt else 0

        # Conteo de resultados
        wins = sum(1 for p in partidas if (p["jugador1"] == j and p["g1"] > p["g2"]) or (p["jugador2"] == j and p["g2"] > p["g1"]))
        losses = sum(1 for p in partidas if (p["jugador1"] == j and p["g1"] < p["g2"]) or (p["jugador2"] == j and p["g2"] < p["g1"]))
        draws = sum(1 for p in partidas if (p["jugador1"] == j or p["jugador2"] == j) and p["g1"] == p["g2"])

        clasificacion.append({
            "jugador": nombre,
            "puntos": puntos[j],
            "MWP": mwp,
            "OMWP": omwp,
            "GWP": gwp,
            "victorias": wins,
            "derrotas": losses,
            "empates": draws
        })

    clasificacion.sort(key=lambda x: (x["puntos"], x["OMWP"], x["MWP"]), reverse=True)
    return clasificacion

def generar_embed_clasificacion(clasificacion, codigo):
    embed = discord.Embed(title=f"📈 Clasificación torneo `{codigo}`", color=discord.Color.gold())
    descripcion = ""
    for i, j in enumerate(clasificacion, 1):
        descripcion += (
            f"**#{i}** - {j['jugador']} | "
            f"🏆 {j['puntos']} pts | "
            f"✅ {j['victorias']}V ❌ {j['derrotas']}D 🤝 {j['empates']}E | "
            f"🎯 {j['MWP']:.2%} MWP | "
            f"🤝 {j['OMWP']:.2%} OMWP | "
            f"🎮 {j['GWP']:.2%} GWP\n"
        )
    embed.description = descripcion
    return embed

async def guardar_resultado(ctx, canal_resultados, jugador1, resultado, jugador2, codigo):
    await canal_resultados.send(
        f"📊 Resultado registrado en torneo `{codigo}`:\n"
        f"{jugador1.mention} **{resultado}** {jugador2.mention}"
    )

def rondas_maximas(num_jugadores):
    for limite, rondas in RONDAS_SUIZO:
        if num_jugadores <= limite:
            return rondas
    return 11