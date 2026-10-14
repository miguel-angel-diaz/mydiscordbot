"""
Tests de la encuesta anónima de fin de torneo (utils/encuestas.py):
    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GUILD_ID_ADMISION", "1")

from utils import encuestas

MADRID = ZoneInfo("Europe/Madrid")


class TestPreguntas(unittest.TestCase):
    def test_fichero_real_valido(self):
        elegir, textos = encuestas.cargar_preguntas()
        self.assertTrue(1 <= len(elegir) <= 4)
        self.assertLessEqual(len(textos), 5)
        estrellas = next(p for p in elegir if p["tipo"] == "estrellas")
        self.assertEqual(estrellas["opciones"], ["1", "2", "3", "4", "5"])

    def test_errores(self):
        with self.assertRaises(ValueError):
            encuestas.validar_preguntas({"elegir": []})
        with self.assertRaises(ValueError):
            encuestas.validar_preguntas({"elegir": [{"id": "a", "texto": "A", "tipo": "estrellas"}] * 2})
        with self.assertRaises(ValueError):
            encuestas.validar_preguntas({"elegir": [{"id": "a", "texto": "A", "opciones": ["solo una"]}]})
        with self.assertRaises(ValueError):
            encuestas.validar_preguntas({"elegir": [{"id": "a", "texto": "A", "tipo": "estrellas"}],
                                         "textos": [{"id": f"t{i}", "texto": "T"} for i in range(6)]})


class TestAnonimato(unittest.TestCase):
    def test_huella(self):
        h = encuestas.huella(123, "T1")
        self.assertEqual(h, encuestas.huella("123", "T1"))
        self.assertNotEqual(h, encuestas.huella(123, "T2"))
        self.assertNotEqual(h, encuestas.huella(124, "T1"))
        self.assertNotIn("123", h)

    def test_quien_puede_votar(self):
        encuesta = {"estado": "abierta", "destinatarios": ["1", "2"], "votaron": [encuestas.huella(2, "T1")]}
        self.assertIsNone(encuestas._no_puede_votar(encuesta, 1, "T1"))
        self.assertIn("Ya respondiste", encuestas._no_puede_votar(encuesta, 2, "T1"))
        self.assertIn("solo para", encuestas._no_puede_votar(encuesta, 3, "T1"))
        self.assertIn("cerrada", encuestas._no_puede_votar({**encuesta, "estado": "cerrada"}, 1, "T1"))
        self.assertIn("cerrada", encuestas._no_puede_votar(None, 1, "T1"))


class TestProgramacion(unittest.TestCase):
    def test_manana_a_las_10_de_madrid(self):
        noche = datetime(2026, 10, 1, 23, 30, tzinfo=MADRID)
        envio = encuestas.siguiente_envio(noche).astimezone(MADRID)
        self.assertEqual((envio.day, envio.hour, envio.minute), (2, 10, 0))

    def test_cambio_de_hora(self):
        # La noche del cambio de horario de invierno (25/10/2026) sigue saliendo a las 10:00 de Madrid
        envio = encuestas.siguiente_envio(datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)).astimezone(MADRID)
        self.assertEqual((envio.day, envio.hour), (25, 10))


ENCUESTA = {
    "codigo": "T1", "nombre": "Liga", "estado": "cerrada", "enviados": 4,
    "elegir": [{"id": "general", "texto": "General", "tipo": "estrellas", "opciones": ["1", "2", "3", "4", "5"]},
               {"id": "ritmo", "texto": "Ritmo", "tipo": "opciones", "opciones": ["Lento", "Bien", "Rápido"]}],
    "textos": [{"id": "mejorar", "texto": "Mejorar"}],
    "respuestas": [{"general": 5, "ritmo": "Bien", "mejorar": "=HYPERLINK(\"x\") más *mesas* @everyone"},
                   {"general": 4, "ritmo": "Bien"},
                   {"general": 3, "ritmo": "Lento", "mejorar": "Horario; más tarde"}],
}


class TestResultados(unittest.TestCase):
    def test_resumen(self):
        texto = encuestas.resumen(ENCUESTA)
        self.assertIn("**3** de 4 (75 %)", texto)
        self.assertIn("media **4.0** / 5", texto)
        self.assertIn(" 2 · Bien", texto)
        self.assertIn("**Mejorar** (2)", texto)
        self.assertIn("\\*mesas\\*", texto)          # sin formato Markdown
        self.assertNotIn("@everyone", texto)         # sin menciones

    def test_resumen_sin_respuestas(self):
        self.assertIn("Todavía no hay respuestas", encuestas.resumen({**ENCUESTA, "respuestas": []}))

    def test_csv(self):
        datos = encuestas.csv_respuestas(ENCUESTA)
        self.assertTrue(datos.startswith(b"\xef\xbb\xbf"))           # BOM para Excel
        texto = datos.decode("utf-8-sig")
        lineas = texto.splitlines()
        self.assertEqual(lineas[0], "torneo;general;ritmo;mejorar")
        self.assertEqual(len(lineas), 4)
        self.assertIn("'=HYPERLINK", texto)                           # fórmula neutralizada
        self.assertIn('"Horario; más tarde"', texto)                  # el ";" del texto va entre comillas


if __name__ == "__main__":
    unittest.main()
