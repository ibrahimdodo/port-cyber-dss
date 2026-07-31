---
title: PortSCRA — Supply-Chain Cyber Risk for Small Ports
emoji: ⚓
colorFrom: blue
colorTo: gray
sdk: streamlit
sdk_version: 1.52.2
app_file: app/streamlit_app.py
pinned: false
license: mit
short_description: Quantified supply-chain cyber risk and budget-constrained control selection for a small EU port
---

# PortSCRA

A decision support system for a port too small to have a security team. It answers
two questions:

1. **If one of our suppliers is compromised, what does it cost us?** — in euro, in
   hours of downtime, in percent of operations disturbed.
2. **Given a fixed budget, which security controls should we buy first?**

The worked example is **Rønne, Bornholm**: 34 employees, sole supply port for an
island, and therefore in scope of NIS2 under Article 2(2)(b) despite sitting below
the size threshold. Legally obligated, operationally critical, far too small to run
a security function.

## What to try

* **Drag the budget slider** on the Portfolio tab and watch the recommendation change.
  ROSI turns negative before the catalogue is exhausted — buying everything is worse
  than buying the right subset.
* **Switch the frequency basis** in the sidebar between generic priors and
  frequencies derived from this port's actual suppliers. They disagree at most
  budgets.
* **Answer the Awareness vignettes** as your staff would, and watch the expected loss
  move. Training is weighted by how much of each scenario is genuinely under human
  control — invoice fraud a lot, a signed trojanized update barely at all.
* **Read the Validation tab.** The held-out incident replay failed on first run and
  the model was changed as a result.

## Where the numbers come from

Nothing here is a placeholder.

* **€659 per outage hour** derived from Rønne Havn A/S's 2024 audited accounts
  (€22.76M revenue, 3,043 calls), reduced by a call-dependent share and an
  unrecoverable share, and cross-checked against an independent revenue-per-call
  derivation.
* **Traffic and berth occupancy** from four seasonal weeks of Danish Maritime
  Authority AIS, reconciled against Danmarks Statistik's official port series.
* **Supplier signals** fetched live from EPSS, CISA KEV and OpenSSF Scorecard.
* **Scenarios** grounded in the ENISA port threat taxonomy, tagged with MITRE ATT&CK
  techniques, and anchored to documented incidents.

Suppliers shown are **illustrative roles, not real companies**. Naming real firms
would assert things about their security this project has no evidence for.

## Source

Full source, 357 tests, and five narrative notebooks:
**https://github.com/ibrahim-desh/port-cyber-dss**
