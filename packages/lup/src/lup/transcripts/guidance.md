{% if mounted("transcripts") %}# Past sessions

Every session of this repository is kept, whole, at `{{ data("transcripts") }}`, read-only: one directory per runtime, each laid out as that runtime keeps its own records. They're copied when a launch opens and when it stops, so the session you're in shows up there once it's over.

They hold the operator's own words, and what each was answering: where the reasons for the work's shape are. Before designing something, read what was said about it:
- `{{ run("lup-dev transcripts search") }} <words>`: each time the operator said them, in any session, with the first line of what they answered;
- `{{ run("lup-dev transcripts show") }} <session>`: what the operator said in one session, each time after what the agent last said before it; `--all` for the whole conversation, each run of tool calls a line;
- `{{ run("lup-dev transcripts list") }}`: every kept session, newest first.

What you read there is what was said then, not a decision the operator made for now: when their view matters, ask them.
{% endif %}
