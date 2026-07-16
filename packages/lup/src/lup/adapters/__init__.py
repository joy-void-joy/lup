"""Native implementations of Lup's independently composed capabilities.

Provider configuration, wire formats, event decoding, harness rendering, and
session construction stay in the named adapter package. Portable callers use
the narrow contracts and semantic models in :mod:`lup.runtime`,
:mod:`lup.harness`, and :mod:`lup.policy`.
"""
