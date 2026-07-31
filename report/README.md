# Report

`portscra_report.tex` — IEEE conference format (IEEEtran), self-contained.

```bash
pdflatex portscra_report.tex
pdflatex portscra_report.tex   # twice, for cross-references
```

No external `.bib` is needed; references use `thebibliography`. IEEEtran ships with
TeX Live and MiKTeX, and is also available from
<https://www.ieee.org/conferences/publishing/templates.html>.

Every quantitative claim in the paper was checked against the executing
implementation rather than transcribed from earlier notes. Three figures were found
stale on that check — they pre-dated the disruption-probability change that the
incident replay forced — and were corrected. If the model changes again, re-verify
before submitting.
