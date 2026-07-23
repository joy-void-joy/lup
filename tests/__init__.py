"""Behavior tests for the lup framework and template.

Every test here answers one question: would it catch a realistic
regression an adopter would feel? Unit tests pin the load-bearing
surfaces offline — policy semantics on shared canonical/bundled
fixtures, harness determinism and reconciliation, the resolver's
commit authority, adapter wire seams, the realtime relay, and the
sandbox's pure decision logic — while ``-m integration`` adds the live
Docker and native-CLI lanes. The surface-by-surface map, the standard
itself, and the ranked uncovered gaps live in docs/test-suite-audit.md.
"""
