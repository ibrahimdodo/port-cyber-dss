#!/usr/bin/env python3
"""Generate and execute the narrative notebooks.

The notebooks are built from here rather than hand-edited so they stay
consistent with each other and can be regenerated after the library changes.
Executing them embeds the outputs, which is what makes them readable on GitHub
without anyone running anything.

    python notebooks/build_notebooks.py            # build and execute
    python notebooks/build_notebooks.py --no-exec  # build only (fast)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


SETUP = """
import warnings; warnings.filterwarnings("ignore")
import matplotlib.pyplot as plt
import numpy as np, pandas as pd
from portscra.viz import PALETTE, INK_MUTED, style, label_bars, despine
style()

def short(text, limit=30):
    "Trim to a word boundary — a label cut mid-word reads as a rendering bug."
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]) + "…"
"""


# --------------------------------------------------------------------------
def notebook_01():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""
# 1 · The port, and where the numbers come from

Every euro figure this project produces traces back to two public sources and one
audited document. This notebook shows that derivation, because a risk model whose
inputs cannot be traced is an opinion with decimal places.

**The port.** Rønne, on Bornholm. Chosen because it is the real thing rather than a
scaled-down proxy: 34 employees, sole supply port for an island, genuinely mixed
traffic. It sits *below* NIS2's size threshold — and in scope anyway under Article
2(2)(b), which catches sole providers of essential services regardless of size.
Legally obligated, operationally critical, far too small to run a security function.
That is precisely the organisation this DSS is for.
"""),
        code(SETUP),
        code("""
from portscra.risk import RONNE_2024, OutageCostPerHour

e = RONNE_2024
print(f"{e.name}, {e.year}")
print(f"  revenue          EUR {e.revenue_eur:>12,.0f}")
print(f"  EBITDA           EUR {e.ebitda_eur:>12,.0f}   margin {e.ebitda_margin:.0%}")
print(f"  ship calls       {e.annual_calls:>16,}")
print(f"  revenue per call EUR {e.revenue_per_call_eur:>12,.0f}")
print(f"  employees        {e.employees_fte:>16} FTE")
print(f"\\nsource: {e.source}")
"""),
        md("""
## Traffic, from AIS

The Danish Maritime Authority publishes daily AIS for all Danish waters, free and
without registration. Four full weeks — one per season — were downloaded, filtered
to Rønne, and reduced to port calls. About 18 GB in, 82 kB out.

Two corrections were needed along the way, both caught by checking the output
against reality rather than by inspecting the code:

* The bounding box was capturing the **marina**. Commercial berths sit at latitude
  55.0875–55.0994 and recreational craft at 55.1033–55.1056 — a clean split, so the
  box was cut at 55.100. Before that, 29 of 50 vessels in a July day were yachts.
* The truncation tolerance was **tighter than AIS itself**. A moored Class A vessel
  transmits every 3 minutes, so a ship already alongside at midnight often produced
  its first message at 00:02 and was recorded as a fresh arrival. The dwell p90 was
  pinned at 23.9 h as a result — an artefact of the observation window, not a berth
  pattern.
"""),
        code("""
from portscra.ais import reflag_truncation, stitch_across_days

calls = pd.read_parquet("../data/processed/portcalls-all.parquet")
calls["date"] = pd.to_datetime(calls["date"])
calls = stitch_across_days(reflag_truncation(calls))

COMMERCIAL = {"Passenger", "HSC", "Cargo", "Tanker", "Ro-Ro", "Reefer"}
ronne = calls[calls.port == "ronne"].copy()
ronne["commercial"] = ronne.ship_type.isin(COMMERCIAL)

SEASONS = {"winter": "2026-01-19", "spring": "2026-04-13",
           "autumn": "2025-10-13", "summer": "2026-07-20"}
def season_of(ts):
    for name, start in SEASONS.items():
        s = pd.Timestamp(start)
        if s <= ts <= s + pd.Timedelta(days=6): return name
    return "other"
ronne["season"] = ronne.arrival.dt.normalize().apply(season_of)

per_day = (ronne[ronne.commercial].groupby("season").size() / 7).reindex(
    ["winter", "spring", "autumn", "summer"])
print(per_day.round(1).to_string())
print(f"\\nseasonal swing: {per_day.max() / per_day.min():.2f}x")
"""),
        code("""
fig, ax = plt.subplots(figsize=(7.5, 3.4))
bars = ax.bar(per_day.index, per_day.values, color=PALETTE["blue"], width=0.62)
label_bars(ax, bars, per_day.values, "{:.1f}")
ax.set_title("Commercial ship calls per day at Rønne, by season")
ax.set_ylabel("calls / day")
ax.set_ylim(0, per_day.max() * 1.25)
despine(ax); ax.grid(axis="x", visible=False)
plt.tight_layout(); plt.show()
"""),
        md("""
A **1.96× swing** between winter and summer. Autumn nearly matches summer, which is
not tourism — it is the offshore-wind installation season, when the weather is still
workable. A consequence model calibrated on July alone would overstate January risk
by about half.
"""),
        md("""
## Does the detector measure the right thing?

The AIS-derived call count is checked against Danmarks Statistik's official series
for Rønne (table SKIB101). Our two vessel-type definitions **bracket** the official
figure, which is a better result than any single ratio: the official series counts
more than our strict commercial set — it will include fishing, tugs and service
craft — but less than everything including yachts.
"""),
        code("""
days = calls.date.nunique()
commercial_yr = ronne.commercial.sum() / days * 365
all_yr = len(ronne) / days * 365
official = {2024: 3043, 2025: 2933}

print(f"commercial calls  {commercial_yr:>7,.0f} / yr")
print(f"all vessel calls  {all_yr:>7,.0f} / yr")
for year, count in official.items():
    inside = commercial_yr <= count <= all_yr
    print(f"official {year}     {count:>7,} / yr   "
          f"{'within our bracket' if inside else 'OUTSIDE'}")
"""),
        md("""
## Dwell times → the consequence model's inputs

How long a vessel occupies a berth sets how long an outage has to last before it
starts turning ships away rather than merely delaying them. Read as
`PERT(p10, median, p90)`, these become the model's three-point estimates.

The Passenger median of **2.7 hours** is the strongest validation the pipeline has
produced: that is a real ro-pax turnaround, and it matches the HAMMERSHUS calls
observed directly on day one. Before the two corrections above it read 9.0 hours —
pure contamination from vessels that were present all day.
"""),
        code("""
complete = ronne[ronne.commercial & ~ronne.truncated_start & ~ronne.truncated_end]
dwell = (complete.groupby("ship_type").dwell_hours
         .agg(n="count", p10=lambda s: s.quantile(.1), median="median",
              p90=lambda s: s.quantile(.9))
         .query("n >= 5").sort_values("median"))
print(dwell.round(2).to_string())
"""),
        code("""
fig, ax = plt.subplots(figsize=(7.5, 3.0))
y = np.arange(len(dwell))
ax.hlines(y, dwell.p10, dwell.p90, color=PALETTE["blue"], lw=2.4, alpha=.35)
ax.plot(dwell["median"], y, "o", color=PALETTE["blue"], ms=7, zorder=3)
for i, (name, row) in enumerate(dwell.iterrows()):
    ax.annotate(f"{row['median']:.1f} h", (row["median"], i), xytext=(0, 9),
                textcoords="offset points", ha="center",
                color=INK_MUTED, fontsize=8.5)
ax.set_yticks(y); ax.set_yticklabels(dwell.index)
ax.set_title("Berth occupancy at Rønne — median, p10–p90 range")
ax.set_xlabel("hours alongside")
ax.set_ylim(-.6, len(dwell) - .3)
despine(ax); ax.grid(axis="y", visible=False)
plt.tight_layout(); plt.show()
"""),
        md("""
## From revenue to a cost per outage hour

Two reductions, both uncertain, so both are distributions rather than point values:

* **Not all revenue is at risk.** A cyber outage stops vessel handling. It does not
  stop the clock on land leases and project-area rental, which are billed on time
  and which grew sharply at Rønne in 2024.
* **Not all disrupted revenue is lost.** A cancelled ferry carries tomorrow's
  passengers too. What is genuinely lost is traffic that diverts, the cruise call
  that cannot be rescheduled, the offshore project window that closes.
"""),
        code("""
cost = OutageCostPerHour(RONNE_2024)
draws = cost.sample(np.random.default_rng(42), 200_000)
print(f"cost per outage hour: EUR {cost.mean:,.0f} mean "
      f"(P10 {np.percentile(draws,10):,.0f} / P90 {np.percentile(draws,90):,.0f})")

check = cost.cross_check_per_call(RONNE_2024.annual_calls / 365)
print(f"\\nindependent derivation via revenue per call: "
      f"EUR {check['adjusted_hourly_eur']:,.0f}/h  (ratio {check['ratio']:.2f})")
"""),
        md("""
The two derivations agree to **ratio 1.00** on a matched call basis. That check paid
for itself the first time it ran: it caught a 15× unit error where daily revenue was
being converted to hourly with `×24` instead of `×365/service_hours`.

**€659/hour** is roughly a quarter of the placeholder used before this derivation
existed — and that difference reorders the risks, as notebook 3 shows.
"""),
    ]
    return nb


# --------------------------------------------------------------------------
def notebook_02():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""
# 2 · Suppliers — who could hurt us, and how badly

Two sources of evidence, deliberately fused rather than chosen between.

The **questionnaire** covers everyone, including suppliers no scanner has heard of —
the crane OEM, the local integrator — but it is self-reported and static. **Public
signals** (EPSS, CISA KEV, OpenSSF Scorecard) are objective and current but only
exist where there is published software with CVEs.

Neither alone suits a small port's supplier list, which mixes global SaaS with a
two-person integrator. Together they degrade gracefully.

> The suppliers below are **illustrative roles, not real companies**. Naming real
> firms would assert things about their security this project has no evidence for.
"""),
        code(SETUP),
        code("""
from portscra.examples import EXAMPLE_VENDORS
from portscra.vendor import CRITERIA, DEFAULT_WEIGHTS, LikelihoodModel

model = LikelihoodModel()
ranked = model.rank(EXAMPLE_VENDORS)

rows = [{"supplier": a.vendor.name, "posture": round(a.posture_score, 2),
         "signals": f"{a.signal_multiplier:.2f}x",
         "P(compromise)/yr": f"{a.annual_probability.minimum:.1%}–{a.annual_probability.maximum:.1%}",
         "most likely": a.annual_probability.most_likely,
         "coverage": f"{a.coverage:.0%}"} for a in ranked]
pd.DataFrame(rows)
"""),
        md("""
## Criterion weights, elicited rather than asserted

The original brief offered teacher help with "criteria ranking". Built solo, that
elicitation became a feature instead: the tool runs the pairwise comparison with the
user and reports whether their judgements actually cohere.

AHP's consistency ratio is the part that earns its place. If someone says access
beats posture, posture beats data exposure, and data exposure beats access, the
ratio exposes the contradiction rather than quietly averaging it away.
"""),
        code("""
from portscra.vendor import matrix_from_comparisons, weights_from_matrix

criteria = [c.key for c in CRITERIA]
judgements = {("access","posture"):3, ("access","data_exposure"):5,
              ("access","incident_history"):5, ("asset_criticality","posture"):3,
              ("asset_criticality","data_exposure"):4,
              ("asset_criticality","incident_history"):5,
              ("update_channel","posture"):2, ("update_channel","incident_history"):3,
              ("substitutability","incident_history"):2,
              ("posture","incident_history"):2, ("data_exposure","incident_history"):2}
result = weights_from_matrix(criteria, matrix_from_comparisons(criteria, judgements))

print(f"consistency ratio {result.consistency_ratio:.4f} "
      f"({'acceptable' if result.is_consistent else 'TOO INCONSISTENT'}, threshold 0.10)\\n")
names = {c.key: c.name for c in CRITERIA}
for key, weight in result.ranked():
    print(f"  {names[key]:38s} {weight:.3f}   (default {DEFAULT_WEIGHTS[key]:.3f})")
"""),
        md("""
The elicited weights track the literature defaults closely — access 0.238 against a
default of 0.24. Two independent derivations landing in the same place is mild
evidence that both are reasonable.
"""),
        md("""
## Live signals

Until these were fetched, every signal in this project was a hand-typed constant
labelled *illustrative*, while the README described them as fused public feeds. The
logic was real; the data was invented.

Enrichment then exposed a problem in the example data itself: the fabricated values
were **inflating** risk. One supplier carried an invented KEV hit worth 1.76×, and
live lookup dropped it to 1.00× — its assessed probability fell from 13.3% to 7.6%.
All fabricated feed values were removed, and a test now fails if one reappears.
"""),
        code("""
from portscra.signals import fetch_epss, fetch_kev, fetch_scorecard

kev = fetch_kev()
print(f"CISA KEV: {kev.describe()} — {len(kev.data):,} known-exploited CVEs, "
      f"{sum(1 for v in kev.data.values() if v['ransomware']):,} ransomware-linked")

epss = fetch_epss(["CVE-2024-3094", "CVE-2021-44228"])
for cve, row in sorted(epss.data.items()):
    print(f"  {cve}  EPSS {row['epss']:.1%}   in KEV: {cve in kev.data}")
"""),
        md("""
**This is the result worth pausing on.** CVE-2024-3094 — the xz-utils backdoor —
scores 86% on EPSS and is *absent* from CISA KEV, because it was caught before it was
exploited in the wild.

One of the most serious supply-chain compromises ever found would score **clean** on
a KEV-only check. That is exactly why the model treats KEV presence as strong
evidence and KEV absence as weak: most software never receives the scrutiny that
would put it there, and some that does is caught too early to qualify.
"""),
        code("""
fig, ax = plt.subplots(figsize=(8.2, 3.6))
labels = [short(a.vendor.name) for a in ranked][::-1]
values = [a.annual_probability.most_likely * 100 for a in ranked][::-1]
bars = ax.barh(labels, values, color=PALETTE["blue"], height=0.62)
label_bars(ax, bars, values, "{:.1f}%", horizontal=True)
ax.set_title("Probability a supplier compromise affects the port, per year")
ax.set_xlabel("% per year")
ax.set_xlim(0, max(values) * 1.22)
despine(ax); ax.grid(axis="y", visible=False)
plt.tight_layout(); plt.show()
"""),
        md("""
## Concentration is a property of the topology

The question a per-supplier score cannot answer: **how much of the port does each
supplier touch?** A supplier reaching everything is a concentration risk even when it
is impeccably run, and that is a fact about the dependency graph rather than about
anyone's security posture.
"""),
        code("""
from portscra.graph import DependencyGraph

graph = DependencyGraph(EXAMPLE_VENDORS)
exposure = graph.single_points_of_failure(threshold=0.0)

fig, ax = plt.subplots(figsize=(8.2, 3.4))
labels = [short(v.name) for v, _ in exposure][::-1]
shares = [s * 100 for _, s in exposure][::-1]
bars = ax.barh(labels, shares, color=PALETTE["orange"], height=0.62)
label_bars(ax, bars, shares, "{:.0f}%", horizontal=True)
ax.set_title("Share of call-dependent revenue exposed to each supplier")
ax.set_xlabel("% of revenue")
ax.set_xlim(0, 100)
despine(ax); ax.grid(axis="y", visible=False)
plt.tight_layout(); plt.show()

for vendor, share in exposure[:3]:
    print(f"{vendor.name[:38]:40s} {share:.0%}  →  "
          f"{', '.join(sorted(graph.services_for_vendor(vendor)))}")
"""),
    ]
    return nb


# --------------------------------------------------------------------------
def notebook_03():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""
# 3 · Risk — euro, hours, and percent of operations

This is Problem #2 of the brief: *if a supplier is compromised, how big is the
consequence — revenue in €, operations disturbance in %, downtime in hours?*

The engine is FAIR-style Monte Carlo. One modelling choice does most of the work:
the number of events in a year is drawn from a **Poisson** distribution rather than
multiplying a frequency by a magnitude. Multiplying gives the mean and destroys the
shape — and the shape is the point. A port with a 0.08/year ransomware frequency has
no "average" year; it has quiet years and one very bad one.
"""),
        code(SETUP),
        code("""
from portscra.controls.optimiser import scenario_ale
from portscra.examples import EXAMPLE_VENDORS
from portscra.graph import DependencyGraph, build_scenarios_from_vendors
from portscra.risk import RONNE_2024, OutageCostPerHour, annual_disturbance_pct, simulate
from portscra.taxonomy import build_scenarios
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES
from portscra.vendor import LikelihoodModel

cost = OutageCostPerHour(RONNE_2024)
graph = DependencyGraph(EXAMPLE_VENDORS)
model = LikelihoodModel()
assessments = {v.key: model.assess(v) for v in EXAMPLE_VENDORS}

generic = build_scenarios(cost)
derived = build_scenarios_from_vendors(graph, assessments, cost,
                                       fallback_scenarios=generic)
NAMES = {t.id: t.name for t in SCENARIO_TEMPLATES}
"""),
        md("""
## Frequencies derived from *this* port's suppliers

A scenario's frequency is built from the suppliers that actually provide the assets
it targets, each contributing in proportion to how much of the scenario it could
drive. Frequencies **add** — loss event frequency is a Poisson rate, so contributions
sum; treating them as probabilities would be wrong.

A scenario with no matching supplier keeps its generic prior rather than dropping to
zero. Otherwise "forget to write the vendor down" would be the cheapest way to reduce
measured risk.
"""),
        code("""
by_id = {s.id: s for s in generic}
rows = []
for s in derived:
    drivers = getattr(s.loss_event_frequency, "drivers", [])
    driver = "— no supplier listed —"
    if drivers:
        v = next(v for v in EXAMPLE_VENDORS if v.key == drivers[0][0])
        driver = f"{v.name[:30]} ({drivers[0][1]/s.loss_event_frequency.mean:.0%})"
    rows.append({"scenario": NAMES[s.id][:44],
                 "generic": round(by_id[s.id].loss_event_frequency.mean, 3),
                 "derived": round(s.loss_event_frequency.mean, 3),
                 "main driver": driver})
pd.DataFrame(rows)
"""),
        md("""
The generic priors were wrong **in both directions** for this port — trojanized
update 2.2× higher than assumed, SaaS takeover 3× lower. Assuming typical
frequencies would have misdirected the spend.
"""),
        code("""
results = {k: simulate(v, iterations=100_000, seed=42)["__portfolio__"]
           for k, v in (("generic", generic), ("derived", derived))}
r = results["derived"]

print(f"expected annual loss (mean)   EUR {r.ale:>10,.0f}")
print(f"median year                   EUR {r.p50:>10,.0f}")
print(f"P90                           EUR {r.p90:>10,.0f}")
print(f"P99                           EUR {r.percentile(99):>10,.0f}")
print(f"worst simulated year          EUR {r.annual_loss.max():>10,.0f}")
print(f"\\nyears with no loss at all     {(r.annual_loss == 0).mean():>10.1%}")
print(f"downtime, mean                {r.annual_downtime_hours.mean():>10.0f} h/yr")
print(f"operations disturbed, mean    "
      f"{annual_disturbance_pct(r, 24*365).mean():>10.2f} %")
"""),
        md("""
Note the gap between the **mean (€95k)** and the **median (€0)**. For a
low-frequency, high-impact risk the average sits where almost no actual year lands.
Quoting it alone is the commonest way quantitative risk work misleads.

The honest chart is the loss exceedance curve: *there is a P chance of losing more
than X this year.*
"""),
        code("""
fig, ax = plt.subplots(figsize=(7.8, 3.8))
losses, probs = r.exceedance_curve(points=400)
ax.plot(losses / 1000, probs * 100, color=PALETTE["blue"], lw=2.2)
ax.fill_between(losses / 1000, probs * 100, color=PALETTE["blue"], alpha=.10)
for q, label in ((90, "P90"), (99, "P99")):
    x = r.percentile(q) / 1000
    ax.plot([x, x], [0, 100 - q], color=INK_MUTED, lw=1, ls=":")
    ax.annotate(f"{label}  EUR {x:,.0f}k", (x, 100 - q), xytext=(6, 6),
                textcoords="offset points", color=INK_MUTED, fontsize=8.5)
ax.set_title("Loss exceedance — probability of exceeding an annual loss")
ax.set_xlabel("annual loss (EUR thousands)"); ax.set_ylabel("% chance of exceeding")
ax.set_xlim(0, r.percentile(99.5) / 1000); ax.set_ylim(0, 70)
despine(ax); ax.grid(axis="x", visible=False)
plt.tight_layout(); plt.show()
"""),
        code("""
ales = sorted(((short(NAMES[s.id], 38), scenario_ale(s)) for s in derived),
              key=lambda kv: kv[1])
fig, ax = plt.subplots(figsize=(8.2, 3.4))
bars = ax.barh([k for k, _ in ales], [v for _, v in ales],
               color=PALETTE["blue"], height=0.62)
label_bars(ax, bars, [v for _, v in ales], "EUR {:,.0f}", horizontal=True)
ax.set_title("Expected annual loss by scenario")
ax.set_xlabel("EUR / year")
ax.set_xlim(0, max(v for _, v in ales) * 1.3)
despine(ax); ax.grid(axis="y", visible=False)
plt.tight_layout(); plt.show()
"""),
        md("""
## A result the derivation produced, and intuition would not

With the placeholder hourly cost, MSP ransomware ranked first. Once the hourly figure
was *derived* — €659, because a small port's revenue per hour is genuinely modest —
the ordering changed: downtime-driven scenarios carry less weight than a direct,
unrecoverable cash loss.

A qualitative heat map would almost certainly have marked ransomware *critical* and
business email compromise *medium*. That reversal is the clearest argument in this
project for quantifying rather than colouring.
"""),
    ]
    return nb


# --------------------------------------------------------------------------
def notebook_04():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""
# 4 · The decision — what to buy with a fixed budget

Problem #1 of the brief, treated as what it actually is: **constrained portfolio
selection**, not a ranked list of recommendations.

Two modelling points decide whether the answer is any good.

**Risk composes multiplicatively.** Two controls each halving a frequency leave a
quarter of it, not zero. Adding percentages would let the model "eliminate" a risk by
stacking three mediocre controls, and would systematically over-buy. It also makes
the objective submodular — diminishing returns — which is what makes greedy selection
principled rather than arbitrary.

**Frequency and magnitude are separate levers.** Backups do not prevent ransomware;
they make it survivable. Collapsing both into one "effectiveness" number cannot tell
a control that stops an incident from one that shortens it.
"""),
        code(SETUP),
        code("""
from portscra.controls import CATALOGUE, apply_controls, efficient_frontier, optimise, tornado
from portscra.examples import EXAMPLE_VENDORS
from portscra.graph import DependencyGraph, build_scenarios_from_vendors
from portscra.risk import RONNE_2024, OutageCostPerHour, simulate
from portscra.taxonomy import build_scenarios
from portscra.vendor import LikelihoodModel

cost = OutageCostPerHour(RONNE_2024)
graph = DependencyGraph(EXAMPLE_VENDORS)
model = LikelihoodModel()
scenarios = build_scenarios_from_vendors(
    graph, {v.key: model.assess(v) for v in EXAMPLE_VENDORS}, cost,
    fallback_scenarios=build_scenarios(cost))

BUDGET = 25_000
portfolio = optimise(scenarios, CATALOGUE, BUDGET)
print(portfolio.explain())
"""),
        md("""
**Seven of the eight selected controls are CIS Implementation Group 1** — "essential
cyber hygiene". That is a *result*, not a constraint: nothing restricted the search to
IG1. It simply bought the cheap fundamentals first, which is independent support for
CIS's own claim about what carries most of the value for small organisations.
"""),
        code("""
residual = apply_controls(scenarios, portfolio.controls)
before = simulate(scenarios, iterations=100_000, seed=42)["__portfolio__"]
after = simulate(residual, iterations=100_000, seed=42)["__portfolio__"]

rows = [("mean (ALE)", before.ale, after.ale),
        ("median", before.p50, after.p50),
        ("P90", before.p90, after.p90),
        ("P99", before.percentile(99), after.percentile(99))]
for label, b, a in rows:
    print(f"  {label:12s} EUR {b:>10,.0f}  ->  EUR {a:>10,.0f}   ({1-a/b if b else 0:.0%} cut)")
print(f"  {'loss-free yr':12s} {(before.annual_loss==0).mean():>13.0%}  ->  "
      f"{(after.annual_loss==0).mean():>13.0%}")
"""),
        md("""
The **mean falls 77% but the P99 tail only 64%** — and that is the opposite of what I
expected before running it.

The portfolio mostly buys *frequency* reduction: loss-free years rise from 34% to
52%. But the bad year that still happens stays expensive, because the residual tail is
dominated by whatever the budget could not cover. Reporting only the mean would
**overstate** how much protection was bought.
"""),
        code("""
fig, ax = plt.subplots(figsize=(7.8, 3.8))
for label, res, colour in (("before controls", before, PALETTE["orange"]),
                           ("after portfolio", after, PALETTE["blue"])):
    losses, probs = res.exceedance_curve(points=400)
    ax.plot(losses / 1000, probs * 100, color=colour, lw=2.2, label=label)
ax.legend(loc="upper right")
ax.set_title(f"Loss exceedance, before and after a EUR {BUDGET:,.0f} portfolio")
ax.set_xlabel("annual loss (EUR thousands)"); ax.set_ylabel("% chance of exceeding")
ax.set_xlim(0, before.percentile(99.5) / 1000); ax.set_ylim(0, 70)
despine(ax); ax.grid(axis="x", visible=False)
plt.tight_layout(); plt.show()
"""),
        md("""
## How much is enough?

The question a port director actually has is not *what should I buy* but *where does
this stop paying*. That is a shape, not a number.
"""),
        code("""
total = sum(c.annual_cost_eur for c in CATALOGUE)
frontier = efficient_frontier(scenarios, CATALOGUE, list(np.linspace(0, total, 16)))
spent = [p.cost / 1000 for p in frontier]
residual_ale = [p.residual_ale / 1000 for p in frontier]

fig, ax = plt.subplots(figsize=(7.8, 3.8))
ax.plot(spent, residual_ale, color=PALETTE["blue"], lw=2.2, marker="o", ms=4)
chosen = portfolio.cost / 1000
ax.plot([chosen], [portfolio.residual_ale / 1000], "o", ms=10,
        color=PALETTE["orange"], zorder=4)
ax.annotate(f"EUR {BUDGET/1000:,.0f}k budget\\nROSI {portfolio.rosi:+.1f}x",
            (chosen, portfolio.residual_ale / 1000), xytext=(14, 14),
            textcoords="offset points", color=INK_MUTED, fontsize=8.5)
ax.set_title("Efficient frontier — residual expected loss against spend")
ax.set_xlabel("annual spend (EUR thousands)")
ax.set_ylabel("residual expected loss (EUR thousands)")
despine(ax)
plt.tight_layout(); plt.show()

for p in frontier[::4] + [frontier[-1]]:
    print(f"  EUR {p.cost:>7,.0f} spent -> EUR {p.residual_ale:>8,.0f} residual "
          f"({p.reduction_pct:4.0%} cut, ROSI {p.rosi:+5.1f}x)")
"""),
        md("""
**ROSI turns negative at full-catalogue spend.** Buying everything is worse than
buying the right subset — a conclusion a compliance checklist structurally cannot
reach, and the sharpest single argument in this project for optimisation over
enumeration.
"""),
        md("""
## Which assumptions actually matter

Control effectiveness estimates are the weakest inputs in the model. The useful
question is not "is 40% the right number" but "would a different plausible number
change what I buy".
"""),
        code("""
bars_data = tornado(scenarios, portfolio)
names = {c.id: c.name for c in CATALOGUE}
labels = [f"{cid} {short(names[cid], 30)}" for cid, _, _ in bars_data][::-1]
widths = [(hi - lo) / 1000 for _, lo, hi in bars_data][::-1]

fig, ax = plt.subplots(figsize=(8.2, 3.4))
bars = ax.barh(labels, widths, color=PALETTE["blue"], height=0.6)
label_bars(ax, bars, widths, "EUR {:,.1f}k", horizontal=True)
ax.set_title("Sensitivity — swing if a control is 50% better or worse")
ax.set_xlabel("EUR thousands of swing")
ax.set_xlim(0, max(widths) * 1.28)
despine(ax); ax.grid(axis="y", visible=False)
plt.tight_layout(); plt.show()
"""),
        md("""
Wide bars are the estimates worth researching before committing budget. Narrow ones
are assumptions that do not change the decision — equally useful to know, and the
reason this is a sensitivity analysis rather than a disclaimer.
"""),
    ]
    return nb


# --------------------------------------------------------------------------
def notebook_05():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""
# 5 · Validation — does the model tell the truth?

The football-recruitment DSS this project is measured against had one illustrative
case study and no validation section. Three checks here, each answering a question an
examiner would actually ask.
"""),
        code(SETUP),
        code("""
from portscra.controls import CATALOGUE
from portscra.risk import RONNE_2024, OutageCostPerHour
from portscra.taxonomy import build_scenarios
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES
from portscra.validation import (INCIDENTS, compare_to_matrix, qualitative_score,
                                 rank_agreement, replay_incident)

cost = OutageCostPerHour(RONNE_2024)
scenarios = build_scenarios(cost)
by_id = {s.id: s for s in scenarios}
NAMES = {t.id: t.name for t in SCENARIO_TEMPLATES}
"""),
        md("""
## 1 · Incident replay

Real port incidents have documented durations. Do they fall inside the model's
predicted band?

Incidents are split into those that **anchored** the estimates and those **held out**.
Only the held-out ones are evidence — checking a model against the data used to build
it is a consistency check, and reporting that as validation would be dishonest.
"""),
        code("""
rows = []
for inc in INCIDENTS:
    r = replay_incident(by_id[inc.scenario_id], inc)
    rows.append({"incident": f"{inc.name} ({inc.year})",
                 "role": "anchor" if inc.used_as_anchor else "held out",
                 "observed": f"{inc.downtime_hours:.0f} h",
                 "model P10–P90": f"{r.p10:.0f}–{r.p90:.0f} h",
                 "percentile": f"{r.percentile:.0f}%",
                 "verdict": r.verdict})
pd.DataFrame(rows)
"""),
        md("""
**The first run of this failed 2 of 4, and the failure was the most useful thing the
project produced.**

Barcelona and San Diego (both 2018) suffered ransomware *without stopping the quay* —
IT was hit, ships kept working. The downtime estimate had a floor of 24 hours and
could not produce that outcome at any percentile. The model was asserting that
supplier-borne ransomware always becomes an operational outage, which the record
contradicts.

The fix was structural rather than a parameter nudge: `disruption_probability` now
separates *an incident happened* from *operations stopped*. Simply lowering the floor
would have blurred two distinct things together.
"""),
        code("""
s2 = by_id["S2"]
modelled = 1 - s2.loss_magnitude.disruption_probability
s2_incidents = [i for i in INCIDENTS if i.scenario_id == "S2"]
observed = sum(1 for i in s2_incidents if i.downtime_hours == 0) / len(s2_incidents)
print("Share of ransomware events causing NO operational downtime")
print(f"  model     {modelled:.0%}")
print(f"  observed  {observed:.0%}  ({sum(1 for i in s2_incidents if i.downtime_hours==0)} "
      f"of {len(s2_incidents)} documented incidents)")
"""),
        md("""
Band containment is a weak test once the band starts at zero. Matching the *rate* at
which nothing operational happens is not — and it is the parameter the replay forced
into existence.
"""),
        md("""
## 2 · Against a 5×5 risk matrix

A qualitative matrix is what CSET, MONARC and most port risk registers actually
produce. Both methods are fed the *same* underlying estimates, so the comparison
isolates the method rather than the inputs.
"""),
        code("""
from portscra.controls.optimiser import scenario_ale
rows = [{"scenario": NAMES[s.id][:44],
         "matrix": f"{qualitative_score(s).rating} ({qualitative_score(s).score})",
         "quantitative ALE": f"EUR {scenario_ale(s):,.0f}"}
        for s in sorted(scenarios, key=lambda s: -qualitative_score(s).score)]
print(f"rank agreement with the quantitative ordering: {rank_agreement(scenarios):+.2f}\\n")
pd.DataFrame(rows)
"""),
        md("""
Rank agreement is **+0.91** — the matrix *orders* risks perfectly sensibly. If it did
not, beating it would prove nothing. The interesting claim is that a method can rank
well and still allocate badly.

Six of seven scenarios land in a single "Medium" band spanning 4.2× in expected loss.
That is Cox's *range compression*, and it is why a heat map cannot prioritise
spending.
"""),
        code("""
budgets = [10_000, 15_000, 25_000, 40_000, 60_000]
comparisons = [compare_to_matrix(scenarios, CATALOGUE, b) for b in budgets]

fig, ax = plt.subplots(figsize=(7.8, 3.6))
x = np.arange(len(budgets)); w = 0.36
b1 = ax.bar(x - w/2, [c.matrix_residual/1000 for c in comparisons], w,
            color=PALETTE["orange"], label="heat-map led")
b2 = ax.bar(x + w/2, [c.quantitative_residual/1000 for c in comparisons], w,
            color=PALETTE["blue"], label="optimised")
ax.set_xticks(x); ax.set_xticklabels([f"EUR {b//1000}k" for b in budgets])
ax.set_title("Residual expected loss for the same budget, spent two ways")
ax.set_ylabel("residual expected loss (EUR thousands)"); ax.set_xlabel("budget")
ax.legend(loc="upper right")
despine(ax); ax.grid(axis="x", visible=False)
plt.tight_layout(); plt.show()

for b, c in zip(budgets, comparisons):
    print(f"  EUR {b:>6,}  advantage EUR {c.advantage:>7,.0f}  "
          f"({c.advantage_pct:+.0%} of baseline)")
"""),
        md("""
The optimiser wins at every budget, by €1.6k–18.9k a year. *A matrix can rank well
and still allocate badly*, because it cannot see that a cheap control touching four
amber risks beats an expensive one touching a single red.
"""),
        md("""
## 3 · ENISA maturity — phase four

This project claims to operationalise ENISA's four-phase approach. Phases one to three
are the taxonomy, the risk engine and the optimiser. This is the fourth.

The portfolio implies a maturity profile, so a budget can be read in ENISA's terms as
well as in euro.
"""),
        code("""
from portscra.controls import optimise
from portscra.maturity import CATEGORY_NAMES, maturity_from_controls

for budget in (0, 25_000, sum(c.annual_cost_eur for c in CATALOGUE)):
    p = optimise(scenarios, CATALOGUE, budget)
    profile = maturity_from_controls([c.id for c in p.controls])
    cats = " · ".join(f"{CATEGORY_NAMES[k][:14]} {v:.2f}"
                      for k, v in sorted(profile.by_category().items()))
    print(f"EUR {budget:>7,.0f} -> overall {profile.overall:.2f}/3  "
          f"(supply-chain {profile.supply_chain_score():.2f})")
    print(f"             {cats}")
"""),
        md("""
Buying **every** control still reaches only 2.42 of 3. That ceiling is deliberate:
ENISA is explicit that maturity cannot be achieved through a checklist mentality.
Level 3 requires oversight, testing and continuous improvement — a way of working
rather than a purchase. A model that let a port buy its way to *Optimal* would be
misrepresenting the framework it cites.

---

## What this project concluded

* **The tail is stickier than the mean.** A portfolio buys frequency reduction; the
  bad year that still happens stays expensive. Reporting the mean overstates the
  protection bought.
* **Buying everything is worse than buying the right subset** — ROSI turns negative at
  full-catalogue spend.
* **Deriving the hourly cost reordered the risks.** Invoice fraud overtook ransomware
  once the figure came from audited accounts rather than a plausible guess.
* **Held-out validation found a real defect**, and fixing it lowered the model's own
  expected-loss estimate. A validation suite that never fails is not a validation
  suite.
"""),
    ]
    return nb


# --------------------------------------------------------------------------
NOTEBOOKS = {
    "01_the_port_and_the_numbers.ipynb": notebook_01,
    "02_suppliers.ipynb": notebook_02,
    "03_risk.ipynb": notebook_03,
    "04_the_decision.ipynb": notebook_04,
    "05_validation.ipynb": notebook_05,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-exec", action="store_true")
    args = parser.parse_args()

    for filename, builder in NOTEBOOKS.items():
        nb = builder()
        nb.metadata["kernelspec"] = {"display_name": "Python 3",
                                     "language": "python", "name": "python3"}
        nb.metadata["language_info"] = {"name": "python"}
        path = HERE / filename

        if not args.no_exec:
            from nbclient import NotebookClient
            print(f"executing {filename} ...", flush=True)
            NotebookClient(nb, timeout=900, kernel_name="python3",
                           resources={"metadata": {"path": str(HERE)}}).execute()

        nbf.write(nb, path)
        print(f"  wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
