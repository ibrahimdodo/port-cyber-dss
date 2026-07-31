# PortSCRA — Supply-Chain Cyber Risk Assessment for Small EU Ports

A decision support system that answers two questions for a port too small to have a security team:

1. **If one of our suppliers is compromised, what does it cost us?** — in euro, in hours of downtime, in percent of operations disturbed.
2. **Given a fixed budget, which security controls should we buy first?**

Every accessible tool in this space — [CISA CSET](https://www.cisa.gov/resources-tools/services/cyber-security-evaluation-tool-csetr), [MONARC](https://www.monarc.lu/), SimpleRisk — stops at a qualitative heat map. Commercial platforms (BitSight, SecurityScorecard, UpGuard) are black-box, enterprise-priced and port-blind. This project quantifies instead, in the port's own operational terms, and then optimises the spend.

> **Status: feature-complete for the analytical chain.** ENISA taxonomies, AIS pipeline, port economics, FAIR Monte Carlo, vendor likelihood, dependency graph, control optimiser, validation suite and an interactive Streamlit dashboard. Remaining: deployment, awareness module, SimPy outage simulation. See [PLANNING.md](PLANNING.md) for the full design rationale, the solution landscape survey, and the rejected alternatives.

---

## Why this problem

Ports are Annex I "Transport — Water" entities under **NIS2** (Directive (EU) 2022/2555). Article 21(2)(d) makes supply-chain security a legal obligation, Article 20 puts liability and training duties on management, and Article 23 imposes 24h/72h incident reporting. Meanwhile the attacks that matter arrive *through suppliers*: SolarWinds, Kaseya, MOVEit, xz-utils.

Ports get hit and it costs real money — Maersk/NotPetya 2017 (~$250–300M, 76 terminals halted), Port of Nagoya 2023 (LockBit, ~2.5 days of container operations lost), DP World Australia 2023 (~3 days, ~30,000 containers stranded). These are the calibration anchors for the consequence model, not decoration.

The anchor case makes the point sharply. **Rønne Havn A/S employs 34 people.** That is below NIS2's size threshold — but as the sole supply port for Bornholm it falls in scope anyway under Article 2(2)(b), which catches sole providers of essential services regardless of size. Legally obligated, operationally critical to an island, and far too small to run a security function. That decision deserves a number, not a colour.

## Approach

```
vendors ──> assets ──> port services        (dependency graph, ENISA taxonomy)
   │                        │
   │  likelihood            │  consequence
   │  questionnaire (NIS2)  │  AIS-derived traffic → €/hour, downtime, % disturbance
   │  + EPSS / KEV / OpenSSF│  + real incident anchors
   ▼                        ▼
        FAIR-style Monte Carlo  →  loss distributions, P10/P50/P90, exceedance curves
                    │
                    ▼
        knapsack optimiser over CIS Controls v8  →  "given €20k, buy these six things"
```

**Threat identification** = ENISA port threat taxonomy (domain skeleton) × MITRE ATT&CK techniques (concrete vectors) × STRIDE (completeness audit only) — following PASTA's risk-centric philosophy rather than STRIDE's software-centric one.

## What works today

```bash
# Install (editable), so imports work from anywhere — including notebooks
pip install -e .
pip install -e ".[app]"    # adds Streamlit for the dashboard

# Run the risk engine — no data download needed
python scripts/demo_risk.py

# Validate the AIS pipeline against one real day (~600 MB download)
python scripts/day_one.py --date 2026-03-02

# Build the four-season port-call dataset (~18 GB downloaded, then discarded)
python scripts/build_dataset.py
python scripts/build_dataset.py --aggregate-only   # re-run stats only

# Pull live EPSS / CISA KEV / OpenSSF Scorecard for the supplier list
python scripts/refresh_signals.py
python scripts/refresh_signals.py --offline   # show graceful degradation

# Rank a supplier list by compromise likelihood
python scripts/demo_vendors.py
python scripts/demo_vendors.py --ahp     # pairwise criterion weighting
python scripts/demo_vendors.py --nis2    # NIS2 Article 21 coverage

# Choose a mitigation portfolio under a budget
python scripts/demo_optimise.py --budget 25000
python scripts/demo_optimise.py --ig 1   # essential cyber hygiene only

# The whole chain: suppliers → graph → derived frequencies → portfolio
python scripts/demo_pipeline.py

# Validation: incident replay, 5x5 matrix duel, persona sweep
python scripts/validate.py

# Interactive dashboard
python -m streamlit run app/streamlit_app.py

# Tests
PYTHONPATH=src python3 -m unittest discover -s tests
```

Sample output from `demo_risk.py`, with the hourly cost derived from Rønne Havn's 2024 audited accounts (€22.8M revenue, 3,043 calls, 34 FTE):

```
cost/hour: EUR 659/h mean (P10 451 / P90 883)

ID   scenario                                        ALE       P50       P90   P(any)
S3   SaaS account takeover → invoice fraud        33.3k       0.0     135.1k   29.0%
S2   Managed service provider compromise ...      27.8k       0.0       0.0     9.3%
S7   Vendor data breach → credential exposure     18.6k       0.0      59.7k   16.6%
...
ALL  total across all scenarios                  114.0k      45.5k    326.7k   66.2%

33.8% of simulated years cost nothing at all, while the worst 1% exceed EUR 648.8k.
```

Two things there are the point of the whole project.

**The distribution, not the mean.** A third of simulated years cost nothing while the worst 1% exceed €648k. A qualitative matrix would rate several of these "High" and stop; the justification for spending lives entirely in the tail.

**The ranking is not the intuitive one.** With a placeholder hourly cost the dramatic ransomware scenario ranked first. Once the hourly figure is *derived* — €659/h, because a small port's revenue per hour is genuinely modest — invoice fraud overtakes it, since that loss is direct and unrecoverable rather than deferred. A heat map would almost certainly have marked ransomware "critical" and business email compromise "medium".

And the answer to Problem #1 — given €25,000, what should this port buy?

```
Expected annual loss EUR 113,987 -> EUR 26,007 (77% reduction, ROSI +2.5x)

  C20  EUR 5,000  IG1  Incident response plan with exercises
  C02  EUR 4,000  IG1  Named vendor accounts with session logging
  C10  EUR 4,000  IG1  Asset and software inventory
  C01  EUR 3,000  IG1  Multi-factor authentication on all accounts
  ... 4 more

Mean falls 77%; the P99 tail falls only 64%.
```

Seven of the eight selected controls are CIS Implementation Group 1 — "essential cyber hygiene" — which is a result rather than a constraint: nothing restricted the optimiser to IG1, it simply bought the cheap fundamentals first.

The efficient frontier shows where spending stops paying: **ROSI turns negative at full-catalogue spend (−0.3×)**. Buying everything is worse than buying the right subset, which is the sort of finding a compliance checklist structurally cannot produce.

### Does assessing suppliers actually change anything?

That question deserves a test rather than an assertion, so `demo_pipeline.py` runs the same port and budget twice — once with generic scenario frequencies, once with frequencies derived from its actual suppliers — and sweeps across budgets, because agreement at any single budget would be coincidence.

**They disagree at 5 of 8 budget levels**, and in the right direction: the derived basis finds trojanized updates ~2× more likely than the generic prior and invoice fraud ~3× less likely, so it buys staged update testing earlier and payment verification later.

The graph also answers a question no per-vendor score can. Ranking suppliers by *revenue exposed* rather than by security posture puts the crane OEM at 80% and the MSP at 75% — concentration is a property of the topology, and a supplier touching everything is a risk even when it is well run.

### Does the model tell the truth?

`validate.py` replays six documented port incidents, keeping the two that *set* the estimates separate from four held out — checking a model against the data used to build it is a consistency check, not a validation.

**The first run failed 2 of 4, and the failure was the most useful thing the project has produced.** Barcelona and San Diego (both 2018) suffered ransomware *without stopping the quay*: IT was hit, ships kept working. The downtime estimate had a floor of 24 hours and could not produce that outcome at any percentile — the model was asserting that supplier-borne ransomware always becomes an operational outage.

The fix was structural rather than a parameter nudge: `disruption_probability` now separates "an incident happened" from "operations stopped", set to 0.67 from the evidence (4 of 6 incidents disrupted operations). Replay passes 4 of 4, and the sharper check matches too — **the model predicts 33% of ransomware events cause no operational downtime; 2 of 6 documented incidents (33%) had none.**

### Is it better than a heat map?

Same scenarios, same budget, both methods. The result is more interesting than "matrix bad":

- **Rank agreement +0.91** — the 5×5 matrix orders risks perfectly sensibly.
- **6 of 7 scenarios land in "Medium", spanning 4.2× in expected loss** — Cox's range compression, made concrete.
- **The optimiser wins at every budget tested**, by €1.6k–18.9k/yr, peaking at +17% of baseline at €15,000.

*A matrix can rank well and still allocate badly*, because it cannot see that a cheap control touching four amber risks beats an expensive one touching a single red. The test suite asserts rank agreement > 0.5 so the baseline stays a fair opponent rather than a straw man.

## Layout

| Path | Contents |
|---|---|
| `src/portscra/risk/` | PERT distributions, FAIR Monte Carlo engine, port economics |
| `src/portscra/vendor/` | NIS2-mapped questionnaire, AHP weighting, likelihood fusion |
| `src/portscra/controls/` | CIS Controls v8 catalogue, knapsack optimiser, tornado sensitivity |
| `src/portscra/graph.py` | Dependency graph: vendor → asset → port service, derived frequencies |
| `src/portscra/validation.py` | Incident replay, 5×5 matrix baseline, range compression |
| `src/portscra/examples.py` | The worked example supplier list (illustrative roles, not real firms) |
| `src/portscra/signals.py` | Live EPSS, CISA KEV and OpenSSF Scorecard, cached with a TTL |
| `app/streamlit_app.py` | Dashboard: move the budget slider, watch the recommendation change |
| `src/portscra/taxonomy/` | ENISA asset + threat taxonomies, scenario catalogue |
| `src/portscra/ais/` | DMA AIS download, streaming filter, port-call detection, day-boundary stitching |
| `scripts/` | `day_one.py`, `build_dataset.py`, `demo_risk.py`, `demo_vendors.py`, `demo_optimise.py`, `demo_pipeline.py`, `validate.py` |
| `tests/` | 277 tests, stdlib `unittest`, no external runner needed (signal tests use a fake session, so the suite runs offline) |
| `refs/` | ENISA 2019 + 2020 port cybersecurity reports, Rønne Havn 2024 annual report |
| `PLANNING.md` | Design rationale, alternatives analysis, dataset comparison |

## Data

**[Danish Maritime Authority AIS](http://aisdata.ais.dk)** — free, no registration, ~600 MB/day covering all Danish waters, daily files from 2006 to within days of the present.

**Anchor port: Rønne, Bornholm** (UN/LOCODE DKRNN). Small enough to be the real thing rather than a scaled-down proxy, genuinely mixed (ferry to Ystad/Køge/Sassnitz/Świnoujście, cargo, cruise, offshore wind), in the Baltic, and — the reason it beats the mainland alternatives — an **island port**, so an outage severs a supply line with no road detour. ENISA singles this out: port paralysis harms most "especially for the islands (food, fuel, etc.)".

A [Kaggle AIS dataset near Tallinn](https://www.kaggle.com/datasets/gaborvisky/ais-dataset) was evaluated and rejected as primary: Port of Tallinn moves ~29.8 Mt and 2M+ TEU across five harbours, which contradicts the small-port premise the entire system is built on. It is retained as a citation asset for the AIS-spoofing scenario. Full comparison in [PLANNING.md §5c](PLANNING.md).

## Design notes

**Why FAIR and not a risk matrix.** Ordinal arithmetic on 1–5 scales is formally unsound (Cox 2008, *What's Wrong with Risk Matrices?* — range compression, ranking reversals), and a matrix cannot produce the euro and hour figures the problem asks for. FAIR's factor tree is also transparent by construction: every number decomposes into inspectable parts, so the model can explain itself to a regulator.

**Why the Poisson step matters.** Multiplying frequency by magnitude gives you the mean and destroys the shape. A port with a 0.08/year ransomware frequency has no "average" year — it has quiet years and one catastrophic one, and the whole investment case lives in that asymmetry.

**Why every estimate carries a `source` string.** An estimate without provenance is a guess wearing a lab coat. There is a test that fails if any scenario input lacks one.

**Why the taxonomies are code, not a spreadsheet.** Tests verify that every scenario's referenced threats, impacts and assets actually exist, so a typo cannot silently produce a scenario that contributes nothing.

**Why an unassessed vendor scores mid-range, not low.** If skipping the questionnaire produced a good score, the cheapest route to looking safe would be silence. A vendor with no evidence lands at 0.5 posture, and coverage is always reported next to the number.

**Why signals are asymmetric.** Appearing in CISA KEV raises risk sharply; *not* appearing lowers it only slightly. Most software never receives the scrutiny that would put it there, so absence is weak evidence of safety while presence is strong evidence of danger. The live feeds make this concrete: **CVE-2024-3094 — the xz-utils backdoor — scores 0.86 on EPSS but is absent from KEV**, because it was caught before exploitation. One of the most serious supply-chain compromises yet found would score clean on a KEV-only check.

**Why no signal is ever typed by hand.** EPSS scores and KEV hits are things only a feed can report, so the example data carries *identifiers* (CVE ids, repository URLs) and leaves the signals empty until `refresh_signals.py` populates them. An earlier version typed them in, and it inflated one supplier's assessed risk from 7.6% to 13.3% on invented evidence. A test now fails if any hand-typed feed value reappears.

**Why the hourly cost is derived twice.** `economics.py` routes to €/hour from annual revenue and, independently, from revenue-per-call times the observed call rate. They agree to ratio 1.00 on a matched call basis. The cross-check paid for itself immediately: it caught a 15× unit error the first time it ran.

**Why AIS calls are stitched across midnight.** DMA publishes daily files, so a vessel alongside for three days looks like three 24-hour calls, and the dwell p90 pins at 23.9 h for reasons that have nothing to do with berth occupancy. Stitching plus a truncation tolerance wider than AIS's own 3-minute reporting interval moved the Passenger median from 9.01 h to 2.70 h — a real ropax turnaround, matching observation.

## Requirements

Python 3.11+, numpy, pandas, pyarrow, requests — plus Streamlit for the dashboard only. Install with `pip install -e .` (add `".[app]"` for the dashboard).

The scripts also run without installing: each falls back to `src/` on the path if `portscra` is not importable. Installing is worth it for notebooks, where the fallback would have to be repeated in every session.

```python
from portscra.examples import EXAMPLE_VENDORS
from portscra.graph import DependencyGraph, build_scenarios_from_vendors
from portscra.controls import CATALOGUE, optimise
```

## References

- ENISA, [*Port Cybersecurity — Good practices*](https://www.enisa.europa.eu/publications/port-cybersecurity-good-practices-for-cybersecurity-in-the-maritime-sector) (2019) — asset and threat taxonomies, attack scenarios
- ENISA, [*Cyber Risk Management for Ports*](https://www.enisa.europa.eu/publications/guidelines-cyber-risk-management-for-ports) (2020) — the four-phase approach this DSS operationalises
- The Open Group, Open FAIR (O-RT, O-RA) — risk quantification standard
- Hubbard & Seiersen, *How to Measure Anything in Cybersecurity Risk* — calibrated estimation
- [MITRE ATT&CK](https://attack.mitre.org/) — technique identifiers, including ATT&CK for ICS
- [EPSS](https://www.first.org/epss/) (FIRST) — daily exploitation probability per CVE, fetched live
- [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) — known-exploited catalogue, fetched live
- [OpenSSF Scorecard](https://securityscorecards.dev/) — open-source hygiene score, fetched live
- CIS Controls v8 — the mitigation catalogue (IG1 for the smallest persona)
- [Danmarks Statistik SKIB101](https://www.statbank.dk/SKIB101) — official Danish port call, cargo and passenger statistics
- Rønne Havn A/S, Årsrapport 2024 (CVR 27932150) — revenue, EBITDA and headcount behind the €/hour derivation

## Licence

MIT.
