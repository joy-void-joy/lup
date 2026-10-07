from lup_dev.errors import LupDevError


def test_root_error_is_an_exception() -> None:
    assert issubclass(LupDevError, Exception)
