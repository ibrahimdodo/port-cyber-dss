# PortSCRA — Supply-Chain Cyber Risk Assessment for Small EU Ports

A decision support system that answers two questions for a port too small to have a security team:

1. **If one of our suppliers is compromised, what does it cost us?** — in euro, in hours of downtime, in percent of operations disturbed.
2. **Given a fixed budget, which security controls should we buy first?**

Every accessible tool in this space — [CISA CSET](https://www.cisa.gov/resources-tools/services/cyber-security-evaluation-tool-csetr), [MONARC](https://www.monarc.lu/), SimpleRisk — stops at a qualitative heat map. Commercial platforms (BitSight, SecurityScorecard, UpGuard) are black-box, enterprise-priced and port-blind. This project quantifies instead, in the port's own operational terms, and then optimises the spend.

> **Status: in development.** The risk engine, ENISA-derived taxonomies and AIS pipeline are built and tested. The vendor-likelihood engine, control optimiser and Streamlit dashboard are next. See [PLANNING.md](PLANNING.md) for the full design rationale, the solution landscape survey, and the rejected alternatives.

---

## Why this problem

Ports are Annex I "Transport — Water" entities under **NIS2** (Directive (EU) 2022/2555). Article 21(2)(d) makes supply-chain security a legal obligation, Article 20 puts liability and training duties on management, and Article 23 imposes 24h/72h incident reporting. Meanwhile the attacks that matter arrive *through suppliers*: SolarWinds, Kaseya, MOVEit, xz-utils.

Ports get hit and it costs real money — Maersk/NotPetya 2017 (~$250–300M, 76 terminals halted), Port of Nagoya 2023 (LockBit, ~2.5 days of container operations lost), DP World Australia 2023 (~3 days, ~30,000 containers stranded). These are the calibration anchors for the consequence model, not decoration.

The user is a 100-person port ecosystem with no security function, choosing between an MFA rollout and a managed SIEM subscription. That decision deserves a number, not a colour.

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
# Run the risk engine — no data download needed
python scripts/demo_risk.py

# Validate the AIS pipeline against one real day (~600 MB download)
python scripts/day_one.py --date 2026-03-02

# Tests
PYTHONPATH=src python3 -m unittest discover -s tests
```

Sample output from `demo_risk.py` (placeholder cost figures pending AIS calibration):

```
ID   scenario                                        ALE       P50       P90   P(any)
S2   Managed service provider compromise ...      52.5k       0.0       0.0     9.2%
S3   SaaS account takeover → invoice fraud        36.6k       0.0     146.5k   28.9%
...
ALL  total across all scenarios                  171.6k      70.9k    483.6k   65.8%

34.2% of simulated years cost nothing at all, while the worst 1% exceed EUR 1.13M.
```

That last line is the point. A qualitative matrix would rate several of these "High" and stop; the distribution shows that most years are quiet and the justification for spending lives entirely in the tail.

## Layout

| Path | Contents |
|---|---|
| `src/portscra/risk/` | PERT distributions, FAIR Monte Carlo engine |
| `src/portscra/taxonomy/` | ENISA asset + threat taxonomies, scenario catalogue |
| `src/portscra/ais/` | DMA AIS download, streaming filter, port-call detection |
| `scripts/` | `day_one.py` (AIS validation), `demo_risk.py` (engine demo) |
| `tests/` | 69 tests, stdlib `unittest`, no external runner needed |
| `refs/` | ENISA 2019 and 2020 port cybersecurity reports |
| `PLANNING.md` | Design rationale, alternatives analysis, dataset comparison |

## Data

**[Danish Maritime Authority AIS](http://aisdata.ais.dk)** — free, no registration, ~600 MB/day covering all Danish waters, daily files from 2006 to within days of the present.

**Anchor port: Rønne, Bornholm** (UN/LOCODE DKRNN). Small enough that a 100-person persona is credible, genuinely mixed (ferry to Ystad/Køge/Sassnitz/Świnoujście, cargo, cruise, offshore wind), in the Baltic, and — the reason it beats the mainland alternatives — an **island port**, so an outage severs a supply line with no road detour. ENISA singles this out: port paralysis harms most "especially for the islands (food, fuel, etc.)".

A [Kaggle AIS dataset near Tallinn](https://www.kaggle.com/datasets/gaborvisky/ais-dataset) was evaluated and rejected as primary: Port of Tallinn moves ~29.8 Mt and 2M+ TEU across five harbours, which contradicts the small-port premise the entire system is built on. It is retained as a citation asset for the AIS-spoofing scenario. Full comparison in [PLANNING.md §5c](PLANNING.md).

## Design notes

**Why FAIR and not a risk matrix.** Ordinal arithmetic on 1–5 scales is formally unsound (Cox 2008, *What's Wrong with Risk Matrices?* — range compression, ranking reversals), and a matrix cannot produce the euro and hour figures the problem asks for. FAIR's factor tree is also transparent by construction: every number decomposes into inspectable parts, so the model can explain itself to a regulator.

**Why the Poisson step matters.** Multiplying frequency by magnitude gives you the mean and destroys the shape. A port with a 0.08/year ransomware frequency has no "average" year — it has quiet years and one catastrophic one, and the whole investment case lives in that asymmetry.

**Why every estimate carries a `source` string.** An estimate without provenance is a guess wearing a lab coat. There is a test that fails if any scenario input lacks one.

**Why the taxonomies are code, not a spreadsheet.** Tests verify that every scenario's referenced threats, impacts and assets actually exist, so a typo cannot silently produce a scenario that contributes nothing.

## Requirements

Python 3.11+, numpy, scipy, pandas, pyarrow, requests. Everything currently implemented runs on those; see `requirements.txt` for the full set including planned dependencies.

## References

- ENISA, [*Port Cybersecurity — Good practices*](https://www.enisa.europa.eu/publications/port-cybersecurity-good-practices-for-cybersecurity-in-the-maritime-sector) (2019) — asset and threat taxonomies, attack scenarios
- ENISA, [*Cyber Risk Management for Ports*](https://www.enisa.europa.eu/publications/guidelines-cyber-risk-management-for-ports) (2020) — the four-phase approach this DSS operationalises
- The Open Group, Open FAIR (O-RT, O-RA) — risk quantification standard
- Hubbard & Seiersen, *How to Measure Anything in Cybersecurity Risk* — calibrated estimation
- [MITRE ATT&CK](https://attack.mitre.org/) — technique identifiers, including ATT&CK for ICS
- [EPSS](https://www.first.org/epss/) (FIRST) — daily exploitation probability per CVE
- CIS Controls v8 — the mitigation catalogue (IG1 for the smallest persona)

## Licence

MIT.
