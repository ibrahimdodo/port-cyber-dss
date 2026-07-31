"""Tests for the validation suite.

The suite exists to tell the truth about the model, so these tests mostly check
that it cannot flatter it: that anchoring incidents are kept separate from
held-out ones, that a miscalibrated model actually fails the replay, and that
the matrix baseline is a fair opponent rather than a straw man.
"""

import unittest

from portscra.controls.catalogue import CATALOGUE
from portscra.controls.optimiser import scenario_ale
from portscra.risk.distributions import Constant, PERT
from portscra.risk.economics import RONNE_2024, OutageCostPerHour
from portscra.risk.montecarlo import LossMagnitude, Scenario
from portscra.taxonomy.scenarios import build_scenarios
from portscra.validation import (
    INCIDENTS,
    Incident,
    compare_to_matrix,
    matrix_led_portfolio,
    qualitative_score,
    range_compression,
    rank_agreement,
    replay_incident,
)


def scenario(sid="S2", hours=PERT(24, 60, 336), disruption=1.0,
             lef=0.1, rate=659.0, response=0.0):
    return Scenario(
        id=sid, name=f"scenario {sid}",
        loss_event_frequency=Constant(lef),
        loss_magnitude=LossMagnitude(
            downtime_hours=hours,
            cost_per_hour=Constant(rate),
            response_cost=Constant(response),
            disruption_probability=disruption,
        ),
    )


class TestIncidentCatalogue(unittest.TestCase):
    def test_every_incident_cites_a_source(self):
        for incident in INCIDENTS:
            self.assertTrue(incident.source.strip(), f"{incident.name} has no source")

    def test_every_incident_targets_a_real_scenario(self):
        known = {s.id for s in build_scenarios(OutageCostPerHour(RONNE_2024))}
        for incident in INCIDENTS:
            self.assertIn(incident.scenario_id, known, incident.name)

    def test_anchors_and_held_out_are_both_present(self):
        """A validation set with no held-out incidents proves nothing, and one
        with no anchors would mean the estimates came from nowhere."""
        anchors = [i for i in INCIDENTS if i.used_as_anchor]
        held_out = [i for i in INCIDENTS if not i.used_as_anchor]
        self.assertTrue(anchors)
        self.assertTrue(held_out)

    def test_held_out_incidents_outnumber_anchors(self):
        anchors = sum(1 for i in INCIDENTS if i.used_as_anchor)
        held_out = sum(1 for i in INCIDENTS if not i.used_as_anchor)
        self.assertGreater(held_out, anchors)


class TestReplay(unittest.TestCase):
    def test_incident_at_the_mode_lands_mid_distribution(self):
        r = replay_incident(scenario(), Incident("t", 2020, 60.0, "S2", "test"))
        self.assertTrue(r.inside_band)
        self.assertGreater(r.percentile, 20)
        self.assertLess(r.percentile, 80)

    def test_a_miscalibrated_model_fails(self):
        """The check must be capable of failing, or it is decoration. A model
        whose downtime floor is 24 hours cannot produce a zero-downtime
        incident, and the replay has to say so."""
        r = replay_incident(
            scenario(hours=PERT(24, 60, 336), disruption=1.0),
            Incident("no outage", 2018, 0.0, "S2", "test"),
        )
        self.assertFalse(r.inside_band)
        self.assertEqual(r.verdict, "BELOW P10")

    def test_the_disruption_gate_admits_zero_outcomes(self):
        """The fix the replay forced: separating 'an incident happened' from
        'operations stopped' lets the model produce the observed outcome."""
        r = replay_incident(
            scenario(hours=PERT(24, 60, 336), disruption=0.67),
            Incident("no outage", 2018, 0.0, "S2", "test"),
        )
        self.assertTrue(r.inside_band)

    def test_gate_rate_matches_the_zero_fraction(self):
        """A disruption probability of p must produce no-downtime outcomes
        about (1 - p) of the time -- the calibration claim the report makes."""
        import numpy as np
        lm = scenario(disruption=0.67).loss_magnitude
        draws = lm.sample_downtime(np.random.default_rng(1), 200_000)
        self.assertAlmostEqual((draws == 0).mean(), 0.33, delta=0.01)

    def test_an_absurd_incident_is_flagged_above(self):
        r = replay_incident(scenario(), Incident("x", 2020, 5_000.0, "S2", "test"))
        self.assertFalse(r.inside_band)
        self.assertEqual(r.verdict, "ABOVE P90")


class TestMatrixBaseline(unittest.TestCase):
    def setUp(self):
        self.scenarios = build_scenarios(OutageCostPerHour(RONNE_2024))

    def test_scores_are_within_the_five_by_five_grid(self):
        for s in self.scenarios:
            score = qualitative_score(s)
            self.assertIn(score.likelihood, range(1, 6))
            self.assertIn(score.impact, range(1, 6))
            self.assertIn(score.rating, {"Low", "Medium", "High", "Critical"})

    def test_higher_frequency_raises_the_likelihood_band(self):
        low = qualitative_score(scenario(lef=0.01))
        high = qualitative_score(scenario(lef=2.0))
        self.assertLess(low.likelihood, high.likelihood)

    def test_higher_magnitude_raises_the_impact_band(self):
        small = qualitative_score(scenario(hours=Constant(1)))
        large = qualitative_score(scenario(hours=Constant(2_000)))
        self.assertLess(small.impact, large.impact)

    def test_range_compression_is_demonstrated(self):
        """Cox's objection, made concrete: the matrix should be shown grouping
        scenarios whose expected losses differ substantially."""
        grouped = range_compression(self.scenarios)
        crowded = [ids for ids in grouped.values() if len(ids) > 1]
        self.assertTrue(crowded, "no rating holds more than one scenario")

        by_id = {s.id: s for s in self.scenarios}
        worst_spread = 0.0
        for ids in crowded:
            ales = sorted(scenario_ale(by_id[i]) for i in ids)
            if ales[0] > 0:
                worst_spread = max(worst_spread, ales[-1] / ales[0])
        self.assertGreater(worst_spread, 2.0,
                           "scenarios sharing a rating differ by under 2x, so "
                           "range compression is not demonstrated here")

    def test_matrix_is_a_fair_opponent_not_a_straw_man(self):
        """The matrix orders risks broadly sensibly. If it did not, beating it
        would prove nothing -- the interesting claim is that a method can rank
        well and still allocate badly."""
        self.assertGreater(rank_agreement(self.scenarios), 0.5)

    def test_matrix_portfolio_respects_the_budget(self):
        for budget in (5_000, 25_000, 60_000):
            chosen = matrix_led_portfolio(self.scenarios, CATALOGUE, budget)
            self.assertLessEqual(sum(c.annual_cost_eur for c in chosen), budget)

    def test_matrix_portfolio_has_no_duplicates(self):
        chosen = matrix_led_portfolio(self.scenarios, CATALOGUE, 60_000)
        ids = [c.id for c in chosen]
        self.assertEqual(len(ids), len(set(ids)))

    def test_optimiser_never_loses_to_the_matrix(self):
        """The claim the report makes. Optimising cannot do worse, since the
        matrix portfolio is always available to the optimiser."""
        for budget in (10_000, 15_000, 25_000, 40_000, 60_000):
            c = compare_to_matrix(self.scenarios, CATALOGUE, budget)
            self.assertLessEqual(
                c.quantitative_residual, c.matrix_residual + 1e-6,
                f"optimiser lost to the matrix at budget {budget}",
            )

    def test_optimiser_advantage_is_material_somewhere(self):
        """If optimising never made a difference the machinery would not earn
        its cost. Checked across budgets rather than at one, since agreement at
        a single point would be coincidence."""
        advantages = [
            compare_to_matrix(self.scenarios, CATALOGUE, b).advantage
            for b in (10_000, 15_000, 25_000, 40_000)
        ]
        self.assertGreater(max(advantages), 1_000)

    def test_comparison_reports_both_portfolios(self):
        c = compare_to_matrix(self.scenarios, CATALOGUE, 25_000)
        self.assertTrue(c.matrix_controls)
        self.assertTrue(c.quantitative_controls)
        self.assertGreater(c.baseline, 0)


class TestRankAgreement(unittest.TestCase):
    def test_identical_ordering_gives_one(self):
        scenarios = [
            scenario("A", lef=0.01, hours=Constant(1)),
            scenario("B", lef=0.5, hours=Constant(100)),
            scenario("C", lef=2.0, hours=Constant(1_000)),
        ]
        self.assertAlmostEqual(rank_agreement(scenarios), 1.0, places=6)

    def test_handles_ties_without_dividing_by_zero(self):
        scenarios = [scenario("A"), scenario("B"), scenario("C")]
        self.assertEqual(rank_agreement(scenarios), 0.0)


if __name__ == "__main__":
    unittest.main()
