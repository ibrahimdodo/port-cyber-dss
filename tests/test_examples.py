"""Integrity tests for the worked example supplier list.

Now that the example lives in the package rather than in a demo script, it is
imported by the pipeline, the dashboard and any notebook. A broken entry would
propagate silently -- a vendor pointing at an asset key that does not exist
contributes nothing to the dependency graph and simply disappears from the
analysis without an error.
"""

import unittest

from portscra.examples import EXAMPLE_VENDORS
from portscra.graph import ASSET_SERVICES, DependencyGraph
from portscra.taxonomy.assets import find_asset
from portscra.vendor.likelihood import LikelihoodModel
from portscra.vendor.questionnaire import QUESTIONS

QUESTION_IDS = {q.id: q for q in QUESTIONS}


class TestExampleVendors(unittest.TestCase):
    def test_keys_are_unique(self):
        keys = [v.key for v in EXAMPLE_VENDORS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_supplied_asset_exists(self):
        for vendor in EXAMPLE_VENDORS:
            for asset in vendor.supplies:
                self.assertIsNotNone(
                    find_asset(asset),
                    f"{vendor.key} supplies unknown asset {asset!r}")

    def test_every_supplied_asset_maps_to_a_service(self):
        """An asset with no service mapping cannot carry operational impact, so
        a vendor supplying only such assets would silently score zero exposure."""
        for vendor in EXAMPLE_VENDORS:
            for asset in vendor.supplies:
                self.assertIn(asset, ASSET_SERVICES,
                              f"{vendor.key}: {asset!r} maps to no port service")

    def test_answer_ids_are_real_questions(self):
        for vendor in EXAMPLE_VENDORS:
            for qid in vendor.answers:
                self.assertIn(qid, QUESTION_IDS,
                              f"{vendor.key} answers unknown question {qid!r}")

    def test_answer_indices_are_in_range(self):
        for vendor in EXAMPLE_VENDORS:
            for qid, index in vendor.answers.items():
                question = QUESTION_IDS[qid]
                self.assertIn(index, range(len(question.options)),
                              f"{vendor.key}/{qid}: option {index} out of range")

    def test_the_freeware_case_has_no_questionnaire(self):
        """The brief's 'freeware?' case: there is no vendor to send a
        questionnaire to, so it must be assessable from public sources alone --
        which means carrying the identifiers those sources are keyed on."""
        oss = next(v for v in EXAMPLE_VENDORS if v.category == "freeware")
        self.assertEqual(oss.answers, {})
        self.assertTrue(oss.cve_ids or oss.repository,
                        "the freeware case has neither questionnaire nor "
                        "identifiers, so nothing could ever assess it")

    def test_no_fabricated_feed_values(self):
        """EPSS scores and KEV hits are things only a feed can report. Typing
        one by hand asserts something we have not looked up, and an earlier
        version of this file did exactly that -- inflating one supplier's risk
        from 7.6% to 13.3% on invented evidence."""
        for vendor in EXAMPLE_VENDORS:
            self.assertIsNone(vendor.signals.max_epss,
                              f"{vendor.key} has a hand-typed EPSS score")
            self.assertEqual(vendor.signals.kev_count, 0,
                             f"{vendor.key} has a hand-typed KEV count")
            self.assertIsNone(vendor.signals.openssf_scorecard,
                              f"{vendor.key} has a hand-typed Scorecard value")

    def test_hand_recorded_signals_are_labelled_illustrative(self):
        """A disclosed breach is legitimately hand-recorded -- no feed reports
        it -- but in a worked example it must still be labelled as illustrative."""
        for vendor in EXAMPLE_VENDORS:
            if vendor.signals.has_any:
                self.assertIn("illustrative", vendor.signals.source.lower(),
                              f"{vendor.key} has unlabelled signals")

    def test_at_least_one_vendor_can_be_enriched(self):
        """Otherwise the live-signal path is never exercised by the example."""
        enrichable = [v for v in EXAMPLE_VENDORS if v.cve_ids or v.repository]
        self.assertTrue(enrichable)

    def test_no_real_company_names(self):
        """Naming real suppliers would assert things about their security
        posture this project has no evidence for."""
        forbidden = ["microsoft", "solarwinds", "kaseya", "navis", "abb",
                     "siemens", "cisco", "fortinet", "moveit"]
        for vendor in EXAMPLE_VENDORS:
            lowered = vendor.name.lower()
            for name in forbidden:
                self.assertNotIn(name, lowered,
                                 f"{vendor.key} names a real company")

    def test_the_list_exercises_the_whole_graph(self):
        """The worked example should reach every scenario, or it is not a
        useful demonstration of the pipeline."""
        graph = DependencyGraph(EXAMPLE_VENDORS)
        from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES
        matched = sum(1 for t in SCENARIO_TEMPLATES if graph.vendors_for_scenario(t))
        self.assertGreaterEqual(matched, len(SCENARIO_TEMPLATES) - 1,
                                "example vendors leave more than one scenario unmatched")

    def test_every_vendor_assesses_without_error(self):
        model = LikelihoodModel()
        for assessment in model.rank(EXAMPLE_VENDORS):
            p = assessment.annual_probability
            self.assertGreater(p.mean, 0.0)
            self.assertLessEqual(p.maximum, 1.0)
