"""The models `lup_dev` keeps in files: each read whole, and replaced whole in one step.

Where each lives is `layout.py`'s; this is how one is read and written, by every
subsystem keeping one: the judge's store and records (`lup_dev.policy`), trust on
launch's approval (`lup_dev.launch`), and the inbox's files of an earlier lup,
read once to convert them onto the ledger (`lup_dev.inbox.conversion`).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel


def read_model[M: BaseModel](path: Path, model: type[M]) -> M | None:
    """Read the model stored at `path`, or return none where nothing is stored."""
    if not path.is_file():
        return None
    return model.model_validate_json(path.read_text())


def write_model(path: Path, value: BaseModel) -> None:
    """Store `value` at `path`, replacing what was there in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.partial")
    partial.write_text(value.model_dump_json(indent=2))
    partial.replace(path)
