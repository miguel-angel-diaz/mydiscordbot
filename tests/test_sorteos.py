"""
Tests de la lógica del sorteo de premios (utils/sorteos.py):
    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GUILD_ID_ADMISION", "1")

from utils import sorteos


class TestParsearPremios(unittest.TestCase):
    def test_lineas_y_cantidades(self):
        self.assertEqual(sorteos.parsear_premios("Tapete\nToken x4"), ["Tapete"] + ["Token"] * 4)

    def test_comas_y_formatos_de_cantidad(self):
        self.assertEqual(sorteos.parsear_premios("2x Funda, Dado (x3)"), ["Funda"] * 2 + ["Dado"] * 3)

    def test_ignora_lineas_vacias_y_espacios(self):
        self.assertEqual(sorteos.parsear_premios("\n  Tapete   playmat \n\n"), ["Tapete playmat"])

    def test_vacio(self):
        with self.assertRaises(ValueError):
            sorteos.parsear_premios("  \n ")

    def test_demasiados(self):
        with self.assertRaises(ValueError):
            sorteos.parsear_premios(f"Token x{sorteos.MAX_PREMIOS + 1}")

    def test_cantidad_cero(self):
        with self.assertRaises(ValueError):
            sorteos.parsear_premios("Token x0")

    def test_nombre_largo(self):
        with self.assertRaises(ValueError):
            sorteos.parsear_premios("A" * (sorteos.MAX_NOMBRE_PREMIO + 1))


class TestCandidatos(unittest.TestCase):
    def test_participantes_sin_retirados(self):
        torneo = {"inscritos_ids": ["1", "2", 3], "retirados": ["2"]}
        self.assertEqual(sorteos.ids_participantes(torneo), ["1", "3"])

    def test_excluye_ganadores_y_descartados(self):
        sorteo = {"premios": [{"ganador": "1", "estado": "pendiente"}, {"ganador": "2", "estado": "aceptado"},
                              {"ganador": "3", "estado": "desierto"}],
                  "descartados": ["4"]}
        self.assertEqual(sorteos.candidatos(["1", "2", "3", "4", "5"], sorteo), ["3", "5"])

    def test_solo_presentes_y_sin_repetidos(self):
        self.assertEqual(sorteos.candidatos(["1", "2", "2", "3"], {}, presentes={"2", "3"}), ["2", "3"])


class TestEstado(unittest.TestCase):
    def test_bloqueo_eliminar(self):
        self.assertIsNone(sorteos.motivo_bloqueo_eliminar({}))
        self.assertIsNone(sorteos.motivo_bloqueo_eliminar({"sorteo": None}))
        self.assertIsNone(sorteos.motivo_bloqueo_eliminar({"sorteo": {"estado": "sin_sorteo"}}))
        self.assertIsNone(sorteos.motivo_bloqueo_eliminar({"sorteo": {"estado": "cerrado"}}))
        self.assertIn("dueño", sorteos.motivo_bloqueo_eliminar({"sorteo": {"estado": "pregunta"}}))
        en_curso = {"sorteo": {"estado": "en_curso", "premios": [{"estado": "aceptado"}, {"estado": "pendiente"}]}}
        self.assertIn("1/2", sorteos.motivo_bloqueo_eliminar(en_curso))

    def test_todo_resuelto(self):
        self.assertTrue(sorteos.todo_resuelto({"premios": [{"estado": "aceptado"}, {"estado": "desierto"}]}))
        self.assertFalse(sorteos.todo_resuelto({"premios": [{"estado": "aceptado"}, {"estado": "pendiente"}]}))

    def test_plazo_vencido(self):
        ahora = datetime.now(timezone.utc)
        pasado = {"estado": "pendiente", "plazo": (ahora - timedelta(minutes=1)).isoformat()}
        futuro = {"estado": "pendiente", "plazo": (ahora + timedelta(hours=1)).isoformat()}
        self.assertTrue(sorteos.plazo_vencido(pasado, ahora))
        self.assertFalse(sorteos.plazo_vencido(futuro, ahora))
        self.assertFalse(sorteos.plazo_vencido({**pasado, "estado": "aceptado"}, ahora))
        self.assertFalse(sorteos.plazo_vencido({"estado": "pendiente", "plazo": "basura"}, ahora))


class TestElegirTorneo(unittest.TestCase):
    def test_filtra_y_ordena(self):
        torneos = [
            {"codigo": "A", "tipo": "swiss", "estado": "en desarrollo"},
            {"codigo": "B", "tipo": "swiss", "estado": "finalizado", "sorteo": {"estado": "cerrado"}},
            {"codigo": "C", "tipo": "battle", "estado": "finalizado"},
            {"codigo": "D", "tipo": "swiss", "estado": "finalizado", "sorteo": {"estado": "sin_sorteo"}},
            {"codigo": "E", "tipo": "otro", "estado": "finalizado"},
            {"codigo": "F", "tipo": "swiss", "estado": "finalizado", "sorteo": {"estado": "en_curso"}},
        ]
        self.assertEqual([t["codigo"] for t in sorteos.torneos_sorteables(torneos)], ["C", "D", "A"])

    def test_etiqueta(self):
        suizo = {"codigo": "premoderntodosQHRH7L", "nombre": "Liga", "tipo": "swiss", "estado": "finalizado",
                 "inscritos_ids": ["1", "2", "3"], "retirados": ["3"]}
        self.assertEqual(sorteos.etiqueta_torneo(suizo),
                         "`premoderntodosQHRH7L` → Liga (suizo, finalizado, 2 jugadores)")
        self.assertIn("(battle, en juego)", sorteos.etiqueta_torneo({"codigo": "brx", "tipo": "battle"}))


class TestBotonesPersistentes(unittest.TestCase):
    """Los custom_id deben casar con su plantilla para que los botones sigan funcionando tras un reinicio."""

    def test_custom_ids_casan_con_su_plantilla(self):
        casos = [
            (sorteos.BotonHaySorteo, ("ABC123",)),
            (sorteos.BotonNoHaySorteo, ("liga-modern_2",)),
            (sorteos.BotonAceptarPremio, ("ABC123", 3, 123456789012345678)),
            (sorteos.BotonRenunciarPremio, ("ABC123", 0, 42)),
            (sorteos.BotonEnviado, ("ABC123", 4)),
        ]
        for clase, args in casos:
            boton = clase(*args)
            self.assertIsNotNone(clase.__discord_ui_compiled_template__.fullmatch(boton.custom_id), clase.__name__)
            self.assertLessEqual(len(boton.custom_id), 100)


if __name__ == "__main__":
    unittest.main()
