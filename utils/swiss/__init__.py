"""
Sistema suizo propio, en tres capas:
  - engine.py: lógica pura (estadísticas, clasificación, emparejamientos, resultados), con tests.
  - service.py: operaciones sobre el estado guardado, con el lock de cada torneo.
  - presentacion.py: mensajes en los canales de Discord.
Los asistentes por DM de los comandos están en utils/swiss_handle.py.
"""
