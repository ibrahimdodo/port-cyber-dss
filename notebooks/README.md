# Notebooks

Five notebooks that walk the pipeline end to end. **Outputs are committed**, so they
read on GitHub without running anything.

| | |
|---|---|
| [1 · The port and the numbers](01_the_port_and_the_numbers.ipynb) | Rønne, AIS traffic, and the derivation of €659 per outage hour from audited accounts |
| [2 · Suppliers](02_suppliers.ipynb) | Questionnaire, AHP weighting with a consistency check, live EPSS/KEV/Scorecard, concentration |
| [3 · Risk](03_risk.ipynb) | Frequencies derived from *this* port's suppliers, Monte Carlo, loss exceedance |
| [4 · The decision](04_the_decision.ipynb) | Budget-constrained optimiser, efficient frontier, tornado sensitivity |
| [5 · Validation](05_validation.ipynb) | Held-out incident replay, duel against a 5×5 matrix, ENISA maturity |

## Running them

```bash
pip install -e .          # then the notebooks need no path juggling
jupyter lab notebooks/
```

## Regenerating

The notebooks are generated from [`build_notebooks.py`](build_notebooks.py) rather
than hand-edited, so they stay consistent with each other and can be rebuilt after
the library changes. Building also executes them, which is what embeds the outputs.

```bash
python notebooks/build_notebooks.py            # build and execute
python notebooks/build_notebooks.py --no-exec  # build only
```

Notebook 1 reads `data/processed/portcalls-all.parquet` (82 kB, committed), so no AIS
download is needed. Notebook 2 fetches live vulnerability feeds and degrades to cached
or unset values without failing when offline.
