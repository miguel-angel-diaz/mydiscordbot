"""
Tests de quién recibe el recordatorio de agenda de los jueves (utils/watchers.py). Sin Discord ni red:
    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.watchers import agenda_de_canal, partidas_sin_agendar, ronda_con_recorrido

RONDA = {"numero": 2, "emparejamientos": [
    {"j1": "1", "j2": "2", "resultado": None},     # agendada
    {"j1": "3", "j2": "4", "resultado": "2-1"},    # ya jugada
    {"j1": "5", "j2": "6", "resultado": None},     # sin agendar
    {"j1": "7", "j2": None, "resultado": "BYE"},
]}


def cita(j1, j2, torneo=None):
    texto = f"📅 [EVENTO] 16/10/2026 19:00 | <@{j1}> vs <@{j2}> | Agendado por <@{j1}>"
    return texto + (f" | Torneo `{torneo}`" if torneo else "")


class TestPartidasSinAgendar(unittest.TestCase):
    def test_solo_las_que_ni_se_jugaron_ni_se_agendaron(self):
        agenda = agenda_de_canal([cita(2, 1), "mensaje cualquiera"])
        self.assertEqual(partidas_sin_agendar("t1", RONDA, agenda), [("5", "6")])

    def test_cita_de_otro_torneo_no_cuenta(self):
        agenda = agenda_de_canal([cita(1, 2, "otro"), cita(5, 6, "t1")])
        self.assertEqual(partidas_sin_agendar("t1", RONDA, agenda), [("1", "2")])

    def test_quien_agenda_no_cuenta_como_jugador(self):
        # "Agendado por <@5>" en una cita de 5 contra otro no es la partida 5-6
        agenda = agenda_de_canal(["📅 [EVENTO] 16/10/2026 19:00 | <@1> vs <@2> | Agendado por <@6>"])
        self.assertIn(("5", "6"), partidas_sin_agendar("t1", RONDA, agenda))


class TestRondaConRecorrido(unittest.TestCase):
    def test_recien_salida_no(self):
        self.assertFalse(ronda_con_recorrido({"creada": "14/10/2026"}, date(2026, 10, 15)))

    def test_de_la_semana(self):
        self.assertTrue(ronda_con_recorrido({"creada": "12/10/2026"}, date(2026, 10, 15)))

    def test_antigua_sin_fecha(self):
        self.assertTrue(ronda_con_recorrido({}, date(2026, 10, 15)))


if __name__ == "__main__":
    unittest.main()
