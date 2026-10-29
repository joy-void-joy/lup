"""The ledger: lup's typed graph of nodes and edges, and threads, its first kind.

The library side, what code calling agents may import: the records
(`lup_ledger.records`), who writes them (`lup_ledger.parties`), threads and how
one stands (`lup_ledger.threads`), and the root error (`lup_ledger.errors`).
The store the host service runs is the environment side,
`lup_ledger.environment`, which this package never imports
(`packages/lup-ledger/README.md`, *Layout*).
"""
