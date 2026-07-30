"""Integrity tests for the ENISA-derived taxonomies and the scenario catalogue.

These guard against the failure mode that matters most in a knowledge-heavy
module: a scenario that references an asset or threat key which does not exist,
so it silently contributes nothing. Cheap to test, expensive to discover late.
"""

import unittest

from portscra.risk.distributions import PERT
from portscra.taxonomy.assets import (
    ASSET_TAXONOMY,
    Relevance,
    find_asset,
    supply_chain_assets,
)
from portscra.taxonomy.scenarios import (
    SCENARIO_TEMPLATES,
    build_scenarios,
    stride_coverage,
)
from portscra.taxonomy.threats import (
    IMPACTS,
    SUPPLY_CHAIN_THREATS,
    THREAT_TAXONOMY,
    find_impact,
    find_threat,
)


class TestAssetTaxonomy(unittest.TestCase):
    def test_has_the_ten_enisa_categories(self):
        """ENISA 2019 section 3.1 identifies ten asset categories."""
        self.assertEqual(len(ASSET_TAXONOMY), 10)

    def test_keys_are_unique(self):
        keys = [s.key for c in ASSET_TAXONOMY for s in c.subcategories]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_subcategory_is_documented(self):
        for category in ASSET_TAXONOMY:
            for sub in category.subcategories:
                self.assertTrue(sub.description.strip(), f"{sub.key} lacks a description")
                self.assertTrue(sub.name.strip())

    def test_lookup(self):
        self.assertIsNotNone(find_asset("tos"))
        self.assertIsNone(find_asset("does_not_exist"))

    def test_supply_chain_filter_narrows_the_scope(self):
        """The HIGH subset must be a genuine narrowing -- otherwise the filter
        is not doing the scoping job it exists for."""
        everything = [s for c in ASSET_TAXONOMY for s in c.subcategories]
        high = supply_chain_assets(Relevance.HIGH)
        self.assertGreater(len(high), 0)
        self.assertLess(len(high), len(everything))

    def test_relevance_threshold_is_ordered(self):
        high = len(supply_chain_assets(Relevance.HIGH))
        medium = len(supply_chain_assets(Relevance.MEDIUM))
        low = len(supply_chain_assets(Relevance.LOW))
        self.assertLessEqual(high, medium)
        self.assertLessEqual(medium, low)

    def test_purely_physical_assets_are_excluded(self):
        """Floating barriers have no software supply chain; modelling them
        would pad the inventory with rows that can never carry risk."""
        barriers = find_asset("floating_barriers")
        self.assertEqual(barriers.supply_chain_relevance, Relevance.NONE)


class TestThreatTaxonomy(unittest.TestCase):
    def test_keys_are_unique(self):
        keys = [t.key for c in THREAT_TAXONOMY for t in c.threats]
        self.assertEqual(len(keys), len(set(keys)))

    def test_supply_chain_subset_is_a_real_narrowing(self):
        total = sum(len(c.threats) for c in THREAT_TAXONOMY)
        subset = SUPPLY_CHAIN_THREATS()
        self.assertGreater(len(subset), 0)
        self.assertLess(len(subset), total)

    def test_notpetya_threat_is_marked_as_supply_chain(self):
        """ENISA files NotPetya under 'use of unreliable source'. That entry is
        the supply-chain attack in ENISA's own vocabulary, and the scoping
        depends on it being flagged."""
        threat = find_threat("unreliable_source")
        self.assertIsNotNone(threat)
        self.assertTrue(threat.supply_chain_vector)

    def test_impacts_map_to_known_loss_components(self):
        valid = {"outage", "response", "secondary", "non_financial"}
        for impact in IMPACTS:
            self.assertIn(impact.loss_component, valid)

    def test_impact_lookup(self):
        self.assertIsNotNone(find_impact("operations_shutdown"))
        self.assertIsNone(find_impact("nope"))


class TestScenarioCatalogue(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [t.id for t in SCENARIO_TEMPLATES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_referenced_threat_exists(self):
        for template in SCENARIO_TEMPLATES:
            for key in template.enisa_threats:
                self.assertIsNotNone(find_threat(key),
                                     f"{template.id} references unknown threat {key!r}")

    def test_every_referenced_impact_exists(self):
        for template in SCENARIO_TEMPLATES:
            for key in template.enisa_impacts:
                self.assertIsNotNone(find_impact(key),
                                     f"{template.id} references unknown impact {key!r}")

    def test_every_referenced_asset_exists(self):
        for template in SCENARIO_TEMPLATES:
            for key in template.target_assets:
                self.assertIsNotNone(find_asset(key),
                                     f"{template.id} references unknown asset {key!r}")

    def test_every_scenario_has_attack_techniques_and_an_anchor(self):
        """A scenario without a real incident behind it is speculation, and
        without ATT&CK identifiers it cannot be mapped to mitigations later."""
        for template in SCENARIO_TEMPLATES:
            self.assertTrue(template.attack_techniques, f"{template.id} has no ATT&CK IDs")
            self.assertTrue(template.incident_anchor.strip(),
                            f"{template.id} has no incident anchor")

    def test_stride_completeness_audit(self):
        """Every STRIDE category should appear somewhere in the catalogue. A
        gap is not automatically a defect, but it is a question to answer."""
        coverage = stride_coverage()
        uncovered = [c for c, scenarios in coverage.items() if not scenarios]
        self.assertEqual(uncovered, [], f"STRIDE categories with no scenario: {uncovered}")

    def test_build_produces_usable_scenarios(self):
        scenarios = build_scenarios(PERT(1000, 3000, 8000))
        self.assertEqual(len(scenarios), len(SCENARIO_TEMPLATES))
        for scenario in scenarios:
            self.assertGreater(scenario.loss_event_frequency.mean, 0)
            self.assertTrue(scenario.attack_techniques)

    def test_every_estimate_carries_its_source(self):
        """An estimate without provenance is a guess wearing a lab coat. This
        is the test that keeps the methodology section honest."""
        for scenario in build_scenarios(PERT(1000, 3000, 8000)):
            lm = scenario.loss_magnitude
            for label, dist in (
                ("frequency", scenario.loss_event_frequency),
                ("downtime", lm.downtime_hours),
                ("response", lm.response_cost),
                ("secondary", lm.secondary_loss),
            ):
                if dist is not None:
                    self.assertTrue(
                        getattr(dist, "source", "").strip(),
                        f"{scenario.id} {label} estimate has no source",
                    )

    def test_scale_reduces_costs_for_smaller_personas(self):
        big = build_scenarios(PERT(1000, 3000, 8000), scale=1.0)
        small = build_scenarios(PERT(1000, 3000, 8000), scale=0.3)
        self.assertLess(
            small[0].loss_magnitude.response_cost.mean,
            big[0].loss_magnitude.response_cost.mean,
        )


if __name__ == "__main__":
    unittest.main()
