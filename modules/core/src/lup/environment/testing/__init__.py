"""The testing submodule's environment side: the harness as the gate runs it, checking promises, and the pytest plugin that runs them.

lup runs here in the process checking it, on an event loop whose order
hypothesis draws and whose clock moves only to the next timer, with no real
time and no processes (`lup/testing/README.md`, *Time and order*).
"""
