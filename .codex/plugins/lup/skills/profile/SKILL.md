---
name: profile
description: Read, select, and switch the account a session runs as
---

# The Account a Session Runs As

A profile is a configuration home with its own saved login. Which one a
session uses is settled when the process starts, from the environment variable
naming that home — so selecting a profile and moving a running session onto
one are two different operations, and this skill keeps them apart rather than
letting one read as the other.

## Input

**Arguments**: the arguments supplied with this skill invocation

The first token is the verb and the second is a profile name:

- **`list`**, or nothing — every profile, which one this session is on, and
  whether each holds a login.
- **`use <name>`** — select the profile a later launch takes by default.
  Changes nothing about the session you are in.
- **`switch <name>`** — move *this* session onto that profile now.

Where the verb is absent, Ask the user directly, offering concrete options, and wait for the answer: which profile to act on, and whether to select it for the next launch or switch this session onto it now. Where a verb names no profile, run `list`
first and put the roster in front of the person rather than guessing which of
their accounts they meant.

## Reading the roster

```bash
uv run lup-devtools harness profile list
```

It marks the selected profile, gives each one's configuration home, and says
which hold a login. Report the home as well as the name: two profiles differ
by nothing a person can see except where their credentials live.

Which profile *this* session is on is a separate question, and the roster does
not answer it — the roster is about what a launch would select, and a running
session was launched with whatever it was launched with. Read the environment
variable naming the configuration home, and say which profile's home it is, or
that it is one no profile claims.

## Selecting for a later launch

```bash
uv run lup-devtools harness profile use <name>
```

Then say plainly that the running session is unaffected and the next one will
take it. A person who asked to "switch" and was given this has been answered
with something else, so name the difference rather than letting the success
line imply the switch happened.

## Switching the running session

The session reads its configuration home once, at startup, and the
environment variable naming it cannot be changed from inside. What *can*
change is what that home contains, and whether the session re-reads it.

So a switch is two moves, and both have to land:

1. **Seed the active home** from the named profile's saved login. Under a
   contained session the active home is the container's own state rather than
   the profile's directory, so this leaves the source profile untouched;
   confirm that before writing, because a home that *is* the profile's
   directory would be overwritten with another account's login.
2. **Make the session re-read it**, by putting `/login` into the session's own
   input the way a person typing it would.

**Report which of the two you actually achieved, separately.** The second move
rests on `/login` re-reading a saved login from disk rather than opening a
fresh interactive sign-in, and that is a property of the runtime rather than
of this repository. Where it opens a sign-in instead, say so: the seeding
still happened, and the person finishes in the dialog.

Where either move is unavailable, fall back to selecting the profile and
printing the exact command that starts a new session on it. A relaunch is a
real answer to "switch me to this account"; a claimed switch that did not
happen is not.

## Afterwards

Read the roster again and report which account the session is on now, measured
rather than assumed — the switch either moved it or it did not, and the only
honest report is the one that looked.
