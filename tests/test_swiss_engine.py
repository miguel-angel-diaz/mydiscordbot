"""
Tests de la lógica pura del suizo (utils/swiss/engine.py). Sin Discord ni red:
    python -m unittest discover -s tests
"""
import os
import random
import sys
import unittest
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.swiss import engine


def ronda(numero, *partidas, completa=True):
    """partidas: (j1, j2, resultado); j2=None es un BYE."""
    return {"numero": numero, "completa": completa,
            "emparejamientos": [{"j1": a, "j2": b, "resultado": "BYE" if b is None else r} for a, b, r in partidas]}


def torneo(jugadores, ronda_actual=0, **extra):
    return {"tipo": "swiss", "estado": "en desarrollo", "inscritos_ids": list(jugadores),
            "ronda_actual": ronda_actual, **extra}


def simular(jugadores, codigo="t1", semilla=1):
    """Juega un torneo entero (gana siempre j1 por 2-0) y devuelve las rondas."""
    t, rondas = torneo(jugadores), []
    azar = random.Random(semilla)
    while engine.error_nueva_ronda(t, rondas) is None:
        r = engine.nueva_ronda(codigo, t, rondas, azar)
        for e in engine.partidas_pendientes(r):
            engine.registrar_resultado(r, e["j1"], "2-0", e["j2"])
        rondas.append(r)
        t["ronda_actual"] = r["numero"]
    return t, rondas


class RondasNecesarias(unittest.TestCase):
    def test_potencias_de_dos(self):
        self.assertEqual([engine.rondas_necesarias(n) for n in (0, 1, 2, 3, 4, 5, 8, 9, 16, 17)],
                         [0, 0, 1, 2, 2, 3, 3, 4, 4, 5])


class Estadisticas(unittest.TestCase):
    def test_victoria_empate_y_bye(self):
        rondas = [ronda(1, ("a", "b", "2-1"), ("c", None, None)),
                  ronda(2, ("a", "c", "1-1"), ("b", None, None))]
        s = engine.calcular_estadisticas(rondas, ["a", "b", "c"])
        self.assertEqual((s["a"]["mp"], s["a"]["w"], s["a"]["dw"], s["a"]["dif"]), (4.0, 1, 1, 1))
        self.assertEqual((s["b"]["mp"], s["b"]["l"], s["b"]["w"]), (3.0, 1, 1))   # el BYE cuenta como victoria
        self.assertEqual(s["c"]["opponents"], ["a"])                               # el BYE no es rival
        self.assertAlmostEqual(s["a"]["mwp"], 4 / 6)

    def test_minimo_33_por_ciento_en_el_omw(self):
        s = engine.calcular_estadisticas([ronda(1, ("a", "b", "2-0"))], ["a", "b"])
        self.assertAlmostEqual(s["b"]["mwp"], 1 / 3)     # 0 victorias -> se cuenta 33 %
        self.assertAlmostEqual(s["a"]["omw"], 1 / 3)
        self.assertAlmostEqual(s["b"]["omw"], 1.0)

    def test_buchholz_recortado(self):
        rondas = [ronda(1, ("a", "b", "2-0"), ("c", "d", "2-0")),
                  ronda(2, ("a", "c", "2-0"), ("b", "d", "2-0")),
                  ronda(3, ("a", "d", "2-0"), ("b", "c", "2-0"))]
        s = engine.calcular_estadisticas(rondas, "abcd")
        mwps = sorted(s[o]["mwp"] for o in "bcd")
        self.assertAlmostEqual(s["a"]["bch"], mwps[1])   # sin el mejor ni el peor

    def test_pendientes_y_resultados_raros_no_cuentan(self):
        rondas = [ronda(1, ("a", "b", None), ("c", "d", "x"), completa=False)]
        s = engine.calcular_estadisticas(rondas, "abcd")
        self.assertTrue(all(d["rondas"] == 0 for d in s.values()))

    def test_jugador_que_no_esta_inscrito_no_rompe(self):
        s = engine.calcular_estadisticas([ronda(1, ("a", "z", "2-0"))], ["a"])
        self.assertIn("z", s)


class Clasificacion(unittest.TestCase):
    def test_orden_puntos_omw_dif(self):
        rondas = [ronda(1, ("a", "b", "2-0"), ("c", "d", "2-1")),
                  ronda(2, ("a", "c", "2-0"), ("b", "d", "2-0"))]
        cl = engine.clasificacion("t1", rondas, "abcd")
        self.assertEqual([p["id"] for p in cl], ["a", "b", "c", "d"])
        self.assertEqual([p["rk"] for p in cl], [1, 2, 3, 4])
        self.assertEqual(set(cl[0]), {"id", "rk", "mp", "w", "l", "dw", "omw", "bch", "dif"})

    def test_empate_total_es_reproducible_y_depende_del_torneo(self):
        jugadores = [str(i) for i in range(8)]
        a = [p["id"] for p in engine.clasificacion("t1", [], jugadores)]
        self.assertEqual(a, [p["id"] for p in engine.clasificacion("t1", [], list(reversed(jugadores)))])
        self.assertNotEqual(a, [p["id"] for p in engine.clasificacion("otro", [], jugadores)])


class Inscripcion(unittest.TestCase):
    def setUp(self):
        self.t = {"tipo": "swiss", "estado": "abierto", "nivel": "socios", "inscritos_ids": ["1"], "total_maximo": 2}

    def test_errores(self):
        self.assertEqual(engine.error_inscripcion(None, 2, [], []), "El torneo no existe.")
        self.assertEqual(engine.error_inscripcion({**self.t, "estado": "en desarrollo"}, 2, ["Socio"], ["socio"]),
                         "Las inscripciones de este torneo están cerradas.")
        self.assertEqual(engine.error_inscripcion(self.t, 2, ["Miembro"], ["Socio"]), "Este torneo es solo para socios.")
        self.assertEqual(engine.error_inscripcion(self.t, 1, ["socio"], ["Socio"]), "Ya estás inscrito.")
        self.assertEqual(engine.error_inscripcion({**self.t, "total_maximo": 1}, 2, ["Socio"], ["Socio"]),
                         "No quedan plazas disponibles.")

    def test_permitidas(self):
        self.assertIsNone(engine.error_inscripcion(self.t, 2, ["SOCIO"], ["Socio"]))
        self.assertIsNone(engine.error_inscripcion(self.t, 2, [], ["Socio"], forzar=True))   # admin inscribiendo


class NuevaRonda(unittest.TestCase):
    def test_errores(self):
        self.assertEqual(engine.error_nueva_ronda(torneo("ab", estado="finalizado"), []), "El torneo ya ha finalizado.")
        self.assertIn("!iniciar-swiss", engine.error_nueva_ronda(torneo("ab", estado="abierto"), []))

    def test_numero_de_ronda_si_falla_una_de_las_dos_escrituras(self):
        r1 = {"numero": 1, "completa": True, "emparejamientos": [{"j1": "a", "j2": "b", "resultado": "2-0"}]}
        r2 = {"numero": 2, "completa": True, "emparejamientos": [{"j1": "a", "j2": "b", "resultado": "1-1"}]}
        # generar_ronda guardó la ronda 2 pero no llegó a actualizar ronda_actual (sigue en 1)
        self.assertEqual(engine.nueva_ronda("t1", torneo("abcd", 1), [r1, r2])["numero"], 3)
        # eliminar_ronda bajó ronda_actual a 1 pero no llegó a borrar la ronda 2
        self.assertEqual(engine.numero_ultima_ronda(torneo("abcd", 1), [r1, r2]), 2)
        # caso normal
        self.assertEqual(engine.nueva_ronda("t1", torneo("abcd", 2), [r1, r2])["numero"], 3)
        self.assertEqual(engine.error_nueva_ronda(torneo("ab", retirados=["b"]), []), "Se necesitan al menos 2 jugadores.")
        pendiente = [ronda(1, ("a", "b", None), ("c", "d", "2-0"), completa=False)]
        self.assertIn("1 partida(s) sin resultado", engine.error_nueva_ronda(torneo("abcd", 1), pendiente))
        self.assertIn("Ya se han jugado las 2 rondas", engine.error_nueva_ronda(torneo("abcd", 2), []))

    def test_primera_ronda_con_bye(self):
        r = engine.nueva_ronda("t1", torneo("abcde"), [], random.Random(3))
        self.assertEqual(r["numero"], 1)
        jugados = [p for e in r["emparejamientos"] for p in (e["j1"], e["j2"]) if p]
        self.assertEqual(sorted(jugados), list("abcde"))
        byes = [e for e in r["emparejamientos"] if e["j2"] is None]
        self.assertEqual(len(byes), 1)
        self.assertEqual(byes[0]["resultado"], "BYE")

    def test_no_empareja_a_los_retirados(self):
        r = engine.nueva_ronda("t1", torneo("abcd", retirados=["d"]), [], random.Random(1))
        self.assertNotIn("d", [p for e in r["emparejamientos"] for p in (e["j1"], e["j2"])])

    def test_torneo_completo_sin_revanchas_ni_byes_repetidos(self):
        for n in range(2, 18):
            jugadores = [str(i) for i in range(n)]
            t, rondas = simular(jugadores, semilla=n)
            self.assertEqual(len(rondas), engine.rondas_necesarias(n))
            parejas = [frozenset((e["j1"], e["j2"])) for r in rondas for e in r["emparejamientos"] if e["j2"]]
            self.assertEqual(len(parejas), len(set(parejas)), f"revancha con {n} jugadores")
            byes = [e["j1"] for r in rondas for e in r["emparejamientos"] if e["j2"] is None]
            self.assertEqual(len(byes), len(set(byes)), f"BYE repetido con {n} jugadores")
            self.assertTrue(all(r["completa"] for r in rondas))

    def test_bye_al_peor_clasificado_sin_bye(self):
        rondas = [ronda(1, ("a", "b", "2-0"), ("c", "d", "2-0"), ("e", None, None))]
        r = engine.nueva_ronda("t1", torneo("abcde", 1), rondas)
        bye = next(e["j1"] for e in r["emparejamientos"] if e["j2"] is None)
        self.assertIn(bye, {"b", "d"})     # perdieron la ronda 1; "e" ya tuvo BYE


class Emparejar(unittest.TestCase):
    def test_revancha_solo_si_no_hay_otra(self):
        historial = engine.historial_emparejamientos([ronda(1, ("a", "b", "2-0"))])
        parejas, bye = engine.emparejar_ronda(["a", "b"], historial, set())
        self.assertEqual((parejas, bye), ([("a", "b")], None))

    def test_retrocede_para_evitar_revanchas(self):
        # Por orden, a-b dejaría c-d, que ya jugaron: tiene que ser a-c / b-d o a-d / b-c
        historial = engine.historial_emparejamientos([ronda(1, ("c", "d", "2-0"))])
        parejas, _ = engine.emparejar_ronda(["a", "b", "c", "d"], historial, set())
        self.assertNotIn(frozenset("cd"), {frozenset(p) for p in parejas})

    def test_todos_contra_todos_agotados_usa_la_revancha_menos_repetida(self):
        rondas = [ronda(i + 1, (a, b, "2-0")) for i, (a, b) in enumerate(combinations("abcd", 2))]
        rondas.append(ronda(7, ("a", "b", "2-0"), ("c", "d", "2-0")))
        parejas, _ = engine.emparejar_ronda(list("abcd"), engine.historial_emparejamientos(rondas), set())
        self.assertEqual(len(parejas), 2)
        self.assertNotIn(frozenset("ab"), {frozenset(p) for p in parejas})


class Resultados(unittest.TestCase):
    def test_orden_inverso_invierte_el_resultado(self):
        r = ronda(1, ("a", "b", None), ("c", "d", None), completa=False)
        ok, _, emp, idx = engine.registrar_resultado(r, "b", "2-1", "a")
        self.assertTrue(ok)
        self.assertEqual((emp["resultado"], idx), ("1-2", 0))
        self.assertFalse(r["completa"])

    def test_la_ultima_partida_completa_la_ronda(self):
        r = ronda(1, ("a", "b", "2-0"), ("c", "d", None), ("e", None, None), completa=False)
        engine.registrar_resultado(r, "c", "1-1", "d")
        self.assertTrue(r["completa"])

    def test_errores(self):
        r = ronda(1, ("a", "b", "2-0"), ("c", "d", None), completa=False)
        self.assertEqual(engine.registrar_resultado(r, "a", "2-0", "c")[1], "Ese partido no existe en la ronda actual.")
        self.assertEqual(engine.registrar_resultado(r, "a", "2-0", "b")[1], "Este partido ya tiene un resultado reportado.")
        r["completa"] = True
        self.assertEqual(engine.registrar_resultado(r, "c", "2-0", "d")[1], "La ronda actual ya está completa.")

    def test_ids_numericos(self):
        r = ronda(1, ("111", "222", None), completa=False)
        self.assertTrue(engine.registrar_resultado(r, 222, "2-0", 111)[0])
        self.assertEqual(r["emparejamientos"][0]["resultado"], "0-2")

    def test_partida_pendiente_de(self):
        r = ronda(1, ("a", "b", "2-0"), ("c", "d", None), ("e", None, None), completa=False)
        self.assertEqual(engine.partida_pendiente_de(r, "d")["j1"], "c")
        self.assertIsNone(engine.partida_pendiente_de(r, "a"))
        self.assertIsNone(engine.partida_pendiente_de(r, "e"))
        self.assertIsNone(engine.partida_pendiente_de(None, "a"))


if __name__ == "__main__":
    unittest.main()
