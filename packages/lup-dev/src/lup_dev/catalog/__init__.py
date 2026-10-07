"""The data that sets lup's policy: what each rule is, which paths have which role.

Everything here is data, as models from `lup.types.Model` with no logic of their
own: the modules that act on it (`lup_dev.roles`, the engine's client) read it from
here. Since it decides what lup allows, asks and refuses, the subpackage is a
protected path in lup's own declaration, so the operator reviews every change to
it before it lands.
"""
