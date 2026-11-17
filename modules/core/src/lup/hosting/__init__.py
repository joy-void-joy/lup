"""The parts that run on the operator's machine: what starts every container, carries calls between them, keeps the operator's approvals and secrets, and brokers their credentials.

Each is a part like any other, its doors checked by promises, but it holds the
machine (`machine=True`) and is one for the whole machine (`shared=True`): it
runs there, from the home repository's approved commit, and only the machine's
own parts may call what's privileged in it (`Machine`). Its reasons are in
`README.md` here.
"""
