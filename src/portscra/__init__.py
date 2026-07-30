"""PortSCRA -- supply-chain cyber risk assessment for small EU ports.

A decision support system that answers two questions for a port too small to
have a security team:

1. If a supplier is compromised, what does it cost us -- in euro, in hours of
   downtime, in percent of operations disturbed?
2. Given a fixed budget, which controls should we buy first?

The approach is quantitative (FAIR-style Monte Carlo over scenarios grounded in
the ENISA port taxonomies) rather than the qualitative heat map that every
accessible tool in this space stops at.
"""

__version__ = "0.1.0"
