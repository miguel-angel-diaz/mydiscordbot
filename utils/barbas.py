######## barbas.py #######
"""
Qué hace el Barbas cuando le escriben en #preguntale-a-el-barbas algo que no es un comando.

Antes el texto libre y los comandos mal escritos (`!agendar`) se ignoraban sin decir nada, y la gente creía que
hablaba con un chat que no le contestaba. Ahora el mensaje se borra y el bot escribe por DM: se presenta, intenta
adivinar el comando (predecir) y, si acierta, lo lanza; si no, abre !mis-comandos.

- predecir(): lógica pura, de un texto a los comandos que más encajan.
- atender(): el flujo completo por DM.
"""
import asyncio
import difflib
import logging
import re
import time
from typing import Dict, List

import discord
from discord.ext.commands.view import StringView

from utils import ayuda, canales, dm
from utils.miembros import normalizar

log = logging.getLogger(__name__)

MAX_SUGERENCIAS = 3
ESPERA_ENTRE_AVISOS = 60          # segundos: alguien que escribe 5 mensajes seguidos recibe un solo saludo
TIMEOUT_RESPUESTA = 120

# Palabras (normalizadas: sin tildes ni mayúsculas) que delatan qué comando buscaba. Cuentan si una palabra del
# texto EMPIEZA así ("agend" vale para "agendar"), para que "cita" no salte con "necesita" ni "hora" con "ahora".
PISTAS: Dict[str, List[str]] = {
    "agendar-partida": ["agend", "quedar", "quedamos", "cita", "jugar contra", "fecha"],
    "modificar-agenda": ["cambiar la partida", "cambiar partida", "mover", "aplazar", "retrasar", "modificar agenda"],
    "reportar-swiss": ["resultado", "report", "gane", "perdi", "empate", "empatamos", "ganado", "perdido"],
    "subir-deck": ["deck", "mazo", "lista", "subir", "subo"],
    "editar-deck": ["editar", "edito", "deck", "mazo", "lista", "cambiar deck", "cambiar el deck", "cambiar lista"],
    "inscribir-swiss": ["inscrib", "apunt", "participar", "unirme", "torneo"],
    "desinscribir-swiss": ["desinscrib", "desapunt", "borrarme", "salirme", "darme de baja", "baja"],
    "clasificacion-swiss": ["clasificacion", "ranking", "puntos", "tabla", "como voy"],
    "partidos-pendientes": ["pendiente", "me toca", "rival", "contra quien", "emparejamiento"],
    "ver-inscritos": ["inscritos", "quien juega", "participantes", "cuantos somos"],
    "eventos-hoy": ["hoy", "eventos"],
    "inscribirse-sorteo": ["sorteo"],
    "nueva-peticion": ["peticion", "sugerencia", "propuesta", "queja", "idea"],
    "best-decks": ["mejores decks", "meta", "mejor deck"],
    "cartas-mas-jugadas": ["cartas"],
}

_ultimo_aviso: Dict[int, float] = {}
_atendiendo = set()


def _puntuar_pistas(texto: str, nombres: List[str]) -> Dict[str, int]:
    t = normalizar(texto)
    puntos = {}
    for nombre in nombres:
        aciertos = sum(1 for pista in PISTAS.get(nombre, []) if re.search(r"(?<!\w)" + re.escape(pista), t))
        if aciertos:
            puntos[nombre] = aciertos
    return puntos


def predecir(texto: str, comandos: List[dict]) -> List[dict]:
    """
    Hasta MAX_SUGERENCIAS comandos (de `comandos`, los que puede usar la persona) que encajan con el texto:
      - `!algo` mal escrito: los que empiezan igual o se le parecen (nombre o alias) van primero.
      - en cualquier caso, las PISTAS que aparecen en el texto, de más a menos aciertos.
    """
    por_nombre = {c["comando"]: c for c in comandos}
    candidatos: List[str] = []

    limpio = texto.strip()
    if limpio.startswith("!"):
        palabra = normalizar(limpio[1:].split()[0]) if limpio[1:].split() else ""
        if palabra:
            alias = {normalizar(a): c["comando"] for c in comandos for a in [c["comando"], *c.get("aliases", [])]}
            parecidos = [alias[a] for a in alias if a.startswith(palabra) or palabra.startswith(a)]
            parecidos += [alias[a] for a in difflib.get_close_matches(palabra, alias, n=MAX_SUGERENCIAS, cutoff=0.6)]
            candidatos += parecidos
        limpio = limpio[1:]

    puntos = _puntuar_pistas(limpio.replace("-", " ").replace("_", " "), list(por_nombre))
    candidatos += sorted(puntos, key=lambda n: (-puntos[n], list(por_nombre).index(n)))

    vistos = []
    for nombre in candidatos:
        if nombre not in vistos and nombre != "mis-comandos":
            vistos.append(nombre)
    return [por_nombre[n] for n in vistos[:MAX_SUGERENCIAS]]


def comandos_de(bot, miembro) -> List[dict]:
    """Comandos que la persona puede usar según sus roles (como !mis-comandos)."""
    roles = {r.name for r in miembro.roles}
    return [c for c in ayuda.comandos_info(bot) if roles & set(c["roles_permitidos"])]


def saludo(nombre: str) -> str:
    return (
        f"👋 ¡Hola, **{nombre}**! Soy **el Barbas**, el bot del servidor **The Klub**.\n"
        f"He visto que has intentado hablar conmigo en `#{canales.COMANDOS}`. No soy un chat: funciono con "
        f"**comandos** (empiezan por `!`), así que he borrado tu mensaje para que el canal quede limpio. "
        f"¡Pero te ayudo encantado!"
    )


async def _lanzar(bot, message: discord.Message, comando):
    """Ejecuta el comando como si la persona lo hubiera escrito en el canal (con sus comprobaciones de permisos)."""
    ctx = await bot.get_context(message)
    ctx.command, ctx.invoked_with = comando, comando.qualified_name
    ctx.view = StringView("")
    await bot.invoke(ctx)         # los errores van a on_command_error, como al escribirlo


async def _mis_comandos(bot, message: discord.Message):
    await _lanzar(bot, message, bot.get_command("mis-comandos"))


async def atender(bot, message: discord.Message):
    """Borra el mensaje y guía a la persona por DM hacia el comando que buscaba."""
    autor = message.author
    try:
        await message.delete()
    except discord.HTTPException:
        pass

    ahora = time.monotonic()
    if autor.id in _atendiendo or ahora - _ultimo_aviso.get(autor.id, 0) < ESPERA_ENTRE_AVISOS:
        return                    # ya tiene la conversación abierta por DM
    _ultimo_aviso[autor.id] = ahora
    _atendiendo.add(autor.id)
    try:
        await _guiar(bot, message)
    except discord.Forbidden:
        try:
            await message.channel.send(
                f"{autor.mention} 🤖 Soy el Barbas, el bot de **The Klub**: no soy un chat, funciono con comandos. "
                f"Escribe `!mis-comandos` para ver lo que puedo hacer (y abre tus DMs, que te escribo por privado).",
                delete_after=30)
        except discord.HTTPException:
            pass
    except asyncio.TimeoutError:
        await autor.send("⏰ Tiempo agotado. Cuando quieras, escribe `!mis-comandos` en el canal.")
    finally:
        _atendiendo.discard(autor.id)


async def _guiar(bot, message: discord.Message):
    autor = message.author
    sugerencias = predecir(message.content, comandos_de(bot, autor))
    await autor.send(saludo(autor.display_name))

    if not sugerencias:
        await autor.send("🤔 No tengo claro qué buscabas, así que te enseño todo lo que puedo hacer por ti:")
        await _mis_comandos(bot, message)
        return

    if len(sugerencias) == 1:
        c = sugerencias[0]
        await autor.send(f"💡 ¿Querías usar **`!{c['comando']}`**? — {c['descripcion']}\n\n"
                         f"Responde **sí** y lo lanzo ahora mismo, o **no** y te enseño todos los comandos.")
        respuesta = await dm.esperar_respuesta(bot, autor, TIMEOUT_RESPUESTA)
        elegido = c if dm.es_si(respuesta.content) else None
    else:
        lineas = "\n".join(f"**{i}.** `!{c['comando']}` — {c['descripcion']}" for i, c in enumerate(sugerencias, 1))
        await autor.send(f"💡 ¿Querías usar alguno de estos?\n{lineas}\n\n"
                         f"Responde con el **número** y lo lanzo, o **no** y te enseño todos los comandos.")
        respuesta = await dm.esperar_respuesta(bot, autor, TIMEOUT_RESPUESTA)
        indice = dm.indice_elegido(respuesta.content, len(sugerencias))
        elegido = sugerencias[indice] if indice is not None else None

    if dm.es_cancelar(respuesta.content):
        await autor.send("👌 Vale. Cuando quieras, escribe `!mis-comandos` en el canal.")
        return
    if elegido is None:
        await _mis_comandos(bot, message)
        return
    await autor.send(f"🚀 ¡Vamos con `!{elegido['comando']}`! La próxima vez puedes escribirlo tú directamente "
                     f"en `#{canales.COMANDOS}`.")
    await _lanzar(bot, message, bot.get_command(elegido["comando"]))
