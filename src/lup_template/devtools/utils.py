"""Pre-configured shell commands for devtools scripts."""

import sh

git = sh.Command("git").bake("--no-pager", "-c", "color.ui=never", _tty_out=False)
gh = sh.Command("gh").bake(_tty_out=False)
uv = sh.Command("uv")
