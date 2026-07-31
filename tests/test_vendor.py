"""Tests for the questionnaire and the vendor likelihood fusion.

The behaviours that matter are directional and structural rather than exact:
worse answers must raise risk, adverse signals must raise it further, absence of
evidence must not be rewarded, and every question must map to something real in
the taxonomy and in NIS2.
"""

import unittest

from portscra.taxonomy.assets import find_asset
from portscra.vendor.likelihood import (
    BASE_RATE,
    LikelihoodModel,
    Vendor,
    VendorSignals,
)
from portscra.vendor.questionnaire import (
    CRITERIA,
    DEFAULT_WEIGHTS,
    QUESTIONS,
    nis2_coverage,
    questions_for,
)


def answers(value: int) -> dict[str, int]:
    """Answer every question with the same option index."""
    return {q.id: min(value, len(q.options) - 1) for q in QUESTIONS}


BEST = {q.id: len(q.options) - 1 for q in QUESTIONS}
WORST = {q.id: 0 for q in QUESTIONS}


class TestQuestionnaire(unittest.TestCase):
    def test_question_ids_are_unique(self):
        ids = [q.id for q in QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_question_belongs_to_a_known_criterion(self):
        keys = {c.key for c in CRITERIA}
        for question in QUESTIONS:
            self.assertIn(question.criterion, keys, f"{question.id} has an unknown criterion")

    def test_every_criterion_has_questions(self):
        for criterion in CRITERIA:
            self.assertTrue(questions_for(criterion.key),
                            f"criterion {criterion.key} has no questions")

    def test_scoring_runs_worst_to_best(self):
        """Option 0 is the worst case and scores 1.0; the last option scores 0."""
        for question in QUESTIONS:
            self.assertAlmostEqual(question.score(0), 1.0)
            self.assertAlmostEqual(question.score(len(question.options) - 1), 0.0)

    def test_scores_decrease_monotonically(self):
        for question in QUESTIONS:
            scores = [question.score(i) for i in range(len(question.options))]
            self.assertEqual(scores, sorted(scores, reverse=True), question.id)

    def test_rejects_out_of_range_answers(self):
        question = QUESTIONS[0]
        with self.assertRaises(ValueError):
            question.score(len(question.options))
        with self.assertRaises(ValueError):
            question.score(-1)

    def test_every_question_cites_a_nis2_point(self):
        """A question that maps to nothing in the directive is not earning its
        place in a questionnaire a supplier has to fill in."""
        valid = set("abcdefghij")
        for question in QUESTIONS:
            self.assertTrue(question.nis2, f"{question.id} cites no NIS2 point")
            for point in question.nis2:
                self.assertIn(point, valid, f"{question.id} cites bad point {point!r}")

    def test_default_weights_are_normalised_and_complete(self):
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS.values()), 1.0, places=6)
        self.assertEqual(set(DEFAULT_WEIGHTS), {c.key for c in CRITERIA})

    def test_nis2_coverage_maps_supply_chain_point(self):
        """21(2)(d) is the supply-chain obligation this whole tool addresses;
        it must be covered."""
        coverage = nis2_coverage()
        supply_chain = next(k for k in coverage if "21(2)(d)" in k)
        self.assertTrue(coverage[supply_chain])


class TestLikelihood(unittest.TestCase):
    def setUp(self):
        self.model = LikelihoodModel()

    def test_worse_answers_produce_higher_probability(self):
        good = self.model.assess(Vendor("a", "Good", "SaaS", answers=BEST))
        bad = self.model.assess(Vendor("b", "Bad", "SaaS", answers=WORST))
        self.assertGreater(bad.annual_probability.mean, good.annual_probability.mean)

    def test_posture_bounds(self):
        good = self.model.assess(Vendor("a", "Good", "SaaS", answers=BEST))
        bad = self.model.assess(Vendor("b", "Bad", "SaaS", answers=WORST))
        self.assertAlmostEqual(good.posture_score, 0.0, places=6)
        self.assertAlmostEqual(bad.posture_score, 1.0, places=6)

    def test_multiplier_respects_the_configured_range(self):
        low, high = self.model.exposure_range
        good = self.model.assess(Vendor("a", "Good", "SaaS", answers=BEST))
        bad = self.model.assess(Vendor("b", "Bad", "SaaS", answers=WORST))
        self.assertAlmostEqual(good.exposure_multiplier, low, places=6)
        self.assertAlmostEqual(bad.exposure_multiplier, high, places=6)

    def test_unassessed_vendor_lands_mid_range_not_best(self):
        """No evidence must not mean no risk -- otherwise the cheapest way to
        look safe is to refuse the questionnaire."""
        unknown = self.model.assess(Vendor("u", "Unknown", "freeware"))
        good = self.model.assess(Vendor("a", "Good", "SaaS", answers=BEST))
        self.assertAlmostEqual(unknown.posture_score, 0.5, places=6)
        self.assertGreater(unknown.annual_probability.mean, good.annual_probability.mean)

    def test_partial_answers_are_judged_on_what_was_answered(self):
        """A vendor answering only the access questions badly must not be
        credited for the questions it skipped."""
        access_only = {q.id: 0 for q in questions_for("access")}
        assessment = self.model.assess(Vendor("p", "Partial", "MSP", answers=access_only))
        self.assertAlmostEqual(assessment.posture_score, 1.0, places=6)
        self.assertEqual(set(assessment.criterion_scores), {"access"})

    def test_coverage_is_reported(self):
        access_only = {q.id: 0 for q in questions_for("access")}
        assessment = self.model.assess(Vendor("p", "Partial", "MSP", answers=access_only))
        self.assertLess(assessment.coverage, 1.0)
        self.assertGreater(assessment.coverage, 0.0)
        full = self.model.assess(Vendor("f", "Full", "SaaS", answers=BEST))
        self.assertAlmostEqual(full.coverage, 1.0)

    def test_kev_entry_raises_risk(self):
        """Appearing in CISA KEV means exploitation is observed, not theoretical."""
        base = Vendor("a", "V", "SaaS", answers=answers(2))
        flagged = Vendor("b", "V", "SaaS", answers=answers(2),
                         signals=VendorSignals(kev_count=2))
        self.assertGreater(
            self.model.assess(flagged).annual_probability.mean,
            self.model.assess(base).annual_probability.mean,
        )

    def test_high_epss_raises_risk(self):
        base = Vendor("a", "V", "SaaS", answers=answers(2))
        risky = Vendor("b", "V", "SaaS", answers=answers(2),
                       signals=VendorSignals(max_epss=0.6))
        self.assertGreater(
            self.model.assess(risky).annual_probability.mean,
            self.model.assess(base).annual_probability.mean,
        )

    def test_recent_breach_raises_risk(self):
        base = Vendor("a", "V", "SaaS", answers=answers(2))
        breached = Vendor("b", "V", "SaaS", answers=answers(2),
                          signals=VendorSignals(recent_breach=True))
        self.assertGreater(
            self.model.assess(breached).annual_probability.mean,
            self.model.assess(base).annual_probability.mean,
        )

    def test_good_openssf_score_lowers_risk_slightly(self):
        """The freeware case: no questionnaire is possible, so Scorecard is the
        only evidence available."""
        neutral = Vendor("a", "lib", "freeware", answers=answers(2))
        healthy = Vendor("b", "lib", "freeware", answers=answers(2),
                         signals=VendorSignals(openssf_scorecard=9.0))
        self.assertLess(
            self.model.assess(healthy).annual_probability.mean,
            self.model.assess(neutral).annual_probability.mean,
        )

    def test_signal_absence_is_weaker_evidence_than_signal_presence(self):
        """Not being in KEV barely helps; being in it hurts a lot. Most software
        never receives the scrutiny that would put it there."""
        model = self.model
        neutral = model.assess(Vendor("a", "V", "SaaS", answers=answers(2)))
        adverse = model.assess(Vendor("b", "V", "SaaS", answers=answers(2),
                                      signals=VendorSignals(kev_count=3)))
        good_signal = model.assess(Vendor("c", "V", "SaaS", answers=answers(2),
                                          signals=VendorSignals(openssf_scorecard=10.0)))
        rise = adverse.annual_probability.mean / neutral.annual_probability.mean
        fall = neutral.annual_probability.mean / good_signal.annual_probability.mean
        self.assertGreater(rise, fall)

    def test_probability_never_exceeds_one(self):
        extreme = Vendor("x", "Awful", "MSP", answers=WORST,
                         signals=VendorSignals(kev_count=99, max_epss=1.0,
                                               openssf_scorecard=0.0, recent_breach=True))
        p = self.model.assess(extreme).annual_probability
        self.assertLessEqual(p.maximum, 1.0)
        self.assertLessEqual(p.most_likely, p.maximum)

    def test_probability_band_is_a_band_not_a_point(self):
        p = self.model.assess(Vendor("a", "V", "SaaS", answers=answers(2))).annual_probability
        self.assertLess(p.minimum, p.maximum)

    def test_probability_carries_its_derivation(self):
        assessment = self.model.assess(Vendor("a", "Acme", "SaaS", answers=answers(1)))
        self.assertIn("Acme", assessment.annual_probability.source)

    def test_custom_weights_change_the_answer(self):
        """AHP weights must actually matter, or the elicitation is theatre."""
        access_bad = {q.id: 0 for q in questions_for("access")}
        access_bad |= {q.id: len(q.options) - 1 for q in QUESTIONS
                       if q.criterion != "access"}
        vendor = Vendor("v", "V", "MSP", answers=access_bad)

        access_heavy = LikelihoodModel(weights={"access": 0.9, "posture": 0.1})
        posture_heavy = LikelihoodModel(weights={"access": 0.1, "posture": 0.9})
        self.assertGreater(
            access_heavy.assess(vendor).posture_score,
            posture_heavy.assess(vendor).posture_score,
        )

    def test_rejects_unknown_criteria_in_weights(self):
        with self.assertRaises(ValueError):
            LikelihoodModel(weights={"not_a_criterion": 1.0})

    def test_rejects_zero_weights(self):
        with self.assertRaises(ValueError):
            LikelihoodModel(weights={"access": 0.0})

    def test_ranking_is_worst_first(self):
        vendors = [
            Vendor("good", "Good", "SaaS", answers=BEST),
            Vendor("bad", "Bad", "MSP", answers=WORST),
            Vendor("mid", "Mid", "SaaS", answers=answers(2)),
        ]
        ranked = self.model.rank(vendors)
        self.assertEqual(ranked[0].vendor.key, "bad")
        self.assertEqual(ranked[-1].vendor.key, "good")

    def test_explain_is_human_readable(self):
        text = self.model.assess(Vendor("a", "Acme", "SaaS", answers=answers(1))).explain()
        for fragment in ("Acme", "posture score", "P(compromise)/yr", "coverage"):
            self.assertIn(fragment, text)


class TestVendorAssetLinkage(unittest.TestCase):
    def test_supplied_assets_exist_in_the_taxonomy(self):
        """A vendor pointing at an asset key that does not exist would silently
        contribute nothing to the dependency graph."""
        vendor = Vendor("v", "V", "TOS vendor", supplies=("tos", "pcs"))
        for key in vendor.supplies:
            self.assertIsNotNone(find_asset(key), f"unknown asset key {key!r}")


class TestBaseRate(unittest.TestCase):
    def test_base_rate_is_a_plausible_annual_probability(self):
        self.assertGreater(BASE_RATE.minimum, 0.0)
        self.assertLess(BASE_RATE.maximum, 1.0)

    def test_base_rate_cites_its_source(self):
        self.assertTrue(BASE_RATE.source.strip())


if __name__ == "__main__":
    unittest.main()
