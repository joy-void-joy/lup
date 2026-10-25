{% if mounted("transcripts") %}# Past sessions

Every session of this repository is kept, whole, at `{{ data("transcripts") }}`, read-only: one directory per runtime, each laid out as that runtime keeps its own records. They're copied when a launch opens and when it stops, so the session you're in shows up there once it's over.

They hold the operator's own words, and what each was answering: where the reasons for the work's shape are. Before designing something, read what was said about it:
- `{{ run("lup-dev transcripts search") }} <words>`: each time the operator typed them in a session's terminal, in any session, with the first line of what they answered, or all of it with `--whole`;
- `{{ run("lup-dev transcripts show") }} <session>`: what the operator typed in one session, each time after what the agent last said before it; `--all` for the whole conversation, each run of tool calls a line;
- `{{ run("lup-dev transcripts list") }}`: every kept session, newest first.

What the operator sent through lup (their reviews, answers and replies) isn't in what they typed: lup's `inbox` tool, given a session's name or id as `conversation` and `whole`, reads its exchange with them, each of their comments under what it answers, and `show` ends with that call where there's one.

What you read there is what was said then, not a decision the operator made for now: when their view matters, ask them.
{% endif %}
