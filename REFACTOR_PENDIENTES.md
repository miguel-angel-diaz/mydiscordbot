# Refactor y correcciones pendientes

Revisión completa del proyecto (octubre 2026). Se trabaja **una tarea cada vez**, marcando `[x]` al terminar.
✔ = verificado leyendo el código. Las líneas son aproximadas y pueden moverse según avancen los cambios.

Ya hecho: `utils/watchers.py` refactorizado, `tzdata` en requirements, `.python-version` 3.11.

---

## Fase 1 · Seguridad y permisos

- [x] **1.** ✔ `!partidos-pendientes` (lo puede usar cualquier miembro) llama a `finalizar_torneo_handle` cuando no quedan partidos, y ese handler no comprueba permisos: cierra Challonge, borra el estado y envía `@everyone`. → `utils/torneos.py:773`, `utils/torneos.py:918`
- [x] **2.** ✔ `!actualizar-web` no comprueba permisos. → `main.py:370`, `utils/admin.py:863` (también se ha quitado el `listar_torneos_handle` duplicado sin permisos)
- [x] **3.** `comando_roles_permitidos` solo hace `setattr` y ningún código comprueba los roles. → `main.py:196-308` (ahora es un `commands.check` real: dueño/admin siempre pasan, Out/Strike bloqueados; también protege `actualizar-clasificacion` y `-battle`)
- [x] **3b.** Los comandos de jugador del suizo (`inscribir-swiss`, `desinscribir-swiss`, `reportar-swiss`, `clasificacion-swiss`) no llevan `@comando_roles_permitidos`, así que los sancionados y la gente sin rol pueden usarlos. → `main.py`
- [x] **4.** `api_deck_rival`: cualquier inscrito puede ver el deck de cualquier jugador. → `utils/torneos_api.py:1667` (solo devuelve el deck de rivales ya jugados con resultado reportado; si no, `{"deck": null}` con 200. `obtener_deck_en_canal` compara ahora el código exacto)
- [x] **5.** Login por código: no hay límite de intentos (se puede forzar por fuerza bruta), `codigos_pendientes` nunca se purga y se pueden enumerar usuarios. → `utils/torneos_api.py:303-398` (código de 8 caracteres con mayúscula y especial, 3 intentos y bloqueo de 15 min con aviso por DM, un solo código activo por usuario y purga en cada petición. La enumeración se ha dejado igual a propósito, por usabilidad)
- [x] **6.** El token JWT viaja en la query string (`?session=`), acaba en los logs y dura 7 días sin poder revocarse. Habría que pasarlo a la cabecera `Authorization` (requiere cambiar la web). → `utils/torneos_api.py` (el backend acepta `Authorization: Bearer` + `session` por compatibilidad, responde al preflight OPTIONS en todas las rutas y el log de accesos ya no incluye la query)
  - [ ] **6b.** Web: enviar el token en `Authorization: Bearer <token>` en lugar de `?session=` / `session` en el body. Cuando esté migrada, quitar la compatibilidad en `obtener_token()`.
  - [ ] **6c.** (Opcional) Duración de la sesión (7 días) y forma de revocarla (p. ej. logout o versión de token por usuario).
- [x] **7.** `api_agendar_partida`: fecha y hora sin validar (permite `@everyone`, saltos de línea y eventos falsos), no comprueba que j1 y j2 sean rivales, y `username` siempre vale "Usuario". → `utils/torneos_api.py:1789-1825` (fecha y hora validadas, solo se mencionan los dos jugadores, se comprueba que sean rivales y "Agendado por" muestra a quien agenda)
  - [x] **7b.** Validación de TODAS las entradas de la web (`utils/validacion_web.py`): textos sin caracteres de control y con menciones neutralizadas, longitudes máximas, códigos de torneo `[A-Za-z0-9]`, IDs de Discord, fechas y horas, resultados, cuerpo JSON como objeto y de 64 KB como máximo, y límite de peticiones por IP (general 120/min, POST 20/min, solicitar-acceso 3/h, solicitar-codigo 5/10 min, verificar-codigo 15/10 min y agendar 10/10 min).
- [-] **8.** (Descartado por decisión del usuario: se deja como está) `JWT_SECRET` se escribe en los logs, `.jwt_secret` se regenera en cada deploy de Railway y el fallback a `config_token` es código muerto. → `config.py:7-52`
- [x] **9.** El middleware convierte los 404/405 en 500 y devuelve `str(e)` al cliente (unos 10 handlers hacen lo mismo). → `utils/torneos_api.py:55-65` (los errores HTTP mantienen su código y los 500/503 responden un mensaje genérico, con el traceback en los logs mediante `_error_interno()`)
- [x] **10.** CORS `*` en todas las rutas, con cabeceras repetidas en unos 15 handlers. → `utils/torneos_api.py:62` (solo `https://theklubmtg.es`, `https://www.theklubmtg.es` y `null` (file://); configurable con la variable de entorno `CORS_ORIGENES`. Se han quitado las 14 cabeceras `*` de los handlers)
- [x] **11.** (Solo se consulta Challonge para torneos del estado o de la caché; si no, `{"rondas": []}`. Escritura de la caché atómica) `api_torneo_enfrentamientos` acepta cualquier código de torneo y lo escribe en el caché, lo que contamina `/api/torneos`. → `utils/torneos_api.py:1445-1580`
- [x] **12.** `swiss_inscribir_asistente_handle` permite a cualquiera inscribir a otro usuario. → `utils/swiss_handle.py:152-159` (solo los admins pueden inscribir a otros; el resto se inscribe a sí mismo sin pregunta. Se aceptan menciones y se rechazan IDs que no son del servidor)
  - [x] **12b.** Si un admin inscribe a otro y este responde "sí" a subir el deck, `submitted_deck_handle(ctx, …)` abre el asistente con el admin (`ctx.author`) en lugar del jugador. → `utils/swiss_handle.py` (resuelto: al inscrito por un admin ya no se le pregunta por el deck, solo recibe un aviso)
- [x] **13.** (Ahora solo admins: decorador `admin` en `main.py` y `roles_permitidos` actualizado en `config.py`) `iniciar_battle_handle` no comprueba permisos ni canal y compara IDs como subcadenas. → `utils/jugadores.py:2134, 2217-2231`
- [x] **14.** (El core rechaza inscribirse o desinscribirse si el estado no es "abierto"; el menú de `!desinscribir-swiss` solo muestra los abiertos. También estaba abierto en Discord) `inscribir_jugador` y `desinscribir_jugador` no comprueban que el torneo esté en estado "abierto", así que desde la web se puede entrar o salir con el torneo en marcha. → `utils/swiss_core.py:65-94`
- [x] **15.** Revisar los permisos de `!sincronizar-estado` (operación destructiva). → `main.py:378`, `utils/torneos_estado.py:253` (comprobado: ya tiene `@commands.has_permissions(administrator=True)`, no requiere cambios)
- [x] **16.** (No se puede sancionar a bots, al dueño, a admins ni a uno mismo; los comandos de admin por DM responden "solo en el servidor"; `moderador_permisos_handle` acepta también el permiso de administrador) `!strike` y `!out` no impiden sancionar a admins, al owner o a bots, y los comandos de admin no son `guild_only`. → `utils/admin.py:11-153, 475`

## Fase 2 · Bugs funcionales

### Sistema suizo
- [x] **17.** ✔ La API compara `miembro.id` (int) con IDs str del JSON, así que un jugador normal recibe 403 al reportar, modificar o eliminar. → `utils/torneos_api.py:1199, 1878, 1980` (resuelto con 7b: los IDs se validan y convierten a int)
- [ ] **18.** ✔ Si un jugador se retira, `_calcular_stats_completos` da `KeyError` y rompe reportes y rondas. Además su partido pendiente nunca se resuelve. → `utils/swiss_core.py:84-94, 235`
- [ ] **19.** Modificar un BYE (j2=None) corrompe la clasificación. → `utils/swiss_handle.py:1218-1250`
- [ ] **20.** (Web ya resuelta en 7b: `^[0-3]-[0-3]$`; falta el handler de Discord y el core) El resultado no se valida (solo se comprueba `"-" in`): "a-b" o "5-0" cuentan como reportados pero valen 0 puntos. Hace falta un parser único. → handler, core y API
- [ ] **21.** `generar_ronda` no comprueba si la ronda anterior está completa ni si el torneo ha terminado, y los partidos de la ronda anterior quedan huérfanos. → `utils/swiss_core.py:155`, `utils/swiss_handle.py:703-753`
- [ ] **22.** Al modificar un resultado no se avisa del efecto en las rondas posteriores, los torneos finalizados no se pueden corregir y `eliminar_ronda_swiss` no renumera las rondas ni reabre el torneo. → `utils/swiss_handle.py:1183, 1298`, `utils/swiss_core.py:559-566`
- [ ] **23.** La clasificación final se publica sin la última ronda y además se publica dos veces. `swiss_finalizar` no recalcula. → `utils/swiss_core.py:371-377, 594-599`, `utils/swiss_handle.py:627, 1152`
- [ ] **24.** Hay dos fórmulas de OMW (una incluye el bye en el divisor y la otra no, y puede salir >1). Faltan el suelo de 1/3 y un desempate final determinista, y la ronda 1 no se aleatoriza. → `utils/swiss_core.py:274, 501-514`
- [ ] **25.** Emparejamiento: el bye puede repetirse, el jugador que flota se elige antes de comprobar que el resto se puede emparejar y, si falla un emparejamiento, se permiten revanchas en todo el grupo. → `utils/swiss_core.py:781-802`
- [ ] **26.** `swiss_iniciar`: `borrar_mensaje_seguro` se llama dos veces, "eliminar" no borra el deck del jugador y la ronda se genera antes de cambiar el estado. → `utils/swiss_handle.py:305, 426-431`
- [ ] **27.** Al desinscribirse, el deck se borra dos veces (en el core y en el handler). → `utils/swiss_core.py:96-137`, `utils/swiss_handle.py:283-293`

### Decks
- [ ] **28.** ✔ El bloqueo de edición no funciona: se busca `"📅 Inicio:"` pero el mensaje dice `"📅 **Inicio:**"`. Lo mismo pasa con Nivel, Jugadores y Código. → `utils/commons.py:982-989, 883`
- [ ] **29.** `editar_deck_web` ignora `ok_validacion`. → `utils/commons.py:1357`
- [ ] **30.** `editar_deck_handle` decide si sigue según el texto del mensaje de error. → `utils/jugadores.py:1868`
- [ ] **31.** Los nombres de los campos del embed no coinciden ("edited", "Ediciones post-inicio", "Ediciones"), así que el contador de ediciones siempre vale 0. → `utils/jugadores.py:1830, 1994, 2103`, `utils/commons.py:1387`
- [ ] **32.** El sideboard no se valida al subir el deck (sí al editarlo) y se descarta la respuesta de texto. → `utils/jugadores.py:1593, 1611`
- [ ] **33.** Los textos se recortan a `[:1000]` sin avisar. → `utils/jugadores.py:1828`, `utils/commons.py:1385`

### Torneos Challonge / Battle Royale / web
- [ ] **34.** ✔ Battle Royale usa `url_challonge`, que no está definida (`NameError` silencioso), así que el torneo nunca se guarda en el estado. Además guarda `tipo: "challonge"`. → `utils/torneos.py:173`
- [ ] **35.** `/api/torneos` llama a `calcular_clasificacion` con argumentos equivocados, por lo que los suizos finalizados no aparecen en la web. → `utils/torneos_api.py:190`
- [ ] **36.** `torneos.py:827` hace `replace(x, x)`, así que en el DM el jugador 2 ve su propio nombre como rival.
- [ ] **37.** `calcular_clasificacion_torneo`: `discord_id_resuelto` puede quedar sin definir o arrastrar el valor del jugador anterior. → `utils/commons.py:838-850`
- [ ] **38.** `!cartas-mas-jugadas` y `!best-decks` fallan siempre (`UnboundLocalError`) y hay un `return` dentro del bucle. → `utils/commons.py:304-533`

### Admin / eventos
- [x] **39.** (Resuelto con el 16: helper `_obtener_objetivo_sancion` común, que corta con timeout o DMs cerrados, acepta menciones y rechaza los SimpleNamespace) `!strike` y `!out` siguen ejecutándose tras un timeout, hacen `raise e` y pueden recibir un `SimpleNamespace` en lugar de un miembro. El texto de `out` dice "strike". → `utils/admin.py:35-112`
- [ ] **40.** `eliminar_decks` filtra por subcadena (puede borrar decks de otro torneo) y la opción "todos" no pide confirmación. → `utils/admin.py:777, 842`
- [ ] **41.** El canal de anuncios se busca por un ID fijo sin comprobar si existe. Si no está, el sorteo ya ha notificado y vaciado el canal. → `utils/admin.py:588, 710`
- [ ] **42.** `📰-tablon-anuncios` usa un guion ASCII y el resto del proyecto usa U+2010, así que probablemente no encuentra el canal. → `utils/admin.py:540`
- [ ] **43.** `cerrar_peticion` falla si `embed.description` o `footer.text` valen None. → `utils/admin.py:347-349`
- [ ] **44.** `!limpiar antiguos` borra 1.000 mensajes uno a uno (unos 8 minutos) sin confirmación y tiene un `except Forbidden` duplicado. → `utils/admin.py:206-260`
- [ ] **45.** `inscribirse_sorteo`: la comprobación de duplicados nunca coincide (te puedes inscribir varias veces) y el contador falla a partir de 10. → `utils/jugadores.py:1285-1313`
- [ ] **46.** `on_command_error` se traga los errores: no hay traceback ni aviso al usuario. → `main.py:494-510`
- [ ] **47.** `on_ready` arranca otra vez el servidor web en cada reconexión y la task no se guarda. → `main.py:449-452`
- [ ] **48.** Los embeds de logs superan los límites de Discord (1024/4096) y se pierden. → `utils/events.py:35-38, 163, 346`
- [ ] **49.** Bienvenida: si fallan los DMs, se omite el registro, `castigar_usuario` no captura `Forbidden` y los roles se quitan antes de comprobar la blacklist. → `utils/events.py:76, 144-177, 319`
- [ ] **50.** `validar_canal_correcto` usa `ctx.channel.name` antes de comprobar que `ctx.guild` no es None, y hay un `"!mis-comandos"` copiado por error. → `utils/jugadores.py:1782, 1840`

## Fase 3 · Base común, concurrencia y persistencia

- [ ] **51.** `asyncio.Lock` por torneo en todas las operaciones de leer-modificar-escribir (estado, rondas, inscripciones, reportes y ediciones de deck). → `utils/torneos_estado.py`, `utils/swiss_core.py`
- [ ] **52.** `inscribir_usuario_web` guarda TODO el estado con datos viejos, y `guardar_estado` borra los torneos que no vienen en la lista. → `utils/commons.py:1200-1217`, `utils/torneos_estado.py:180`
- [ ] **53.** Persistencia en mensajes: `history(limit=200)` pierde el estado sin avisar, el troceado no es atómico y los `except:` desnudos ocultan JSON corrupto. → `utils/torneos_estado.py`
- [ ] **54.** El caché web (`cache/torneos.json`) se pierde en cada deploy, usa `open()` síncrono y no se escribe de forma atómica. → `utils/torneos_api.py:152-167, 1578`
- [ ] **55.** `utils/canales.py`: constantes con IDs y nombres de canal y rol, más `get_canal()` (hoy hay 112 búsquedas por nombre).
- [ ] **56.** `utils/dm.py`: `preguntar_dm()`, `elegir_torneo()` y `confirmar()` (hoy hay 45 `dm_check` y 111 `wait_for`).
- [ ] **57.** `utils/challonge.py`: un cliente con una sola sesión, timeout y autenticación (hoy hay 28 `ClientSession`).
- [ ] **58.** `utils/decks.py`: construir, leer, buscar y validar el embed de un deck (hoy hay 6 versiones del embed y 4 búsquedas distintas).
- [ ] **59.** Un `parsear_codigo()` único, y leer los torneos del estado en lugar de parsear `#torneos-activos` (hoy hay 3 o 4 parsers distintos).
- [ ] **60.** `resolver_miembro()` que use antes `get_member` y luego `fetch_member` con caché (hoy hay N+1 llamadas a la API de Discord).
- [ ] **61.** matplotlib bloquea el event loop; hay que ejecutarlo en un executor. → `utils/commons.py:373-391`
- [ ] **62.** Usar `logging` en lugar de `print` y quitar los `except:` desnudos de todo el proyecto.
- [ ] **63.** Validación del deck compartida entre la API y los comandos. → `utils/torneos_api.py:628-668, 874-900`

## Fase 4 · Reorganización

- [ ] **64.** Pasar `main.py` a Cogs (Admin, Jugadores, Swiss, Eventos) con permisos en `cog_check` y carga en `setup_hook`.
- [ ] **65.** Separar el suizo en `engine.py` (lógica pura con tests), `service.py` (locks) y `presentacion.py`, con una única fuente de estadísticas.
- [ ] **66.** Convertir `torneos_api.py` en un paquete `api/` (auth, torneos, decks, partidas, contenido, routes) con el decorador `@requiere_sesion`.
- [ ] **67.** Capa de servicios compartida entre comandos y API (inscribir, reportar, subir y editar deck).
- [ ] **68.** `config.py`: mover los datos (COMANDOS_INFO, arquetipos, blacklist) a JSON, no exigir `OPENROUTER_API_KEY` al importar y generar COMANDOS_INFO desde los comandos.
- [ ] **69.** `events.py`: generar el mapa de aliases desde `bot.walk_commands()` y usar `bot.invoke` en lugar de `ctx.invoke` (que se salta las comprobaciones).
- [ ] **70.** Partir las funciones gigantes: `deck_dm_flow`, `iniciar_torneo_handle`, `bienvenida_y_comandos_handle`, `api_torneo_enfrentamientos` y `member_join_handle`, y unificar `strike` y `out`.

## Fase 5 · Limpieza

- [ ] **71.** Handlers que ningún comando registra en `jugadores.py`: `inscribirse_handler`, `desinscribirse_handler`, `reportar_resultado_handle` y `modificar_resultado_handle` (unas 850 líneas). Revisar `iniciar_torneo_battle_handle` y `new_tournament_assistance_handle`.
- [ ] **72.** Borrar `webserver.py` (Flask, que no se usa) y `from flask import app`.
- [ ] **73.** Funciones definidas dos veces: `listar_torneos_handle`, `tiene_rol_permitido`, `_parsear_embed_deck` y `_cargar_historial_emparejamientos`.
- [ ] **74.** Otras funciones sin uso: `asignar_strike_automatico`, `member_update_handle`, `comprobar_registro_y_enviar_comandos`, `extraer_mencion`, `enviar_ayuda_handle`, `obtener_torneos_swiss_disponibles_canal`, `obtener_estado_torneos_usuario`, `obtener_inscritos_ids`, `eliminar_rondas` y `eliminar_clasificacion`.
- [ ] **75.** Imports muertos o duplicados en todos los módulos, y constantes sin uso (`ROLES_BORRADOS`, `ROLES_BIENVENIDA`, `MAX_ERRORES`...).
- [ ] **76.** Dejar de subir a git los `.pyc` y `cache/torneos.json` (añadirlos a `.gitignore` y hacer `git rm --cached`).
