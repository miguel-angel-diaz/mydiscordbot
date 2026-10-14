"""
Tests de cuándo toca cada recordatorio de deck (utils/watchers.py). Sin Discord ni red:
    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.watchers import _mensaje_recordatorio, aviso_pendiente


class TestAvisoPendiente(unittest.TestCase):
    def test_dias_exactos(self):
        self.assertEqual(aviso_pendiente({}, 3), 3)
        self.assertEqual(aviso_pendiente({}, 1), 1)

    def test_fuera_de_plazo(self):
        for dias in (10, 4, 0, -1):
            self.assertIsNone(aviso_pendiente({}, dias))

    def test_recupera_el_aviso_perdido(self):
        # El bot estaba caído el día de los 3 días: sale al día siguiente
        self.assertEqual(aviso_pendiente({}, 2), 3)

    def test_una_sola_vez(self):
        self.assertIsNone(aviso_pendiente({"recordatorio_3d_enviado": True}, 2))
        self.assertIsNone(aviso_pendiente({"recordatorio_1d_enviado": True}, 1))

    def test_el_de_un_dia_sale_aunque_ya_saliera_el_de_tres(self):
        self.assertEqual(aviso_pendiente({"recordatorio_3d_enviado": True}, 1), 1)

    def test_tras_el_ultimo_dia_no_sale_el_de_tres(self):
        self.assertIsNone(aviso_pendiente({"recordatorio_1d_enviado": True}, 2))


class TestMensaje(unittest.TestCase):
    def test_fechas(self):
        lunes = date(2026, 9, 28)
        texto = _mensaje_recordatorio("abc123", "Liga", 3, lunes)
        self.assertIn("lunes 28/09", texto)
        self.assertIn("domingo 27/09 a las 23:59", texto)
        self.assertIn("!subir-deck abc123", _mensaje_recordatorio("abc123", "Liga", 1, lunes))


if __name__ == "__main__":
    unittest.main()
