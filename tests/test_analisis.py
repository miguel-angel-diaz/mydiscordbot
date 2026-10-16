"""
Tests del análisis de fin de torneo (utils/analisis.py). Sin Discord ni red:
    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.analisis import SIN_ARQUETIPO, _grafico, construir_embed, reparto_arquetipos, top_cartas

DECKS = [
    {"archetype": "Burn", "decklist": "4 Lightning Bolt\n4 Chain Lightning\n20 Mountain"},
    {"archetype": "Burn", "decklist": "4x Lightning Bolt\n2 Fireblast\n18 Mountain"},
    {"archetype": "Mono Black", "decklist": "4 Dark Ritual\n1 Lightning Bolt\n20 Swamp"},
    {"archetype": "Desconocido", "decklist": "3 Dark Ritual\nlínea rara\n"},
]


class TestTopCartas(unittest.TestCase):
    def test_suma_copias_sin_basicas(self):
        top = top_cartas(DECKS)
        self.assertEqual(top[0], ("Lightning Bolt", 9, 3))
        self.assertEqual(top[1], ("Dark Ritual", 7, 2))
        self.assertNotIn("Mountain", [c for c, _, _ in top])

    def test_limite(self):
        self.assertEqual(len(top_cartas(DECKS, n=2)), 2)

    def test_empate_desempata_por_numero_de_decks(self):
        decks = [{"decklist": "4 A"}, {"decklist": "2 B"}, {"decklist": "2 B"}]
        self.assertEqual([c for c, _, _ in top_cartas(decks)], ["B", "A"])


class TestArquetipos(unittest.TestCase):
    def test_porcentajes(self):
        reparto = reparto_arquetipos(DECKS)
        self.assertEqual(reparto[0], ("Burn", 2, 50.0))
        self.assertIn((SIN_ARQUETIPO, 1, 25.0), reparto)
        self.assertAlmostEqual(sum(p for _, _, p in reparto), 100.0)


class TestPresentacion(unittest.TestCase):
    def test_embed(self):
        embed = construir_embed("t1", "Torneo de prueba", DECKS)
        self.assertEqual(embed.footer.text, "Torneo t1")
        self.assertIn("Lightning Bolt", embed.fields[0].value)
        self.assertIn("50.0%", embed.fields[1].value)

    def test_grafico_png(self):
        self.assertTrue(_grafico("t1", DECKS).startswith(b"\x89PNG"))

    def test_grafico_con_muchos_arquetipos(self):
        decks = [{"archetype": f"Arquetipo {i}", "decklist": "4 Carta"} for i in range(15)]
        self.assertTrue(_grafico("t1", decks).startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
