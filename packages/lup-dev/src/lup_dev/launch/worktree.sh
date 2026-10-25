# The room's hook's last step where the host service's answer may name a
# worktree for the room to make (docs/host.md, *The one hook*): run by
# `printing` (launch/session.py) as `sh -c <this> worktree <event>`, the answer
# on standard input.
#
# The worktree is named a field a line, its root first, then the worktree git
# makes it from, its new branch and its commit (`Making.lines`,
# policy/worktrees.py). It's made here with the room's own git, which writes to
# standard error alone, so its checkout never runs the host's git configuration
# on what the room committed.
#
# - `asked`, a worktree the runtime asks for: an answer that isn't a path is why
#   the judge makes none, said on standard error, and the hook ends with status
#   1, as it does where git fails, which fails the making; else the root is
#   printed, the last line the runtime reads.
# - `started`, a call's start: an answer naming a worktree first, a call
#   spawning a subagent lup isolates, has it made, then the rest printed, the
#   answer the runtime reads (docs/judging-writes.md, *A subagent lup
#   isolates*); where git fails, the hook ends with status 2, which blocks the
#   call, telling the agent why. Any other answer, JSON, is printed as it is.

event=$1
answer=$(cat && echo .)
answer=${answer%.}
case $answer in
/*) ;;
*)
	if [ "$event" = started ]; then
		printf %s "$answer"
		exit 0
	fi
	printf %s "$answer" >&2
	exit 1
	;;
esac
{ read -r root; read -r origin; read -r branch; read -r commit; } <<EOF
$answer
EOF
if ! git -C "$origin" worktree add --quiet -b "$branch" "$root" "$commit" >&2; then
	[ "$event" = asked ] && exit 1
	echo "lup couldn't make $root, the worktree of the subagent this call spawns, so the call didn't run." >&2
	exit 2
fi
if [ "$event" = asked ]; then
	printf '%s\n' "$root"
	exit 0
fi
newline='
'
for field in root origin branch commit; do
	answer=${answer#*"$newline"}
done
printf %s "$answer"
