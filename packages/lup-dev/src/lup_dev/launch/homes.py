"""A launch's home of the rooms' own: placed by its profile, logged in with its account, and what the operator is told of either (`docs/launch.md`, *A home of the rooms' own*).

The home is the project's, or the one every project shares where the profile
chooses it (`Layout.room_home`); the login is the account's file for the
runtime, made empty where there's none, so the runtime's own sign-in in the
room writes it; the configuration over the operator's is the profile's own
(`ProfilesLayout`). What's said, each where its reader needs it next:
- before the room starts, that the home is new, so the operator knows earlier
  sessions don't resume there until they're moved (`lup_dev.migration`), and
  that the account holds no login yet, so the sign-in they're about to see is
  the account's;
- what was left out of the configuration copied in, a line for what would run
  a command and one for what would hand the room a credential, each where it
  changed since the last launch on the profile said it;
- at the end, what the session saved that was carried back to the profile, and,
  the first time a launch sees an account's login change under it, that every
  room on the account shares that login.
"""

from typing import TYPE_CHECKING

from lup.sessions.terminal import Left, RuntimeHome, Why
from lup.types import Model
from lup_dev.accounts import Login
from lup_dev.declaration.profiles import Chosen
from lup_dev.layout import ToldLayout

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.layout import LaunchLayout, Layout


class LeftOut(Model):
    """What was last left out of a profile's configuration for a runtime, as it was said."""

    said: list[Left] = []


class LaunchHome(Model):
    """One launch's home of the rooms' own, and its login: where each is, and what the operator is told of them."""

    runtime: str
    """The runtime launched, by its adapter's name."""
    choice: Chosen
    home: RuntimeHome
    told: ToldLayout

    @classmethod
    def of(
        cls,
        layout: Layout,
        launch: LaunchLayout,
        repository: Path,
        runtime: str,
        *,
        choice: Chosen,
        login: Login,
    ) -> LaunchHome:
        """Place the home of the launch `launch` of `runtime`, in the repository whose git directory is `repository`, on the profile and account `choice` names, with the account's `login`: the launch's own directory, and the history it links into, the project's or the one every project shares."""
        profile = choice.profile
        return cls(
            runtime=runtime,
            choice=choice,
            home=RuntimeHome(
                directory=launch.runtime_home,
                shared=layout.room_home(
                    repository, runtime, shared=profile.rooms_home == "global"
                ),
                login=login.path,
                operators=profile.operator_configuration,
                layer=layout.profiles.profile(profile.name).runtime(runtime),
            ),
            told=layout.told,
        )

    @property
    def login(self) -> Login:
        """The account's login for the runtime."""
        return Login(runtime=self.runtime, path=self.home.login)

    def said(self) -> list[str]:
        """Say, before the room starts, what's new of its home and its login: a home not made yet, and an account with no login for the runtime."""
        profile = self.choice.profile
        whose = (
            "this project's rooms"
            if profile.rooms_home == "project"
            else f"the rooms of every project on the profile `{profile.name}`"
        )
        moving = (
            "lup-dev account migrate"
            if profile.rooms_home == "project"
            else "lup-dev account migrate --shared"
        )
        new = (
            f"This launch makes {self.home.shared}, where {self.runtime}'s "
            f"sessions in {whose} keep their history and state from now on, apart "
            "from your own: a session from before it resumes in a room once you "
            f"move it there, which `{moving}`, in your own terminal in the "
            "repository, says how to."
        )
        unheld = (
            f"The account `{self.choice.account}` holds no {self.runtime} login "
            f"yet: sign in when {self.runtime} asks in the room, and every room on "
            "the account is signed in with it."
        )
        return [
            *([] if self.home.shared.is_dir() else [new]),
            *([] if self.login.held() else [unheld]),
        ]

    def left(self, left_out: list[Left]) -> list[str]:
        """Say what was left out of the configuration copied into the room, each reason's in a line where it isn't what the last launch on the profile said; keep it as said."""
        kept = self.told.left_out(self.choice.profile.name, self.runtime)
        before = (
            LeftOut.model_validate_json(kept.read_text())
            if kept.is_file()
            else LeftOut()
        )
        if before.said == left_out:
            return []
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(LeftOut(said=left_out).model_dump_json())
        source = (
            f"the {self.runtime} configuration this room copies from yours and the "
            "profile's"
        )
        reasons: dict[str, list[Why]] = {
            "as each would run a command in the room, where rooms run lup's own hooks": [
                "command"
            ],
            "as each would hand the room's code a credential or isn't followed": [
                "credential",
                "unread",
            ],
        }

        def said(why: list[Why], reason: str) -> str | None:
            now = [each.said for each in left_out if each.why in why]
            was = [each.said for each in before.said if each.why in why]
            if not now or now == was:
                return None
            return f"Left out of {source}, {reason}: {'; '.join(now)}."

        return [
            line
            for reason, why in reasons.items()
            if (line := said(why, reason)) is not None
        ]

    def ready(self) -> str:
        """Make the account's login where there's none, and return what it holds, as `ended` compares it."""
        login = self.login
        login.made()
        return login.fingerprint()

    def ended(self, before: str) -> list[str]:
        """Say, the first time a launch sees the account's login change under it, that the login is every room's on the account; nothing where it didn't change, or where that was said."""
        account = self.choice.account
        mark = self.told.login(account, self.runtime)
        if self.login.fingerprint() == before or mark.exists():
            return []
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.touch()
        said = (
            f"The account `{account}`'s {self.runtime} login changed while this "
            "room ran, by a sign-in or a refresh: it's one login every room on "
            "the account shares, so a sign-in in one signs in every room on it, "
            f"and `lup-dev account logout {account} {self.runtime}` logs them all "
            "out."
        )
        return [said]
