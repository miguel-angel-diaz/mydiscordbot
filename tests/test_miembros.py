"""
Tests de la búsqueda de jugadores (utils/miembros.py). Sin Discord ni red:
    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import miembros


def miembro(uid, name, nick=None, global_name=None, bot=False):
    return SimpleNamespace(id=uid, name=name, global_name=global_name, display_name=nick or global_name or name,
                           bot=bot)


class Servidor:
    def __init__(self, *gente):
        self.members = list(gente)

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)


ANA = miembro(1, "ana_mtg", nick="Ana")
MARIANA = miembro(2, "mariana")
JOSE = miembro(3, "pepe", nick="José")
JOSE2 = miembro(4, "jose99", nick="José")
BOT = miembro(5, "anabot", bot=True)
SERVIDOR = Servidor(ANA, MARIANA, JOSE, JOSE2, BOT)


class TestTextos(unittest.TestCase):
    def test_id_de_texto(self):
        self.assertEqual(miembros.id_de_texto("123"), 123)
        self.assertEqual(miembros.id_de_texto(" <@123> "), 123)
        self.assertEqual(miembros.id_de_texto("<@!123>"), 123)
        self.assertIsNone(miembros.id_de_texto("ana"))
        self.assertIsNone(miembros.id_de_texto("<@&123>"))   # mención de rol

    def test_normalizar(self):
        self.assertEqual(miembros.normalizar("  JOSÉ "), "jose")


class TestCandidatos(unittest.TestCase):
    def test_yo(self):
        self.assertEqual(miembros.candidatos(SERVIDOR, "Yo", autor=MARIANA), [MARIANA])

    def test_mencion_e_id(self):
        self.assertEqual(miembros.candidatos(SERVIDOR, "<@2>"), [MARIANA])
        self.assertEqual(miembros.candidatos(SERVIDOR, "1"), [ANA])

    def test_id_ausente(self):
        [fuera] = miembros.candidatos(SERVIDOR, "999")
        self.assertEqual(fuera.id, "999")

    def test_exacto_gana_al_parcial(self):
        # "ana" es exacto para Ana y parcial para Mariana: solo cuenta el exacto
        self.assertEqual(miembros.candidatos(SERVIDOR, "ANA"), [ANA])

    def test_usuario_y_tildes(self):
        self.assertEqual(miembros.candidatos(SERVIDOR, "pepe"), [JOSE])
        self.assertEqual(miembros.candidatos(SERVIDOR, "jose"), [JOSE, JOSE2])

    def test_parcial_sin_bots(self):
        self.assertEqual(miembros.candidatos(SERVIDOR, "rian"), [MARIANA])
        self.assertNotIn(BOT, miembros.candidatos(SERVIDOR, "an"))

    def test_vacio(self):
        self.assertEqual(miembros.candidatos(SERVIDOR, "  "), [])
        self.assertEqual(miembros.candidatos(SERVIDOR, "zzz"), [])


if __name__ == "__main__":
    unittest.main()
