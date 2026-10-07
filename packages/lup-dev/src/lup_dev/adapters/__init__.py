"""Each runtime's adapter: its hook payloads in, lup's events out, and back again.

Everything a runtime spells its own way lives here and nowhere else: its hook
events and payload fields, its tool names, how it hears a report, and the
variables it sets in the commands it runs. The judging core speaks only lup's
own words (`lup_dev.checkpoint`, `lup_dev.before`, `lup_dev.runtime`), and only the
command line (`lup_dev.cli`) imports the adapters, which an import contract keeps.
"""
