"""Point the shipped lup registration at the template a project was generated from.

`sync.json` ships naming lup's own repository, which is right for every
project generated from lup and wrong for one generated from a fork of it: the
registration would mount, review and merge the copied half from a repository
the project was never stamped from. The forge knows which it was -- GitHub
records the template a repository was generated from -- so initialization
asks once and writes the answer where the project keeps it.

Where the project resolves lup from a repository, the registration follows
that pin rather than its own ``url`` (:func:`lup.devtools.sync.completed`), so
the pin is what has to name the template, and moving a pin is
``dev library git``'s: this says which command moves it rather than writing a
second copy of the answer.
"""

import json
from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.devtools import sync
from lup.devtools.utils import decode_stderr, gh, slug_from_remote
from lup.harness.credential import (
    parse_remote,
    remote_url,
    resolved_host,
    same_repository,
)


class TemplateRepository(BaseModel, frozen=True):
    """The repository GitHub says another was generated from."""

    clone_url: str


class GeneratedRepository(BaseModel, frozen=True):
    """The one field of GitHub's repository document this reads."""

    template_repository: TemplateRepository | None = None


class TemplateOrigin(BaseModel, frozen=True):
    """What the forge answered about where one repository was generated from."""

    repository: str = ""
    """The template's clone URL, empty where it was generated from none."""

    unanswered: str = ""
    """Why the forge could not be asked, empty where it answered."""


def template_origin(origin: str) -> TemplateOrigin:
    """Ask the forge which template the repository at ``origin`` came from.

    The host is the one the remote reaches: an ssh config alias is resolved
    first, because `gh` knows forges by hostname and an alias names none.
    """
    address = parse_remote(origin)
    slug = slug_from_remote(origin)
    if address is None or not slug:
        return TemplateOrigin(
            unanswered=f"the origin remote ({origin or 'none'}) names no forge repository"
        )
    host = address.host if address.proxied else resolved_host(address.host)
    try:
        document = gh.out("api", "--hostname", host, f"repos/{slug}")
    except sh.CommandNotFound:
        return TemplateOrigin(unanswered="gh is not installed")
    except sh.ErrorReturnCode as error:
        return TemplateOrigin(
            unanswered=f"gh api repos/{slug} failed: {decode_stderr(error)}"
        )
    template = GeneratedRepository.model_validate_json(document).template_repository
    return TemplateOrigin(repository=template.clone_url if template is not None else "")


def point_at_template(root: Path, name: str, dry_run: bool) -> bool:
    """Make the ``name`` registration mean the template this project came from.

    Answers whether the registration now means it, or already did. Nothing is
    written where the forge could not be asked, where the project was
    generated from no template, or where a git pin decides which repository
    the registration means -- that last one is said, with the command that
    moves the pin.
    """
    registration = next(
        (entry for entry in sync.load_projects(root) if entry["name"] == name), None
    )
    if registration is None:
        typer.echo(f"No '{name}' registration in sync.json, so none to point.")
        return False
    current = sync.registered_repository(registration)
    found = template_origin(remote_url(root, "origin"))
    if found.unanswered:
        typer.echo(
            f"Could not ask which template this repository was generated from: "
            f"{found.unanswered}. '{name}' stays {current or 'unplaced'}; where "
            f"the template is another repository, set \"url\" on the '{name}' "
            "entry in sync.json to it."
        )
        return False
    if not found.repository:
        typer.echo(
            f"This repository was generated from no template, so '{name}' stays "
            f"{current or 'unplaced'}."
        )
        return True
    if current and same_repository(current, found.repository):
        typer.echo(
            f"'{name}' already means {current}, the template this repository "
            "was generated from."
        )
        return True
    pinned = sync.pinned_source(name, root)
    if pinned is not None:
        typer.echo(
            f"'{name}' follows the git pin in pyproject.toml, which names "
            f"{pinned.url}; this repository was generated from "
            f"{found.repository}. To build on it: uv run lup-devtools dev "
            f"library git --url {found.repository} --{pinned.ref_kind} {pinned.ref}"
        )
        return False
    declared = sync.load_json(root / "sync.json")
    if not any(entry["name"] == name for entry in declared["projects"]):
        typer.echo(
            f"sync.json declares no '{name}' registration -- it is this "
            "machine's alone -- so there is no committed one to point."
        )
        return False
    declared["projects"] = [
        sync.PROJECT_ENTRY_ADAPTER.validate_python({**entry, "url": found.repository})
        if entry["name"] == name
        else entry
        for entry in declared["projects"]
    ]
    if not dry_run:
        (root / "sync.json").write_text(json.dumps(declared, indent=2) + "\n")
    typer.echo(
        f"{'Would point' if dry_run else 'Pointed'} '{name}' at "
        f"{found.repository} in sync.json (it meant {current or 'nothing'}); "
        "the next launch materializes and mounts it."
    )
    cached = sync.cached_clone(name)
    held = remote_url(cached, "origin") if cached is not None else ""
    if cached is not None and held and not same_repository(held, found.repository):
        typer.echo(
            f"  {cached} holds a clone of {held}, which is refused under this "
            "name from now on: remove it so the next launch clones the template."
        )
    return True
