"""The stream concept: the ``Stream`` ABC and the generic replay
implementation. An engine with a live event feed implements the verb in
its own package (``clients/claude/stream.py``); one without takes
:mod:`~lup.adapters.clients.streams.replay`."""
