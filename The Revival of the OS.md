# The Revival of the OS

Oct 23, 2026 · @Simon

*Notes from a discussion with Claude, put out for discussion.*

This is not a finished argument. I had a hunch about where software is going, and one night I asked Claude whether it holds. The answers pushed back, I pushed back on some of them, and the idea changed shape along the way. What follows are the thoughts in the order they came up, including the wrong turns.

I think best when I build. So every thought here was tested by turning it into a rule for iterthink, the tool my company is rebuilding right now. Where a thought didn't survive a look at the existing code, I say so. Where it is still open, I'd like to hear what you think.

## 1. The starting thesis

Cloud companies captured the term operating system. CRM vendors, collaboration suites and data platforms all wanted to become the OS for your company. Your data moved into their databases, and the real operating system shrank to a launcher for the browser.

With AI, the OS has a chance to become the main part again. My first sketch of the stack was simple: an operating system, AI, files and databases, and apps, permanent or ad hoc, that manipulate the data. Very often no cloud needed. A revival of the basics: CSV, HTML, IFC, Markdown.

Claude's first reply: the direction holds, but two claims won't survive. The AI in that stack mostly runs in the cloud. And "OS" was doing double duty: the classic OS returning, or AI becoming the new OS? Those are different articles.

## 2. The cloud doesn't go away, it changes role

So I adjusted: AI as a synergy of local and cloud. Local orchestration, cloud power.

In SaaS, the vendor holds your data and you rent the interface. Here the machine holds the data, the files and the decisions, and rents intelligence by the call.

The objection that stays: renting intelligence is still a dependency. Local models are getting better, but they don't match the frontier yet. And if the OS becomes central again, Apple, Microsoft and Google are best placed to own that layer. A revival of the OS could also mean a new centralisation.

## 3. Linux, quietly

My next thought: this is a chance for Linux. Claude agreed, with a twist I liked. Agents work best in a shell, text in and text out, everything scriptable. Most coding agents already run in Linux containers.

So Linux may win as the environment agents live in, whatever the human sees on screen. iterthink runs on Fedora, Windows and macOS.

## 4. Files alone don't collaborate

The strongest objection to "just files": the cloud solved real problems. Sharing, permissions, backup, sync. Files don't. Claude suggested a thin cloud that only syncs, built on the model of Git. That clicked, especially once agents and humans work on the same files. An agent changes fifty files in a minute. Keeping track of those changes becomes the main work.

We called it Git for everyone: diffs, review, rollback, who changed what. Keep the model, hide the vocabulary. A commit becomes a version, a pull request becomes a proposal.

While writing the spec, review turned out to matter more than version control. It works like a permission system: humans, agents and generated apps all propose, nothing lands without a verdict. On the iterthink website we had written that most tools track files and iterthink tracks decisions. That describes it better than Git for everyone.

I'll have several agents working in parallel, so the spec includes a board to hand out tasks. Each task is a plain Markdown file any agent can read. Conflicts between agents are detected and shown in review, never resolved silently.

## 5. Chat isn't the interface. A line is.

Some argue chat becomes the main interface. I think it's fine for some tasks, not for all. Nobody wants to rotate a building model or check 200 rows by typing. Claude put it this way: chat is the new command line, and the command line never replaced the graphical interface.

Then I described the dream I had when I started iterthink. A white screen, one pulsing dot, one line: what do you want to do? Start typing and it begins. If you write, it becomes a document. If it goes back and forth, it's a chat. If you ask for a door schedule, a small app appears.

Claude asked the key design question: should the screen ever react while you type? My answer: no. Nothing until Enter. In a document, Enter is a new paragraph, so the AI waits for Mod+Enter. Voice works the same way; it's just another way to type.&#32;

## 6. Ad-hoc apps, and who sees the data

AI makes software cheap to produce. A small tool to clean a CSV or compare two model versions can be built in minutes, used once and thrown away. Many SaaS products start to look like expensive wrappers around a file or database and a few functions.

When I asked which building blocks I already had, the answer surprised me: most of them. Imports, comparison, impact checks, search, annotations. The impact analysis that iterthink started with is now just one block among many. Ad-hoc apps work best when the AI writes the glue, not the logic, and composes proven parts.

The best idea of the night came from asking how the app builder works. It's a prompt with the guidelines, handed to the model. But the model only needs to know the task and what the data looks like: file names, column headers, the property sets in a model. It writes the app; the app reads the actual data locally. A cloud model can build a door schedule without a single door leaving the machine. The dependency on the cloud model remains. The project data stays on the machine.

## 7. Work open, deliver closed

A small moment that taught me something. Claude's example for a door schedule app ended with "export to Word". I asked: why DOCX and not CSV? A door schedule is a table, and the whole thesis is open formats.

The default had slipped back in. The same happened with the frontend: Claude first proposed the usual TypeScript framework with a build step, and I asked why not plain HTML and JavaScript where needed, following my own simple rule. It agreed, with the trade-offs: less tooling, more state on the server. That's where we landed.

The rule that came out of it: inside a project, everything stays CSV, Markdown or JSON. Word, Excel and PDF only at the boundary, generated for whoever asks for them, never edited, never the source. In both cases Claude had agreed with the open-formats idea and still suggested the conventional option first.

## 8. Where the data lives

This one went through three rounds.

First, the spec said "manage one folder". I questioned it: shouldn't it be a base folder with project subfolders? Yes. The project is the unit of history, sharing and handover.

Second, the spec put iterthink's store in a fixed location under Documents. Wrong again. Source files stay where people already keep them, on a local disk or a network share. iterthink never moves them. Its own files move instead: a hidden folder inside each project carries the history, the log, the tasks and the generated apps. At the end of a job, you hand over the folder.

Third, that raised the question I didn't expect: is SQLite still the right model? A database file on a network share breaks when two people write to it, and it's a binary format nobody can read without the software. The answer we arrived at: files are the truth, the database is only an index. Each machine appends to its own plain text log. The database is rebuilt from it, locally. So iterthink's own records are open files too.

Underneath all of it sits one idea from our pragmaticBIM work: one table for content, one for relations. Documents, plans, models, chats, tasks and apps are all content with a kind; every link between them is a relation. Open files make the data readable. The contract makes sure different tools interpret it the same way.

Systems of record are different. Accounting and ERP won't move into CSV files, and they don't need to. They will stay, but they have to open up and become accessible through APIs, so their data can be used where the work happens. For us that means connecting bexio, our accounting software, to iterthink through its API.

## 9. Trust: a hash, not a blockchain

iterthink promises a sealed log of who decided what. Looking at the code, Claude found that the seal wasn't actually implemented yet. So we specced a hash chain: each log line carries the hash of the previous one.

Then I asked: is this a blockchain? No. A hash chain is what Git commits use. A blockchain adds consensus between parties who don't trust each other; we don't need that.

There's a limit: a hash chain is tamper-evident, not tamper-proof. Editing one line breaks the chain. But whoever controls all copies can rewrite everything and recompute the hashes. Real protection only comes from anchoring the chain somewhere the writer doesn't control: another machine, the client at handover, or a timestamp service. "Tamper-proof" was the wrong word on our own website.

## 10. Thinking by doing: iterthink

I'm testing these ideas on iterthink. Disclosure: iterthink is built by my company, abstract. It started as a tool that shows every change to a document, human or AI, and whether it matters.

Nothing described here is built yet. What exists is the current iterthink, and a spec for the next version. Before writing the spec, Claude read through the existing code. A large part of it is interface code, and the logic underneath barely depends on it: change detection, impact checks, search, imports, the model router. If the analysis holds, the rebuild replaces the interface and keeps most of the logic. That would support the thesis that the value sits in the logic and the data. Whether it holds is what the build will show.

The spec is the result of this discussion. Every thought in these notes ended up as a rule in one file that I hand to the coding agent. I'm publishing it alongside this article, in the [iterthink repository](https://github.com/simondilhas/iterthink) as `.cursor/rules/iterthink-2.mdc`. It is the plan, not the finished state, and it will change once it meets the code.

Put together, the pieces map onto the classic operating system, layer by layer.

&#91;embedded content: the new OS stack · 6 layers\]

The planned stack follows its own argument: plain HTML in a native window, Python underneath, no build step, files as the truth. Writing a spec for an AI agent is itself part of the experiment.

## Open questions

These are the ones I haven't settled. I'd like to hear where you disagree.

- **Who owns the layer?** If the OS becomes central again, do Apple, Microsoft and Google simply take it, or do open formats and Linux keep it open?
- **How local can it get?** Is separating code generation from data access enough, or does real independence need local models that match the cloud?
- **Does a decision record need a standard?** Provenance standards and BCF in BIM exist, but nothing covers who decided what on project documents. Should it be one?
- **Is "wait for Enter" too strict?** Silence makes the AI predictable. Does it also make it less useful?
- **Can several people share a project without a server?** Append-only logs per machine work in theory. Real offices with NAS drives and OneDrive will test it.
- **Does dictation work on site?** Speech-to-text handles Standard German well. Swiss German from a site meeting is another matter.

## 11. Pressed go

The notes above are the background. Another chapter comes after I have watched this build and thought about what it did.

The spec is one file, and it is long enough that an agent will wander if I only say "build this". So the work is cut into slices. Each slice is one part of the app and the tests that prove it. The agent writes the tests, watches them fail, and writes the code that makes them pass. Then it takes the next slice. It keeps going for as long as the next slice can start.

Three things are already written, and the agent builds on them. The bridge: every function the window, an ad-hoc app, or another agent is allowed to call. A working stand-in for that bridge, so the window can be opened before the history exists. And the tests that say how the bridge must behave. The agent leaves those files alone. When one of them is wrong, it writes the case down and continues with the rest.

Flet goes. The new window is plain HTML in a native shell, Python underneath, no build step. Change detection, impact checks, search, imports and the model router stay. Version history in this build is a snapshot per save, named by the hash of its contents, in the project folder. The log stays a hash chain, tamper-evident. Jujutsu, sync, and a connector for the accounting system stay written down for later.

I pressed go. I'll keep you posted on what happens.
