#!/usr/bin/env python3
"""PortSCRA dashboard.

The point of a decision support system is that the decision maker can move the
inputs and watch the recommendation change. Everything expensive is cached, so
dragging the budget slider re-optimises in real time and the port director sees
directly where their money stops buying risk reduction.

Run with:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from portscra.controls import (  # noqa: E402
    apply_controls,
    catalogue_for_group,
    efficient_frontier,
    optimise,
    tornado,
)
from portscra.graph import (  # noqa: E402
    DependencyGraph,
    build_scenarios_from_vendors,
)
from portscra.risk import (  # noqa: E402
    RONNE_2024,
    OutageCostPerHour,
    annual_disturbance_pct,
    simulate,
)
from portscra.taxonomy import build_scenarios, stride_coverage  # noqa: E402
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES  # noqa: E402
from portscra.validation import (  # noqa: E402
    INCIDENTS,
    compare_to_matrix,
    qualitative_score,
    rank_agreement,
    replay_incident,
)
from portscra.vendor import CRITERIA, DEFAULT_WEIGHTS, LikelihoodModel  # noqa: E402

from demo_vendors import VENDORS  # noqa: E402

st.set_page_config(page_title="PortSCRA", page_icon="⚓", layout="wide")

NAMES = {t.id: t.name for t in SCENARIO_TEMPLATES}


def eur(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"€{value / 1_000_000:,.2f}M"
    if abs(value) >= 1_000:
        return f"€{value / 1_000:,.1f}k"
    return f"€{value:,.0f}"


@st.cache_data
def _assessments(weights_key: tuple) -> dict:
    model = LikelihoodModel(weights=dict(weights_key))
    return {v.key: model.assess(v) for v in VENDORS}


@st.cache_data
def _simulate(scenario_key: str, _scenarios, iterations: int):
    """Cached simulation. The key carries the configuration; the scenarios go
    in underscore-prefixed so Streamlit does not try to hash them."""
    return simulate(_scenarios, iterations=iterations, seed=42)["__portfolio__"]


# --------------------------------------------------------------- sidebar
st.sidebar.title("⚓ PortSCRA")
st.sidebar.caption("Supply-chain cyber risk for small EU ports")

persona = st.sidebar.selectbox(
    "Port size (FTE)", [10, 50, 100], index=2,
    help="Rønne Havn A/S actually employs 34, so these bracket the real case. "
         "Revenue and response costs both scale with headcount.",
)
economics = RONNE_2024 if persona == 100 else RONNE_2024.scaled_to(persona)
cost_scale = {10: 0.25, 50: 0.6, 100: 1.0}[persona]
cost_per_hour = OutageCostPerHour(economics)

basis = st.sidebar.radio(
    "Frequency basis", ["Derived from suppliers", "Generic priors"],
    help="Derived uses this port's assessed vendors. Generic uses catalogue "
         "priors — what you would have without a vendor assessment.",
)

max_group = st.sidebar.select_slider(
    "CIS Implementation Group", options=[1, 2, 3], value=3,
    help="IG1 is CIS's 'essential cyber hygiene' baseline.",
)
catalogue = catalogue_for_group(max_group)
catalogue_cost = sum(c.annual_cost_eur for c in catalogue)

budget = st.sidebar.slider(
    "Annual security budget (€)", 0, int(catalogue_cost),
    value=min(25_000, int(catalogue_cost)), step=500,
)
iterations = st.sidebar.select_slider(
    "Monte Carlo iterations", options=[10_000, 50_000, 100_000], value=50_000)

st.sidebar.divider()
st.sidebar.metric("Revenue", eur(economics.revenue_eur))
st.sidebar.metric("Cost per outage hour", eur(cost_per_hour.mean))
st.sidebar.caption(f"{economics.annual_calls:,} calls/yr · {economics.employees_fte} FTE")

# --------------------------------------------------------------- model
graph = DependencyGraph(VENDORS)
assessments = _assessments(tuple(sorted(DEFAULT_WEIGHTS.items())))
generic = build_scenarios(cost_per_hour, scale=cost_scale)
scenarios = (
    generic if basis == "Generic priors"
    else build_scenarios_from_vendors(graph, assessments, cost_per_hour,
                                      fallback_scenarios=generic)
)
portfolio = optimise(scenarios, catalogue, budget)

tab_overview, tab_vendors, tab_risk, tab_optimise, tab_validate = st.tabs(
    ["Overview", "Suppliers", "Risk", "Portfolio", "Validation"])

# --------------------------------------------------------------- overview
with tab_overview:
    st.subheader(f"{economics.name}")
    st.caption(
        "Rønne is the sole supply port for Bornholm. At 34 FTE it sits below "
        "NIS2's size threshold, but Article 2(2)(b) catches sole providers of "
        "essential services regardless of size — legally obligated, "
        "operationally critical, too small to run a security function."
    )

    baseline = _simulate(f"base-{persona}-{basis}-{iterations}", scenarios, iterations)
    residual_scenarios = apply_controls(scenarios, portfolio.controls)
    after = _simulate(f"after-{persona}-{basis}-{budget}-{max_group}-{iterations}",
                      residual_scenarios, iterations)

    # Deltas are passed as plain strings with the arrow suppressed: Streamlit
    # guesses a direction from formatted text and gets it backwards here, where
    # a fall in expected loss is the good outcome.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Expected annual loss", eur(baseline.ale),
              delta=f"→ {eur(after.ale)} with portfolio", delta_color="off")
    c2.metric("1-in-100 year (P99)", eur(baseline.percentile(99)),
              delta=f"→ {eur(after.percentile(99))}", delta_color="off")
    c3.metric("Loss-free years", f"{(baseline.annual_loss == 0).mean():.0%}",
              delta=f"→ {(after.annual_loss == 0).mean():.0%}", delta_color="off")
    c4.metric("Budget", eur(budget),
              delta=f"ROSI {portfolio.rosi:+.1f}×", delta_color="off")

    st.markdown("##### Loss exceedance — the chart that communicates risk")
    losses, probs = baseline.exceedance_curve(points=150)
    losses_a, probs_a = after.exceedance_curve(points=150)
    curve = pd.DataFrame({
        "Annual loss (€)": np.concatenate([losses, losses_a]),
        "Probability of exceeding": np.concatenate([probs, probs_a]),
        "Case": ["Before controls"] * len(losses) + ["After portfolio"] * len(losses_a),
    })
    st.scatter_chart(curve, x="Annual loss (€)", y="Probability of exceeding",
                     color="Case", height=320)
    st.caption(
        "Read it as: there is a P chance of losing more than X this year. A "
        "single expected-value figure sits in a gap where few actual years land."
    )

    st.markdown("##### Operations impact")
    disturbance = annual_disturbance_pct(baseline, 24 * 365)
    d1, d2, d3 = st.columns(3)
    d1.metric("Downtime, mean", f"{baseline.annual_downtime_hours.mean():.0f} h/yr")
    d2.metric("Downtime, P90",
              f"{np.percentile(baseline.annual_downtime_hours, 90):.0f} h/yr")
    d3.metric("Operations disturbed", f"{disturbance.mean():.2f}%",
              help="Of 8,760 service hours. Rønne is a 24-hour operation "
                   "because Bornholmslinjen sails overnight.")

# --------------------------------------------------------------- vendors
with tab_vendors:
    st.subheader("Supplier risk")
    st.caption(
        "Assessed from a NIS2 Article 21-mapped questionnaire fused with public "
        "signals (EPSS, CISA KEV, OpenSSF Scorecard). Illustrative roles, not "
        "real companies."
    )

    rows = []
    for key, a in assessments.items():
        p = a.annual_probability
        rows.append({
            "Supplier": a.vendor.name,
            "Category": a.vendor.category,
            "Posture (0 best)": round(a.posture_score, 2),
            "Signals": f"{a.signal_multiplier:.2f}×",
            "P(compromise)/yr": f"{p.minimum:.1%} – {p.maximum:.1%}",
            "Most likely": p.most_likely,
            "Coverage": f"{a.coverage:.0%}",
            "Revenue exposed": graph.revenue_at_risk(a.vendor),
        })
    frame = pd.DataFrame(rows).sort_values("Most likely", ascending=False)
    st.dataframe(
        frame, hide_index=True, width="stretch",
        column_config={
            "Most likely": st.column_config.ProgressColumn(
                "Most likely", format="%.1f%%", min_value=0.0,
                max_value=float(frame["Most likely"].max())),
            "Revenue exposed": st.column_config.ProgressColumn(
                "Revenue exposed", format="%.0f%%", min_value=0.0, max_value=1.0),
        },
    )

    st.markdown("##### Concentration is a property of the topology")
    st.caption(
        "A supplier touching everything is a risk even when it is well run. "
        "This is the question a per-vendor security score cannot answer."
    )
    conc = pd.DataFrame([
        {"Supplier": v.name, "Share of revenue exposed": share}
        for v, share in graph.single_points_of_failure(threshold=0.0)
    ]).set_index("Supplier")
    st.bar_chart(conc, height=280)

    with st.expander("Criterion weights (AHP)"):
        st.caption(
            "The brief offered teacher help with criteria ranking. Built solo, "
            "that elicitation became a feature: a port runs the pairwise "
            "comparison itself and the tool checks whether its judgements cohere."
        )
        st.dataframe(
            pd.DataFrame([
                {"Criterion": c.name, "Weight": DEFAULT_WEIGHTS[c.key],
                 "Why it matters for a port": c.port_rationale}
                for c in CRITERIA
            ]).sort_values("Weight", ascending=False),
            hide_index=True, width="stretch",
        )

# --------------------------------------------------------------- risk
with tab_risk:
    st.subheader("Risk scenarios")
    if basis == "Derived from suppliers":
        st.caption("Frequencies derived from this port's assessed suppliers.")
    else:
        st.caption("Generic catalogue priors — no supplier evidence applied.")

    from portscra.controls.optimiser import scenario_ale
    rows = []
    for s in scenarios:
        drivers = getattr(s.loss_event_frequency, "drivers", [])
        driver = ""
        if drivers:
            vendor = next((v for v in VENDORS if v.key == drivers[0][0]), None)
            if vendor:
                driver = f"{vendor.name} ({drivers[0][1] / s.loss_event_frequency.mean:.0%})"
        rows.append({
            "ID": s.id,
            "Scenario": NAMES[s.id],
            "Frequency/yr": round(s.loss_event_frequency.mean, 3),
            "Expected loss": scenario_ale(s),
            "Matrix rating": qualitative_score(s).rating,
            "Main driver": driver or "—",
            "ATT&CK": ", ".join(s.attack_techniques),
        })
    risk_frame = pd.DataFrame(rows).sort_values("Expected loss", ascending=False)
    st.dataframe(
        risk_frame, hide_index=True, width="stretch",
        column_config={"Expected loss": st.column_config.ProgressColumn(
            "Expected loss", format="€%.0f", min_value=0.0,
            max_value=float(risk_frame["Expected loss"].max()))},
    )

    st.info(
        "**Range compression.** Note how many scenarios share a matrix rating "
        "while differing several-fold in expected loss. A heat map cannot "
        "prioritise among risks it colours alike — Cox (2008).",
        icon="⚠️",
    )

    with st.expander("STRIDE completeness audit"):
        st.caption(
            "STRIDE is used only to check the catalogue for blind spots. It "
            "cannot be the primary frame: it assumes a data-flow diagram of a "
            "system you own, which is exactly what you lack for a third party."
        )
        st.table(pd.DataFrame([
            {"STRIDE category": k, "Covered by": ", ".join(v) or "NOT COVERED"}
            for k, v in stride_coverage().items()
        ]))

# --------------------------------------------------------------- optimise
with tab_optimise:
    st.subheader(f"Recommended portfolio at {eur(budget)}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Expected annual loss", eur(portfolio.residual_ale),
              delta=f"−{portfolio.reduction_pct:.0%} vs {eur(portfolio.baseline_ale)}",
              delta_color="off")
    m2.metric("Spent", eur(portfolio.cost),
              delta=f"{eur(portfolio.headroom)} unspent", delta_color="off")
    m3.metric("ROSI", f"{portfolio.rosi:+.1f}×",
              help="Loss avoided minus cost, over cost. An expected value "
                   "against a certain cost — read it beside the exceedance curve.")

    if portfolio.controls:
        st.dataframe(
            pd.DataFrame([
                {"ID": c.id, "Control": c.name, "Cost/yr": c.annual_cost_eur,
                 "IG": c.implementation_group,
                 "CIS": ", ".join(c.cis_safeguards),
                 "NIS2 21(2)": ", ".join(c.nis2)}
                for c in sorted(portfolio.controls, key=lambda c: -c.annual_cost_eur)
            ]),
            hide_index=True, width="stretch",
            column_config={"Cost/yr": st.column_config.NumberColumn(format="€%.0f")},
        )
        ig1 = sum(1 for c in portfolio.controls if c.implementation_group == 1)
        st.success(
            f"{ig1} of {len(portfolio.controls)} selected controls are CIS "
            f"Implementation Group 1 — essential cyber hygiene. Nothing "
            f"restricted the optimiser to IG1; it bought the cheap "
            f"fundamentals first.", icon="✅")
    else:
        st.warning("No controls affordable at this budget.")

    st.markdown("##### How much is enough?")
    steps = [b for b in np.linspace(0, catalogue_cost, 12)]
    frontier = efficient_frontier(scenarios, catalogue, steps)
    st.line_chart(
        pd.DataFrame({
            "Spent (€)": [p.cost for p in frontier],
            "Residual expected loss (€)": [p.residual_ale for p in frontier],
        }).set_index("Spent (€)"),
        height=280,
    )
    negative = [p for p in frontier if p.rosi < 0 and p.cost > 0]
    if negative:
        st.caption(
            f"ROSI turns negative around {eur(min(p.cost for p in negative))}. "
            f"Buying everything is worse than buying the right subset — a "
            f"conclusion a compliance checklist structurally cannot reach."
        )

    st.markdown("##### Which assumptions actually matter")
    if portfolio.controls:
        bars = tornado(scenarios, portfolio)
        st.bar_chart(
            pd.DataFrame([
                {"Control": next(c.name[:34] for c in portfolio.controls
                                 if c.id == cid),
                 "Swing (€)": high - low}
                for cid, low, high in bars
            ]).set_index("Control"),
            height=280,
        )
        st.caption(
            "Residual loss if each control proves 50% better or worse than "
            "assumed. Wide bars are worth researching before committing budget; "
            "narrow ones are assumptions that do not change the answer."
        )

# --------------------------------------------------------------- validate
with tab_validate:
    st.subheader("Does the model tell the truth?")

    st.markdown("##### Incident replay")
    st.caption(
        "Anchoring incidents set the estimates and can only check consistency. "
        "Only the held-out ones are evidence."
    )
    by_id = {s.id: s for s in scenarios}
    replay_rows = []
    for incident in INCIDENTS:
        s = by_id.get(incident.scenario_id)
        if s is None:
            continue
        r = replay_incident(s, incident)
        replay_rows.append({
            "Incident": f"{incident.name} ({incident.year})",
            "Role": "anchor" if incident.used_as_anchor else "held out",
            "Observed downtime": f"{incident.downtime_hours:.0f} h",
            "Model P10–P90": f"{r.p10:.0f}–{r.p90:.0f} h",
            "Percentile": f"{r.percentile:.0f}%",
            "Verdict": r.verdict,
        })
    st.dataframe(pd.DataFrame(replay_rows), hide_index=True,
                 width="stretch")

    s2 = by_id.get("S2")
    if s2 is not None:
        modelled = 1.0 - s2.loss_magnitude.disruption_probability
        s2_incidents = [i for i in INCIDENTS if i.scenario_id == "S2"]
        observed = sum(1 for i in s2_incidents if i.downtime_hours == 0) / len(s2_incidents)
        st.info(
            f"**The replay found a real defect.** Barcelona and San Diego (2018) "
            f"suffered ransomware without stopping the quay, an outcome the model "
            f"could not produce because its downtime estimate had a 24-hour floor. "
            f"Fixed by separating *an incident happened* from *operations stopped*. "
            f"Model now predicts **{modelled:.0%}** of ransomware events cause no "
            f"operational downtime; **{observed:.0%}** of documented incidents had "
            f"none.", icon="🔍")

    st.markdown("##### Against a 5×5 risk matrix")
    duel = pd.DataFrame([
        {
            "Budget": b,
            "Matrix residual": compare_to_matrix(scenarios, catalogue, b).matrix_residual,
            "Optimised residual": compare_to_matrix(scenarios, catalogue, b).quantitative_residual,
        }
        for b in np.linspace(5_000, min(catalogue_cost, 70_000), 8)
    ]).set_index("Budget")
    st.line_chart(duel, height=280)
    st.caption(
        f"Rank agreement with the quantitative ordering is "
        f"**{rank_agreement(scenarios):+.2f}** — the matrix *orders* risks "
        f"sensibly. It fails at *allocation*, because it cannot see that a cheap "
        f"control touching four amber risks beats an expensive one touching a "
        f"single red."
    )
