# Continue the build

Run the slice named in the argument (e.g. `/next-slice A1`) following
`docs/agent-prompt.md` and `AGENTS.md`. Without an argument, pick the
lowest-id slice with `status: ready` whose `depends_on` are all `done`.
When it is done or blocked, start the next slice that can start. Stop when
none can. Nobody answers questions during the run; never stop to ask.
