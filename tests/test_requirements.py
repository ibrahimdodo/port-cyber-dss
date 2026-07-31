"""Tests for the supplier security-requirements generator."""

import unittest

from portscra.examples import EXAMPLE_VENDORS
from portscra.requirements import (
    REQUIREMENTS,
    Tier,
    as_clauses,
    requirements_for_assets,
    requirements_for_vendor,
    scenario_requirement_map,
)
from portscra.taxonomy.assets import find_asset
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES
from portscra.vendor.likelihood import Vendor
from portscra.vendor.questionnaire import QUESTIONS

QUESTION_IDS = {q.id for q in QUESTIONS}


class TestCatalogue(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [r.id for r in REQUIREMENTS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_requirement_cites_nis2(self):
        valid = set("abcdefghij")
        for requirement in REQUIREMENTS:
            self.assertTrue(requirement.nis2, f"{requirement.id} cites no NIS2 point")
            for point in requirement.nis2:
                self.assertIn(point, valid, requirement.id)

    def test_every_requirement_has_an_evidence_test(self):
        """A requirement with no way to check it is a statement of hope."""
        for requirement in REQUIREMENTS:
            self.assertTrue(requirement.evidence.strip(),
                            f"{requirement.id} has no evidence test")

    def test_every_requirement_has_contract_text(self):
        """It has to be something procurement can paste into an agreement."""
        for requirement in REQUIREMENTS:
            self.assertGreater(len(requirement.text), 60, requirement.id)
            self.assertTrue(requirement.rationale.strip(), requirement.id)

    def test_verifying_questions_exist(self):
        for requirement in REQUIREMENTS:
            for question_id in requirement.verified_by:
                self.assertIn(question_id, QUESTION_IDS,
                              f"{requirement.id} verifies against unknown {question_id}")

    def test_referenced_assets_exist(self):
        for requirement in REQUIREMENTS:
            for key in requirement.asset_keys:
                self.assertIsNotNone(find_asset(key),
                                     f"{requirement.id} names unknown asset {key!r}")

    def test_referenced_scenarios_exist(self):
        known = {t.id for t in SCENARIO_TEMPLATES}
        for requirement in REQUIREMENTS:
            for sid in requirement.scenarios:
                self.assertIn(sid, known, requirement.id)

    def test_essential_tier_stays_short_enough_to_negotiate(self):
        """A small port has no leverage to impose everything on everyone. If the
        essential list is long, the important clauses get traded away with the
        trivial ones."""
        essential = [r for r in REQUIREMENTS if r.tier == Tier.ESSENTIAL]
        self.assertLessEqual(len(essential), 8)
        self.assertGreater(len(essential), 3)


class TestScoping(unittest.TestCase):
    def test_universal_requirements_apply_to_everyone(self):
        for requirement in requirements_for_assets(("corporate_systems",)):
            self.assertTrue(not requirement.asset_keys
                            or "corporate_systems" in requirement.asset_keys)

    def test_ot_requirements_only_reach_ot_suppliers(self):
        ot = {r.id for r in requirements_for_assets(("ics",))}
        saas = {r.id for r in requirements_for_assets(("cloud",))}
        self.assertIn("R09", ot)      # brokered remote access
        self.assertNotIn("R09", saas)
        self.assertIn("R11", saas)    # encryption of port data
        self.assertNotIn("R11", ot)

    def test_scoping_actually_narrows(self):
        """The whole point: the stationery supplier and the TOS vendor must not
        receive the same demands."""
        narrow = requirements_for_assets(())
        broad = requirements_for_assets(("tos", "ics", "cloud"))
        self.assertLess(len(narrow), len(broad))

    def test_essential_requirements_come_first(self):
        selected = requirements_for_assets(("tos",))
        tiers = [r.tier for r in selected]
        self.assertEqual(tiers, sorted(tiers, key=lambda t: [
            Tier.ESSENTIAL, Tier.RECOMMENDED, Tier.ADVANCED].index(t)))


class TestVendorScoping(unittest.TestCase):
    def test_gap_analysis_uses_existing_answers(self):
        """The port has already collected the answers; the gaps should fall out
        of them rather than requiring a second exercise."""
        weak = Vendor("w", "Weak", "MSP", supplies=("servers",),
                      answers={"Q3": 0, "Q16": 0})
        result = requirements_for_vendor(weak)
        self.assertIn("R02", result.unmet)   # MFA, verified by Q3
        self.assertIn("R01", result.unmet)   # 24h notification, verified by Q16

    def test_good_answers_produce_no_gap(self):
        strong = Vendor("s", "Strong", "SaaS", supplies=("cloud",),
                        answers={q.id: len(q.options) - 1 for q in QUESTIONS})
        result = requirements_for_vendor(strong)
        self.assertEqual(result.unmet, ())

    def test_unanswered_is_unverified_not_met(self):
        """Not asking is not the same as passing."""
        silent = Vendor("q", "Silent", "SaaS", supplies=("cloud",))
        result = requirements_for_vendor(silent)
        self.assertTrue(result.unverified)
        self.assertEqual(result.unmet, ())

    def test_critical_assets_escalate_recommended_to_essential(self):
        """Strictness has to concentrate where failure actually hurts."""
        critical = Vendor("c", "C", "sw", supplies=("tos",))       # HIGH relevance
        marginal = Vendor("m", "M", "sw", supplies=("waste_treatment",))
        critical_essential = len(requirements_for_vendor(critical)
                                 .by_tier(Tier.ESSENTIAL))
        marginal_essential = len(requirements_for_vendor(marginal)
                                 .by_tier(Tier.ESSENTIAL))
        self.assertGreater(critical_essential, marginal_essential)

    def test_escalation_can_be_disabled(self):
        vendor = Vendor("c", "C", "sw", supplies=("tos",))
        with_escalation = requirements_for_vendor(vendor)
        without = requirements_for_vendor(vendor, escalate_critical=False)
        self.assertGreaterEqual(len(with_escalation.by_tier(Tier.ESSENTIAL)),
                                len(without.by_tier(Tier.ESSENTIAL)))

    def test_essential_gaps_are_surfaced(self):
        weak = Vendor("w", "Weak", "MSP", supplies=("tos",), answers={"Q3": 0})
        self.assertTrue(requirements_for_vendor(weak).essential_gaps)

    def test_every_example_vendor_gets_requirements(self):
        for vendor in EXAMPLE_VENDORS:
            result = requirements_for_vendor(vendor)
            self.assertTrue(result.requirements, f"{vendor.key} got none")


class TestOutput(unittest.TestCase):
    def test_clauses_render(self):
        vendor = Vendor("v", "Acme Systems", "sw", supplies=("tos",),
                        answers={"Q3": 0})
        text = as_clauses(requirements_for_vendor(vendor))
        self.assertIn("Acme Systems", text)
        self.assertIn("Evidence:", text)
        self.assertIn("NIS2", text)
        self.assertIn("not currently met", text)

    def test_clauses_can_be_filtered_by_tier(self):
        vendor = Vendor("v", "V", "sw", supplies=("tos",))
        essential = as_clauses(requirements_for_vendor(vendor), tier=Tier.ESSENTIAL)
        everything = as_clauses(requirements_for_vendor(vendor))
        self.assertLess(len(essential), len(everything))

    def test_scenario_map_links_requirements_to_risks(self):
        mapping = scenario_requirement_map()
        self.assertTrue(mapping.get("S1"))
        for sid, ids in mapping.items():
            for rid in ids:
                self.assertTrue(any(r.id == rid for r in REQUIREMENTS))


class TestEscalationStaysNegotiable(unittest.TestCase):
    """The essential tier is the list a port is willing to lose a supplier over.
    An earlier version escalated every recommended requirement for any critical
    supplier, putting 9 of 10 items in the essential tier -- at which point the
    important clauses get traded away alongside the rest."""

    def test_no_supplier_gets_an_unnegotiable_essential_list(self):
        for vendor in EXAMPLE_VENDORS:
            essential = requirements_for_vendor(vendor).by_tier(Tier.ESSENTIAL)
            self.assertLessEqual(
                len(essential), 8,
                f"{vendor.key} has {len(essential)} essential requirements; "
                f"too many to hold in a negotiation")

    def test_escalation_is_tied_to_actual_exposure(self):
        """Promotion applies only where a scenario reaches the supplied asset."""
        exposed = Vendor("e", "E", "sw", supplies=("tos",))      # S1 targets tos
        unexposed = Vendor("u", "U", "sw", supplies=("buildings",))
        self.assertGreater(
            len(requirements_for_vendor(exposed).by_tier(Tier.ESSENTIAL)),
            len(requirements_for_vendor(unexposed).by_tier(Tier.ESSENTIAL)))

    def test_some_requirements_stay_below_essential(self):
        """If escalation swallowed every tier the tiering would be decorative."""
        for vendor in EXAMPLE_VENDORS:
            result = requirements_for_vendor(vendor)
            lower = result.by_tier(Tier.RECOMMENDED) + result.by_tier(Tier.ADVANCED)
            self.assertTrue(lower, f"{vendor.key} has nothing below essential")
