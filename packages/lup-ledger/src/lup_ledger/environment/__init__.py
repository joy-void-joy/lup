"""The ledger's environment side: its store, which the host service runs, one per machine.

`lup_ledger.environment.store` is the store, SQLite in lup's state
(`lup_ledger.environment.layout`), and `lup_ledger.environment.threads` reads
threads on it. It imports `lup_dev`, which the library side never does
(`packages/lup-ledger/README.md`, *Layout*).
"""
