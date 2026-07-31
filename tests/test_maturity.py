"""Tests for the ENISA phase-four maturity assessment."""

import unittest

from portscra.controls import CATALOGUE
from portscra.maturity import (
    LEVEL_NAMES,
    MEASURES,
    assess_maturity,
    find_measure,
    maturity_from_controls,
)


class TestMeasures(unittest.TestCase):
    def test_codes_are_unique(self):
        codes = [m.code for m in MEASURES]
        self.assertEqual(len(codes), len(set(codes)))

    def test_all_three_enisa_categories_present(self):
        self.assertEqual({m.category for m in MEASURES},
                         {"policies", "organisational", "technical"})

    def test_every_measure_defines_all_three_levels(self):
        for measure in MEASURES:
            self.assertEqual(set(measure.evidence), {1, 2, 3}, measure.code)
            for text in measure.evidence.values():
                self.assertTrue(text.strip())

    def test_every_referenced_control_exists(self):
        """A ceiling pointing at a control that is not in the catalogue would
        silently never fire."""
        known = {c.id for c in CATALOGUE}
        for measure in MEASURES:
            for control in measure.control_ceiling:
                self.assertIn(control, known,
                              f"{measure.code} references unknown control {control}")

    def test_ceilings_are_valid_levels(self):
        for measure in MEASURES:
            for control, ceiling in measure.control_ceiling.items():
                self.assertIn(ceiling, (1, 2, 3), f"{measure.code}/{control}")

    def test_supply_chain_measures_are_identified(self):
        """The DSS's actual scope is narrower than ENISA's catalogue, and
        pretending otherwise would inflate the result."""
        self.assertTrue([m for m in MEASURES if m.supply_chain])
        self.assertTrue([m for m in MEASURES if not m.supply_chain])

    def test_lookup(self):
        self.assertIsNotNone(find_measure("PS-01"))
        self.assertIsNone(find_measure("XX-99"))


class TestAssessment(unittest.TestCase):
    def test_unmentioned_measures_score_zero(self):
        """Otherwise a port raises its score by assessing only what it does well."""
        profile = assess_maturity({"PS-01": 3})
        self.assertEqual(profile.levels["PS-01"], 3)
        self.assertEqual(profile.levels["TM-02"], 0)
        self.assertLess(profile.overall, 3)

    def test_overall_and_category_scores(self):
        profile = assess_maturity({m.code: 2 for m in MEASURES})
        self.assertAlmostEqual(profile.overall, 2.0)
        for score in profile.by_category().values():
            self.assertAlmostEqual(score, 2.0)

    def test_supply_chain_score_is_reported_separately(self):
        """A port can be mature overall and weak exactly where suppliers reach it."""
        levels = {m.code: (0 if m.supply_chain else 3) for m in MEASURES}
        profile = assess_maturity(levels)
        self.assertEqual(profile.supply_chain_score(), 0.0)
        self.assertGreater(profile.overall, 0.0)

    def test_gaps_are_ranked_worst_first(self):
        profile = assess_maturity({"PS-01": 2, "TM-02": 1})
        gaps = profile.gaps(target=2)
        self.assertTrue(gaps)
        self.assertEqual(gaps, sorted(gaps, key=lambda kv: kv[1]))

    def test_rejects_unknown_measure(self):
        with self.assertRaises(ValueError):
            assess_maturity({"XX-99": 1})

    def test_rejects_out_of_range_level(self):
        with self.assertRaises(ValueError):
            assess_maturity({"PS-01": 4})

    def test_describe_is_readable(self):
        text = assess_maturity({m.code: 2 for m in MEASURES}).describe()
        self.assertIn("Overall maturity", text)
        self.assertIn("supply-chain", text)


class TestControlLinkage(unittest.TestCase):
    def test_no_controls_means_no_maturity(self):
        self.assertEqual(maturity_from_controls([]).overall, 0.0)

    def test_buying_controls_raises_maturity(self):
        few = maturity_from_controls(["C01"])
        many = maturity_from_controls([c.id for c in CATALOGUE])
        self.assertGreater(many.overall, few.overall)

    def test_the_highest_ceiling_wins(self):
        """C01 carries access control to 2, C03 to 3."""
        self.assertEqual(maturity_from_controls(["C01"]).levels["TM-02"], 2)
        self.assertEqual(maturity_from_controls(["C01", "C03"]).levels["TM-02"], 3)

    def test_buying_everything_does_not_reach_full_marks(self):
        """ENISA is explicit that maturity cannot be achieved through a checklist
        mentality. Level 3 needs oversight, testing and continuous improvement,
        which purchasing a control does not confer."""
        profile = maturity_from_controls([c.id for c in CATALOGUE])
        self.assertLess(profile.overall, 3.0)

    def test_an_optimised_portfolio_produces_a_profile(self):
        from portscra.controls import optimise
        from portscra.risk import RONNE_2024, OutageCostPerHour
        from portscra.taxonomy import build_scenarios

        portfolio = optimise(build_scenarios(OutageCostPerHour(RONNE_2024)),
                             CATALOGUE, 25_000)
        profile = maturity_from_controls([c.id for c in portfolio.controls])
        self.assertGreater(profile.overall, 0.0)
        self.assertGreater(profile.supply_chain_score(), 0.0)

    def test_level_names_cover_every_level(self):
        for level in (0, 1, 2, 3):
            self.assertIn(level, LEVEL_NAMES)
