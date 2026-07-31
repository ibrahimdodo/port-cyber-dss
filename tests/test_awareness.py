"""Tests for the risk-driven awareness assessment.

The claim this module makes is that the training is generated from the port's
own risk ranking and that the measurement feeds back into the model. Both are
testable, and both would be easy to fake, so they are tested directly.
"""

import unittest

from portscra.awareness import (
    HUMAN_FACTOR_WEIGHT,
    MANAGEMENT,
    VIGNETTES,
    apply_awareness,
    awareness_multiplier,
    score_responses,
    vignettes_for,
)
from portscra.risk.distributions import Constant
from portscra.risk.economics import RONNE_2024, OutageCostPerHour
from portscra.risk.montecarlo import LossMagnitude, Scenario
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES, build_scenarios

ALL_CORRECT = {v.id: v.correct_index for v in VIGNETTES}
ALL_WRONG = {
    v.id: next(i for i in range(len(v.options)) if i != v.correct_index)
    for v in VIGNETTES
}


class TestVignetteCatalogue(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [v.id for v in VIGNETTES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_vignette_has_exactly_one_correct_option(self):
        for vignette in VIGNETTES:
            correct = [o for o in vignette.options if o.correct]
            self.assertEqual(len(correct), 1,
                             f"{vignette.id} has {len(correct)} correct options")

    def test_every_option_explains_itself(self):
        """The feedback is the training; the score is only the measurement. An
        option with no explanation teaches nothing."""
        for vignette in VIGNETTES:
            for option in vignette.options:
                self.assertTrue(option.feedback.strip(),
                                f"{vignette.id}: an option has no feedback")

    def test_options_are_distinct(self):
        for vignette in VIGNETTES:
            texts = [o.text for o in vignette.options]
            self.assertEqual(len(texts), len(set(texts)), f"{vignette.id} repeats an option")

    def test_no_giveaway_options(self):
        """A quiz whose wrong answers are obviously wrong measures nothing.
        Plausibility is not machine-checkable, but the classic tells are: filler
        options, and absolutes that signal the answer without reading it."""
        tells = ("none of the above", "all of the above", "i don't know",
                 "do nothing", "always ", "never ")
        for vignette in VIGNETTES:
            for option in vignette.options:
                lowered = option.text.lower()
                for tell in tells:
                    self.assertNotIn(tell, lowered,
                                     f"{vignette.id}: option contains the giveaway "
                                     f"{tell!r}")

    def test_the_correct_option_is_not_simply_the_longest(self):
        """The commonest accidental tell in multiple choice: the right answer
        gets the careful wording and the distractors get a clause each."""
        longest_is_correct = sum(
            1 for v in VIGNETTES
            if max(range(len(v.options)), key=lambda i: len(v.options[i].text))
            == v.correct_index
        )
        self.assertLess(longest_is_correct / len(VIGNETTES), 0.75,
                        "the longest option is the correct one too often; a "
                        "respondent could score well without reading")

    def test_correct_answers_are_spread_across_positions(self):
        """If the answer is always in the same slot, position alone scores."""
        positions = {v.correct_index for v in VIGNETTES}
        self.assertGreater(len(positions), 1)

    def test_every_vignette_maps_to_a_real_scenario(self):
        known = {t.id for t in SCENARIO_TEMPLATES}
        for vignette in VIGNETTES:
            self.assertIn(vignette.scenario_id, known, vignette.id)

    def test_every_vignette_cites_nis2(self):
        for vignette in VIGNETTES:
            self.assertTrue(vignette.nis2, f"{vignette.id} cites no NIS2 point")

    def test_every_scenario_has_at_least_one_vignette(self):
        """Otherwise a port whose top risk happens to be uncovered gets no
        training on the thing most likely to hurt it."""
        covered = {v.scenario_id for v in VIGNETTES}
        for template in SCENARIO_TEMPLATES:
            self.assertIn(template.id, covered,
                          f"scenario {template.id} has no vignette")

    def test_management_is_addressed_directly(self):
        """NIS2 Article 20(2) obliges the management body itself to train."""
        self.assertTrue([v for v in VIGNETTES if v.role == MANAGEMENT])


class TestSelection(unittest.TestCase):
    def test_selection_follows_the_risk_ranking(self):
        """The core claim: training leads with what threatens this port."""
        ordered = vignettes_for(["S6", "S3"])
        self.assertEqual(ordered[0].scenario_id, "S6")
        self.assertIn("S3", [v.scenario_id for v in ordered])

    def test_reordering_the_risks_reorders_the_training(self):
        first = vignettes_for(["S3", "S6"])[0].scenario_id
        second = vignettes_for(["S6", "S3"])[0].scenario_id
        self.assertNotEqual(first, second)

    def test_role_filter(self):
        for vignette in vignettes_for(["S3"], role=MANAGEMENT):
            self.assertEqual(vignette.role, MANAGEMENT)

    def test_limit_applies(self):
        self.assertEqual(len(vignettes_for(["S3", "S2", "S4"], limit=2)), 2)

    def test_unknown_scenario_yields_nothing_rather_than_failing(self):
        self.assertEqual(vignettes_for(["nope"]), [])

    def test_top_risks_from_the_real_engine_produce_training(self):
        from portscra.controls.optimiser import scenario_ale
        scenarios = build_scenarios(OutageCostPerHour(RONNE_2024))
        ranked = [s.id for s in sorted(scenarios, key=scenario_ale, reverse=True)]
        selected = vignettes_for(ranked, limit=5)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected[0].scenario_id, ranked[0])


class TestScoring(unittest.TestCase):
    def test_all_correct(self):
        result = score_responses(ALL_CORRECT)
        self.assertEqual(result.overall, 1.0)
        self.assertEqual(result.missed, ())

    def test_all_wrong(self):
        result = score_responses(ALL_WRONG)
        self.assertEqual(result.overall, 0.0)
        self.assertEqual(len(result.missed), len(VIGNETTES))

    def test_partial_answers_are_scored_on_what_was_answered(self):
        """Unanswered vignettes are excluded rather than counted wrong --
        otherwise coverage and competence get conflated."""
        subset = {v.id: v.correct_index for v in VIGNETTES[:3]}
        result = score_responses(subset)
        self.assertEqual(result.answered, 3)
        self.assertEqual(result.overall, 1.0)

    def test_per_scenario_and_per_role_breakdowns(self):
        result = score_responses(ALL_CORRECT)
        self.assertTrue(result.per_scenario)
        self.assertTrue(result.per_role)
        for value in result.per_scenario.values():
            self.assertEqual(value, 1.0)

    def test_weakest_scenarios_are_identified(self):
        responses = dict(ALL_CORRECT)
        for vignette in VIGNETTES:
            if vignette.scenario_id == "S3":
                responses[vignette.id] = ALL_WRONG[vignette.id]
        weakest = score_responses(responses).weakest_scenarios(1)
        self.assertEqual(weakest[0][0], "S3")

    def test_management_gap_is_surfaced(self):
        """An organisational average can look healthy while the people carrying
        the legal duty are the weakest group."""
        responses = dict(ALL_CORRECT)
        for vignette in VIGNETTES:
            if vignette.role == MANAGEMENT:
                responses[vignette.id] = ALL_WRONG[vignette.id]
        result = score_responses(responses)
        gap = result.management_gap()
        self.assertIsNotNone(gap)
        self.assertAlmostEqual(gap, 1.0)

    def test_no_gap_when_everyone_scores_alike(self):
        self.assertAlmostEqual(score_responses(ALL_CORRECT).management_gap(), 0.0)

    def test_rejects_unknown_vignette(self):
        with self.assertRaises(ValueError):
            score_responses({"nope": 0})

    def test_rejects_out_of_range_answer(self):
        with self.assertRaises(ValueError):
            score_responses({VIGNETTES[0].id: 99})


class TestFeedbackIntoTheModel(unittest.TestCase):
    def test_average_awareness_is_neutral(self):
        """A score of 0.5 must leave the frequency alone: the base rate already
        reflects organisations of average awareness."""
        result = score_responses(ALL_CORRECT)
        neutral = type(result)(per_scenario={"S3": 0.5}, per_role={},
                               answered=1, correct=1)
        self.assertAlmostEqual(awareness_multiplier(neutral, "S3"), 1.0)

    def test_good_awareness_lowers_frequency(self):
        result = score_responses(ALL_CORRECT)
        self.assertLess(awareness_multiplier(result, "S3"), 1.0)

    def test_poor_awareness_raises_frequency(self):
        result = score_responses(ALL_WRONG)
        self.assertGreater(awareness_multiplier(result, "S3"), 1.0)

    def test_effect_is_proportional_to_human_involvement(self):
        """Training must move invoice fraud a long way and a signed trojanized
        update barely at all. A tool that improved every risk equally would be
        selling training rather than measuring it."""
        result = score_responses(ALL_CORRECT)
        human = 1.0 - awareness_multiplier(result, "S3")   # weight 0.60
        technical = 1.0 - awareness_multiplier(result, "S1")  # weight 0.05
        self.assertGreater(human, technical * 5)

    def test_unassessed_scenario_is_neutral_not_improved(self):
        """Not assessing something is not an improvement in it."""
        result = score_responses({VIGNETTES[0].id: VIGNETTES[0].correct_index})
        self.assertAlmostEqual(awareness_multiplier(result, "S9-unknown"), 1.0)

    def test_weights_cover_every_scenario(self):
        for template in SCENARIO_TEMPLATES:
            self.assertIn(template.id, HUMAN_FACTOR_WEIGHT)

    def test_apply_awareness_changes_expected_loss(self):
        """The closed loop: train the staff, and the risk figures move."""
        from portscra.controls.optimiser import baseline_ale
        scenarios = build_scenarios(OutageCostPerHour(RONNE_2024))
        good = apply_awareness(scenarios, score_responses(ALL_CORRECT))
        bad = apply_awareness(scenarios, score_responses(ALL_WRONG))
        self.assertLess(baseline_ale(good), baseline_ale(scenarios))
        self.assertGreater(baseline_ale(bad), baseline_ale(scenarios))

    def test_apply_awareness_does_not_mutate_inputs(self):
        scenarios = build_scenarios(OutageCostPerHour(RONNE_2024))
        before = scenarios[0].loss_event_frequency.mean
        apply_awareness(scenarios, score_responses(ALL_WRONG))
        self.assertEqual(scenarios[0].loss_event_frequency.mean, before)

    def test_works_on_vendor_derived_frequencies(self):
        """Awareness must compose with derived frequencies, not only PERTs."""
        from portscra.examples import EXAMPLE_VENDORS
        from portscra.graph import DependencyGraph, build_scenarios_from_vendors
        from portscra.vendor import LikelihoodModel

        cost = OutageCostPerHour(RONNE_2024)
        model = LikelihoodModel()
        graph = DependencyGraph(EXAMPLE_VENDORS)
        assessments = {v.key: model.assess(v) for v in EXAMPLE_VENDORS}
        derived = build_scenarios_from_vendors(
            graph, assessments, cost, fallback_scenarios=build_scenarios(cost))
        adjusted = apply_awareness(derived, score_responses(ALL_WRONG))
        self.assertEqual(len(adjusted), len(derived))


if __name__ == "__main__":
    unittest.main()
