"""
Tests del predictivo del Barbas (utils/barbas.py): de lo que escribe alguien al comando que buscaba.
    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.barbas import predecir


def comando(nombre, *aliases):
    return {"comando": nombre, "aliases": list(aliases), "descripcion": nombre}


COMANDOS = [
    comando("mis-comandos", "comandos"),
    comando("agendar-partida", "agendar_partida"),
    comando("modificar-agenda"),
    comando("subir-deck", "subir_deck"),
    comando("editar-deck"),
    comando("reportar-swiss", "reportar-resultado"),
    comando("inscribir-swiss"),
]


def nombres(texto, comandos=COMANDOS):
    return [c["comando"] for c in predecir(texto, comandos)]


class TestTextoLibre(unittest.TestCase):
    def test_pistas(self):
        self.assertEqual(nombres("hola, quiero agendar una partida con Ana")[0], "agendar-partida")
        self.assertEqual(nombres("¿cómo subo mi mazo?")[0], "subir-deck")
        self.assertEqual(nombres("Gané 2-0 a Pepe"), ["reportar-swiss"])

    def test_mas_aciertos_primero(self):
        self.assertEqual(nombres("quiero editar el deck")[0], "editar-deck")

    def test_solo_al_inicio_de_palabra(self):
        # "necesita" no es "cita", "ahora" no es "hora"
        self.assertEqual(nombres("ahora se necesita algo"), [])

    def test_nada_que_ver(self):
        self.assertEqual(nombres("hola barbas, ¿qué tal?"), [])

    def test_solo_comandos_que_puede_usar(self):
        self.assertEqual(nombres("me apunto al torneo", COMANDOS[:3]), [])


class TestComandoMalEscrito(unittest.TestCase):
    def test_empieza_igual(self):
        self.assertEqual(nombres("!agendar")[0], "agendar-partida")
        self.assertEqual(nombres("!reportar")[0], "reportar-swiss")

    def test_parecido(self):
        self.assertEqual(nombres("!subirdeck")[0], "subir-deck")

    def test_nunca_sugiere_mis_comandos(self):
        self.assertNotIn("mis-comandos", nombres("!comandoss"))

    def test_maximo_tres(self):
        self.assertLessEqual(len(nombres("!deck lista mazo editar resultado agendar")), 3)


if __name__ == "__main__":
    unittest.main()
