"""
Tests del DM que avisa a cada jugador de su rival al salir una ronda (utils/swiss/presentacion.py):
    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.swiss.presentacion import texto_aviso_ronda


class TestTextoAvisoRonda(unittest.TestCase):
    def test_con_rival(self):
        texto = texto_aviso_ronda("abc123", "Liga Modern", 2, "42", "Ana")
        self.assertIn("Ronda 2 del torneo Liga Modern**", texto)
        self.assertNotIn("abc123", texto)
        self.assertIn("contra **Ana** (<@42>)", texto)
        self.assertIn("!agendar-partida", texto)
        self.assertIn("!mis-comandos", texto)

    def test_bye(self):
        texto = texto_aviso_ronda("abc123", "Liga Modern", 3)
        self.assertIn("BYE", texto)
        self.assertIn("victoria reportada", texto)
        self.assertNotIn("!agendar-partida", texto)


if __name__ == "__main__":
    unittest.main()
