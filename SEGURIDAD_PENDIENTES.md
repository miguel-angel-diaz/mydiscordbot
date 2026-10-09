# Seguridad y correcciones pendientes · bot + web

Plan de trabajo a partir de las auditorías del 2026-10-09: la del bot (código y comprobación tarea a tarea del refactor) y la de seguridad de la web. Se trabaja igual que en `REFACTOR_PENDIENTES.md`: **una tarea cada vez**, marcándola con `[x]` y anotando entre paréntesis qué se hizo.

Cada tarea indica a qué proyecto afecta:
- **[BOT]** este repositorio, `mydiscordbot` (API aiohttp en Railway).
- **[WEB]** `C:\Users\madiaz.affin\myProyects\theklubnewweb` (web estática en Apache, theklubmtg.es).
- **[OPS]** sin código: Railway, hosting, Discord, claves.

**El problema principal.** La web mete en el HTML, con `innerHTML` y sin escapar, todo lo que le llega de la API: nombres de Discord, decks, nombres de torneo y feeds RSS. Además no hay CSP. Cualquier socio puede ejecutar código en el navegador de los demás poniéndose un apodo de Discord como `<img src=x onerror=…>` y robarles el token de sesión (7 días de acceso en su nombre, también si es admin). Por eso la fase 1 va primero y conviene publicarla en cuanto esté hecha.

Ramas: **[BOT]** en `fix/auditoria` (ya creada desde `main`). **[WEB]** en una rama `fix/seguridad` de `theklubnewweb`. No se hace commit, merge ni push sin que lo pida el usuario.

---

## Fase 0 · Urgente y sin código

- [x] **1.** [OPS] (Hecho por el usuario el 2026-10-09) Definir `JWT_SECRET` en Railway con un valor nuevo (`python -c "import secrets; print(secrets.token_urlsafe(32))"`). Ahora está vacía: se genera un secreto en cada deploy y las sesiones se pierden. Además, un valor nuevo invalida cualquier token que se haya podido robar.
- [x] **2.** [OPS] (Hecho por el usuario el 2026-10-09) Rotar el token del bot en el Discord Developer Portal. Está en el historial público del repo del bot (`config.py` y un `.pyc` de julio de 2025). Poner el nuevo en Railway y en `config_token.py`.
- [x] **3.** [OPS] (Hecho por el usuario el 2026-10-09) Rotar la clave de Challonge, que salió en una captura y en el chat. Poner la nueva en Railway y en `config_token.py`.
- [x] **4.** [OPS] (Hecho por el usuario el 2026-10-09) OpenRouter: rotar la clave o, si el análisis con IA ya no se usa, quitarlo (ver tarea 41) y borrar `OPENROUTER_API_KEY` de Railway y de `config_token.py`.
- [x] **5.** [OPS] (Hecho por el usuario el 2026-10-09) Borrar la variable `pepe` de Railway. `CACHE_PATH` se puede quitar: tiene el mismo valor que el código usa por defecto.
- [ ] **6.** [BOT] (Commit f5e8789 en `fix/auditoria`; falta integrarlo en `main` y desplegar, cuando lo pida el usuario) Revisar, hacer commit y desplegar `fix/auditoria`, con las correcciones de la auditoría del bot ya hechas: sancionados en la web, deck del rival, `!best-decks`, suizo, agenda, hora de Madrid, búsqueda exacta, etc. Están listadas al final de `REFACTOR_PENDIENTES.md`. La web es compatible y no hay que coordinar nada.

## Fase 1 · XSS en la web (crítico)

Un dato de la API **nunca** debe entrar en `innerHTML` sin escapar, tampoco dentro de un atributo (`data-*`, `href`, `src`, `alt`).

- [x] **7.** [WEB] (Hecho: escapeHtml() escapa & < > " ' y safeUrl() solo deja https y devuelve el resultado escapado; probadas con node) Crear en `assets/js/utils.js` las funciones `escapeHtml()`, que escapa `& < > " '`, y `safeUrl()`, que con `new URL()` solo acepta `https:` y si no devuelve `#`. Base para las tareas 8 a 15.
- [x] **8.** [WEB] (Hecho: nombre, torneo, contador, rango y números escapados; avatar por safeUrl(); borrado standings.js. Probado en node con nombres maliciosos) Clasificaciones públicas de la portada: escapar `p.nombre`, `torneo.nombre` y `participantes_count`, y pasar `p.avatar` por `safeUrl()`. **Afecta a cualquier visitante, sin login.** → `assets/js/standings-slider.js:18-40, 66`. Borrar `assets/js/standings.js`, que tiene el mismo fallo pero no se carga.
- [x] **9.** [WEB] (Hecho: nombres, fecha y hora escapados en las celdas; los data-* de editar y eliminar, escapados una vez en datosPartida) Agenda "Todas las partidas": escapar los nombres de los jugadores en las celdas y en los `data-nombre1/2`. Se carga sola al entrar en la zona de socios, así que afecta a todos. → `assets/js/member.js:1201-1230`.
- [x] **10.** [WEB] (Hecho: nombre, arquetipo, decklist y sideboard escapados; encodeURIComponent en la URL) Deck del rival: escapar nombre, arquetipo, decklist y sideboard, o mejor ponerlos con `textContent`. Meterlos dentro de `<pre>` no protege nada. → `member.js:612-623`.
- [x] **11.** [WEB] (Hecho: deck del panel, Mis decks y el panel de torneo abierto escapados; toggleDeckDisplay borrada (62 líneas sin uso)) Los decks propios, que son el mismo texto que llega al rival: escapar. → `member.js:373-377, 796-801, 1791-1797`. Borrar `toggleDeckDisplay` (`member.js:1516-1525`), que no se usa.
- [x] **12.** [WEB] (Hecho: clasificación del panel, enfrentamientos (texto y data-*) y pendientes (texto y data-* en datosPartida)) Nombres de jugadores en la clasificación, los enfrentamientos y las pendientes de la zona de socios. → `member.js:303, 516, 525, 1356-1357, 1366, 1375-1376, 1384-1385`.
- [x] **13.** [WEB] (Hecho: nombre, fecha, contadores y data-* del banner, de Mis torneos y de pendientes) Nombres y fechas de torneo en el banner y los selectores. → `member.js:144, 883, 886, 1335`.
- [x] **14.** [WEB] (Hecho: el Toast pone el mensaje con textContent; los ${err.message} de member.js, escapados) Mensajes de la API: el aviso emergente con `textContent` (`assets/js/toast.js:25-29`, que cubre todas sus llamadas) y los `${err.message}` metidos con `innerHTML`. → `member.js:313, 572, 629, 1268, 1432, 1534, 1831`.
- [x] **15.** [WEB] (Hecho: textoPlano() con DOMParser + escapeHtml en título y descripción; enlace e imagen por safeUrl(); rel=noopener) Podcast y artículos: escapar título, descripción, fecha y `alt`, pasar `enlace` e `imagen` por `safeUrl()` y añadir `rel="noopener noreferrer"`. → `assets/js/broadcast.js:32-46, 79-83`.
- [x] **16.** [WEB] (Hecho: encodeURIComponent en clasificacion-torneo, torneo-enfrentamientos y deck-rival) `encodeURIComponent()` en los parámetros de las URL de `fetch`. → `member.js:272, 426, 599`.
- [x] **17.** [WEB] (Hecho: barrido de los ${} de member.js (los que quedan son seguros) y prueba jsdom de extremo a extremo con 15 pantallas y datos maliciosos: 15 XSS en la versión anterior, 0 en la nueva; con datos normales todo se ve igual. Versiones ?v= subidas en index.html para que el navegador no use la copia vieja) Prueba final de la fase: buscar con `grep -n "innerHTML\|insertAdjacentHTML" assets/js/*.js` y comprobar que cada uso tiene solo texto fijo o datos escapados. Probar con un nombre `<img src=x onerror=alert(1)>` en un bot de pruebas, o simulando la respuesta de la API.

## Fase 2 · Cabeceras y hosting de la web (defensa en profundidad)

- [x] **18.** [WEB] (Hecho: assets/js/scroll-restoration.js, cargado sin defer en el <head>; ya no queda ningún script inline ejecutable) Mover el `<script>` inline de `index.html:38-42` (`history.scrollRestoration`) a `assets/js/scroll-restoration.js`, cargado sin `defer` en el `<head>`. Es requisito para la CSP, que no debe usar `'unsafe-inline'` en `script-src`.
- [x] **19.** [WEB] (La web está en Cloudflare Pages, que no lee .htaccess: las mismas cabeceras y la misma CSP van en `_headers` (commit 90601dd) y el .htaccess se quitó. Antes: .htaccess en la raíz con https, HSTS, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, COOP, CSP con script-src 'self' y connect-src solo a la API, y 403 a .git, ocultos y copias. Probada en Chrome headless con la API simulada: portada y zona de socios sin ninguna violación y un XSS inyectado a propósito, bloqueado. Se aplica en modo normal, no Report-Only, porque ya está probada) `.htaccess` en la raíz:
  - redirección a https y HSTS;
  - `X-Content-Type-Options`, `X-Frame-Options` / `frame-ancestors`, `Referrer-Policy` y `Permissions-Policy`;
  - bloquear `.git` y los ficheros ocultos (salvo `.well-known`);
  - **CSP** con `script-src 'self'` y `connect-src` limitado a la API de Railway.

  Primero en modo `Content-Security-Policy-Report-Only` y, cuando no salgan avisos en la consola, en modo normal. La propuesta completa está en el informe del revisor de hosting.
- [ ] **20.** [OPS] (Cloudflare Pages despliega solo al hacer push a main de la web. Comprobar con `curl -sI https://theklubmtg.es | grep -i -E "content-security|strict-transport|x-frame"` que salen las cabeceras; Pages no publica .git) Desplegar solo `index.html`, `assets/` y `.well-known/`, nunca la carpeta `.git`. Comprobar en vivo con `curl -I https://theklubmtg.es` que salen las cabeceras y que `https://theklubmtg.es/.git/HEAD` da 403 o 404.
- [x] **21.** [WEB] (Hecho: los 25 style="..." (7 en index.html, 18 en member.js) pasan a clases de utilidad al final de styles.css; la CSP ya no lleva 'unsafe-inline'. Comprobado en Chrome: los 21 elementos afectados tienen exactamente los mismos estilos calculados que antes y el panel de torneo se abre y se cierra igual) (Opcional) Pasar a clases CSS los `style="..."` de `index.html:743-781` y de las plantillas de `member.js` (17), para quitar `'unsafe-inline'` de `style-src`.
- [x] **22.** [WEB] (Hecho: Inter y Space Grotesk, variables y en woff2, en assets/fonts con assets/css/fonts.css; quitados los enlaces y el @import de Google Fonts y el de Fontshare, que no se usaba en ningún sitio. La CSP queda con style-src y font-src 'self') (Opcional) Alojar en local las fuentes de Google Fonts y Fontshare (como ya se hace con keyrune), para quitar dos orígenes externos de la CSP.

## Fase 3 · Sesiones y API del bot

- [x] **23.** [BOT] (Hecho: POST /auth/logout y `iat` en el token; cerrar sesión invalida todos los tokens anteriores de ese usuario (también los antiguos sin iat). En memoria, por decisión del usuario: tras reiniciar se olvida, acotado por la caducidad de 24 h. Probado: el token cerrado da 401, otros usuarios y el nuevo login siguen valiendo) Cierre de sesión real (la tarea 6c del refactor): un endpoint `POST /auth/logout` que revoque el token, con un contador de versión de sesión por usuario guardado en el estado o una lista de `jti` revocados. Ahora un token robado sigue valiendo 7 días aunque la víctima cierre sesión.
- [x] **24.** [BOT] (Hecho: 24 horas, por decisión del usuario) Bajar la caducidad del JWT (`SESSION_EXPIRATION_SECONDS`, ahora 7 días), por ejemplo a 24 horas. **Decisión del usuario:** un valor más corto obliga a iniciar sesión más a menudo.
- [x] **25.** [WEB] (Hecho: cerrarSesion() llama a /auth/logout (keepalive) y limpia klubDiscordId; al salir se vacían la agenda, el banner, las pendientes, mis torneos, mis decks y el deck del rival. Probado en Chrome con la CSP estricta) Al cerrar sesión: llamar a `/auth/logout` (depende de la 23), vaciar los contenedores de la zona de socios y limpiar `window.klubDiscordId`. → `assets/js/auth.js:235-244`.
- [x] **26.** [BOT] (Hecho: título, descripción y fecha en texto plano (sin etiquetas, entidades decodificadas) y enlace e imagen solo si son https; un RSS con <img onerror> y javascript: sale limpio) Que la API devuelva las descripciones del podcast y de Medium como texto plano (sin HTML ni etiquetas cortadas) y solo enlaces e imágenes `https`. Así se protege también cualquier otro cliente. → `utils/api/contenido.py`.
- [x] **27.** [BOT] (Hecho: _texto() de utils/decks.py rechaza < y > en nombre, decklist y sideboard, para Discord y la web) Rechazar `<` y `>` en los textos de los decks (nombre, decklist, sideboard), que nunca los necesitan. Es defensa en profundidad frente a la tarea 10. → `utils/decks.py`.
- [x] **28.** [BOT] (Hecho: mis-decks, deck-rival, todas-partidas y clasificacion-torneo con miembro=True. mis-torneos sigue solo con sesión (es el propio historial, sale de la caché)) Los endpoints con `servidor=True` no comprueban que el usuario siga en el servidor: `todas-partidas`, `mis-decks`, `clasificacion-torneo` y `deck-rival`. Pasarlos a `miembro=True`. → `utils/api/*.py`.
- [x] **29.** [BOT] (Hecho: los fallos cuentan por IP (3 fallos bloquean la IP 15 min, no la cuenta, y la víctima recibe un aviso), un código nuevo no anula los anteriores (hasta 3 activos) y la respuesta es la misma exista o no el usuario. Probado con atacante y víctima desde IPs distintas: 11/11) Login por código:
  - Ahora cualquiera puede pedir códigos a nombre de otro y fallarlos para dejarle bloqueado 15 minutos, o pedir uno nuevo para anularle el suyo.
  - La respuesta 404 revela si un usuario existe.
  - Propuesta: que el bloqueo y los intentos cuenten por usuario e IP, y responder lo mismo exista o no el usuario.

  → `utils/api/auth.py:150-290`.
- [x] **30.** [BOT] (Hecho: `null` fuera de los orígenes por defecto (se puede añadir con CORS_ORIGENES para pruebas locales)) Quitar el origen `null` de los CORS por defecto (solo servía para abrir la web como fichero local). → `utils/api/routes.py:12-18`.
- [x] **31.** [BOT] (Hecho: los RSS con caché de 10 min y timeout de 10 s; torneo-enfrentamientos usa la caché aunque esté vacía (antes consultaba Challonge en cada visita)) Caché (unos minutos) y timeout corto para los RSS (`contenido.py`). Además, que `torneo-enfrentamientos` no vuelva a consultar Challonge en cada visita cuando un torneo de la caché no tiene partidos. → `utils/api/torneos.py:386-409`.
- [x] **32.** [BOT] (Hecho: jugador_id como texto) `mis-decks`: enviar `jugador_id` como texto, porque JS redondea los números de 18 o 19 cifras. La web no lo usa, pero así queda bien para el futuro. → `utils/decks.py:180`.

## Fase 4 · Correcciones y limpieza de la web

- [ ] **33.** [WEB] Formulario de admisión: `e.preventDefault()` en la primera línea del manejador. Ahora, si se han agotado los intentos, el navegador envía el formulario por GET y el email acaba en la URL y en los logs. El límite real ya está en el servidor (3 por hora). → `assets/js/admission.js:40-44`.
- [ ] **34.** [WEB] (El console.log de depuración de member.js ya se quitó en la fase 1) Quitar el modo de desarrollo (`DEV_MODE_FAKE_LOGIN`, `dev-fake-session-token`) y el `console.log` de depuración. → `assets/js/auth.js:4`, `member.js:440-444, 769`.
- [ ] **35.** [WEB] `rel="noopener noreferrer"` en todos los `target="_blank"`. → `index.html:288, 291, 313`.
- [ ] **36.** [WEB] Texto de ayuda del login: pedir el usuario o apodo de Discord **exacto** (el bot ya no acepta coincidencias parciales). → `index.html:466-467`.
- [ ] **37.** [WEB] Quitar del repo los 45 retos caducados de `.well-known/acme-challenge/` (el hosting los crea y borra al renovar) y añadir un `.gitignore`. Mantener su `.htaccess` en el servidor.
- [ ] **38.** [WEB] Borrar los ficheros sin uso: `assets/css/all-css.css`, `assets/js/backtotop.js`, `assets/js/scroll.js`, `assets/images/image.png`, `standings.js` (ver 8) y los demás que no cargue `index.html`.
- [ ] **39.** [WEB] SEO y coherencia:
  - mover `robots.txt` y `sitemap.xml` de `assets/` a la raíz;
  - `<link rel="canonical">` y el JSON-LD apuntan a `pngpremodern.com`, no a theklubmtg.es;
  - falta `/apple-touch-icon.png`.
- [ ] **40.** [OPS] Usar el email `noreply` de GitHub en los commits de los dos repos: el email del trabajo queda a la vista en el historial si son públicos. Los commits pasados no se cambian sin reescribir el historial.

## Fase 5 · Correcciones pendientes del bot (no de seguridad)

- [ ] **41.** [BOT] (Decidido el 2026-10-09: la IA ya no se usa y la clave se quitó de Railway) Quitar `llamar_a_openrouter` y `analizar_torneo_con_ia` (`utils/commons.py:611-660`), su llamada en `utils/torneos.py` y `OPENROUTER_API_KEY` de `config.py` y de `data/ayuda_comandos.json`. El informe seguiría publicando las cartas más jugadas y los mejores decks.
- [ ] **42.** [BOT] `!iniciar-swiss`: si `generar_ronda` lanza una excepción (por ejemplo, Discord falla al guardar), deshacer el cambio a "en desarrollo" y el recorte de inscritos, igual que cuando devuelve error. → `utils/swiss/service.py:178-182`.
- [ ] **43.** [BOT] Orden de las dos escrituras de `generar_ronda` (rondas y `ronda_actual`) y de `eliminar_ronda_swiss`: si falla la segunda, la ronda siguiente sale con el número repetido. Que el número salga de las rondas guardadas y no de `ronda_actual`. → `utils/swiss/service.py:269-270, 330-331`, `engine.py:188`.
- [ ] **44.** [BOT] IDs escritos a mano: el servidor en `utils/watchers.py:26` (usar `config.GUILD_ID_ADMISION`) y el canal de log de comandos en `utils/events.py:365` (pasarlo a `utils/canales.py`).
- [ ] **45.** [BOT] Atajos con espacio (`!subir deck`):
  - si el usuario tiene los DMs cerrados, el comando se descarta sin avisarle;
  - la pregunta "¿Querías usar `!eliminar-mensajes`?" se manda antes de comprobar permisos, así que enseña comandos de admin a cualquiera.

  → `utils/events.py:192-222`.
- [ ] **46.** [BOT] `utils/abandonos.py:95-120`: usar `presentacion.quitar_partida_de_citas` con el número de ronda leído antes de retirar al jugador (ahora busca el último mensaje y puede fallar si se completa la ronda), y quitar la clase `_Ctx` que repite el antiguo FakeCtx.
- [ ] **47.** [BOT] `!agendar-partida` con los argumentos en la misma línea:
  - no valida fecha ni hora;
  - con el ID de alguien que ya no está en el servidor, `jugador.send` lanza `AttributeError`.

  → `utils/jugadores.py:43-120`.
- [ ] **48.** [BOT] Battle: `!reportar-resultado-battle <código> @j1`, sin el segundo jugador, ignora el primero. → `utils/battle.py:421-440`.
- [ ] **49.** [BOT] `requirements.txt`: comprobar y quitar los paquetes que ya no se importan (`pychallonge`, `seaborn`, `requests`, `beautifulsoup4`, `python-dotenv`, `pytz`, `tzlocal`). Así la instalación en Railway es más rápida.
- [ ] **50.** [BOT] (Cosmético) Al finalizar un suizo con una ronda que tenía BYE, el mensaje de citas se queda con la cabecera y la línea del BYE.
