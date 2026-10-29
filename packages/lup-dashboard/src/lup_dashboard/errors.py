"""The root of the errors `lup_dashboard` raises."""


class LupDashboardError(Exception):
    """The root of every error `lup_dashboard` raises, so one clause catches them all."""


class CopyError(LupDashboardError):
    """A copy of the operator's dashboard state the demo can't serve: one of its files this checkout's code doesn't read, said with the file and why, or the host not giving one."""
