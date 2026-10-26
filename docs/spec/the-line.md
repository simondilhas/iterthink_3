# The line (start screen and universal entry)
White screen, one centered line: "What do you want to achieve?", the dot
next to it (its pulse carries the state, see Recall and state). Nothing else
on screen: no project list, no folder form.
A quiet three-dot menu in the top right holds Open project and Open folder;
everything else happens through the line ("open project" lists projects to
pick from, a project name opens it, a folder path lists its folders).
The mode emerges from what the user does; the user never picks a mode first.

## Core rule
- The AI never reacts while the user types. No suggestions, no autocomplete,
  no "make this a table?" hints. It acts only when invited.
- Invitation = Enter in the line and in chat; Mod+Enter wherever Enter
  already has a job (document, app).
- Surfaces open full width with nothing around them. Explorer, history,
  checks and review open as panels on demand, never by default. The 1.x
  three-column layout is gone.

## First Enter decides the mode
`services/intent.py` classifies the line (via `llm_router`, small local model
first) and returns a mode plus a plan. The AI builds the surface; it does not
fill it unless asked.

| Line example                              | Mode     | Result                                             |
|-------------------------------------------|----------|----------------------------------------------------|
| "Fire protection concept, Schulhaus Basel"| document | new .md with that title, cursor ready, no AI text  |
| "Which doors are EI 30?"                  | chat     | chat with the answer                               |
| "Compare spec v6 and v7"                  | review   | review screen for the two versions                 |
| "Door schedule from the model"            | app      | ad-hoc app (table) generated for the task          |
| file dropped on the screen                | review   | what changed since the last version, or import     |
| "Have an agent check all specs"           | task     | task files in Backlog with a proposed split        |

Low confidence → do not guess silently: build the most likely surface and show
one quiet line "Opened as document · switch" with the alternatives.

## Enter by mode
| Mode     | Enter                          | Mod+Enter                           |
|----------|--------------------------------|-------------------------------------|
| line     | hand over, decide mode         | same as Enter                       |
| document | new paragraph                  | AI on current paragraph / selection |
| chat     | send                           | send                                |
| app      | confirm current field / action | ask the AI to change the app        |

Shift+Enter is a line break in line and chat.

## Recall and state
- Mod+K, or `/` at the start of an empty paragraph, brings the line back from
  any mode. It is scoped: inside a document it acts on that document; on the
  start screen on the project.
- The dot carries state:

  | State                            | Dot                                   |
  |----------------------------------|---------------------------------------|
  | idle                             | ink colour, slow pulse (about 3 s)    |
  | typing                           | solid, no pulse                       |
  | working after Enter              | faster pulse                          |
  | something waits for your verdict | orange, solid                         |
  | error or blocked                 | red                                   |

  Typing stills the dot: nothing runs until Enter, and the still dot shows
  that. When several states apply, the strongest wins: error, then verdict,
  then working, then typing, then idle. Ink is the text colour; orange and
  red are theme tokens, never colours written into the stylesheet. With
  reduced motion set in the OS, the dot does not pulse; colour still carries
  the state. Clicking an orange dot opens the review queue; clicking a red
  dot shows what failed or is blocked. Voice states (listening,
  transcribing) are described under Voice input.
- Typing a project name, a file name or "continue" in the line reopens work.
- The line needs a project. If none is active, the first answer places the
  work in one or creates it (folder model applies). A created project is a
  new folder in the default workspace, named after the work; the quiet line
  says where ("New project in ~/Documents/iterthink").
- "new project <name>" / "neues Projekt <name>" on the start screen creates
  that project in the default workspace and opens it (rule, no model).
  Without a name, the line asks for one; the next Enter creates it.

## Voice input
Voice is another way to type, not another mode. Same core rule: speech becomes
text in the line (or document, or chat); nothing happens until Enter.

- Trigger: hold the dot, or hold a configurable key, to speak; release to
  stop. Default key: Mod+Shift+Space. Never Ctrl+Space: it switches input
  sources on macOS and IBus on Linux. The dot shows state: listening,
  transcribing. Hands-free toggle optional.
- Speech-to-text runs locally by default: faster-whisper (CTranslate2) in
  `ai/local_stt.py`, model downloaded on first use into the machine app directory like the
  embedding model. Model size selectable in Settings (small default).
- Audio capture in Python (`sounddevice`) in `services/dictation.py`, not in
  the WebView, so behaviour is identical on WebView2, WebKit and WebKitGTK.
  macOS: add the microphone usage description and entitlement to packaging.
- Partial transcripts stream into the active input via SSE; the user can edit
  the text before pressing Enter.
- By mode:
  - line: transcript fills the line; Enter hands over as usual
  - document: dictation inserts at the cursor; Mod+Enter invites the AI
  - chat: transcript fills the input; Enter sends
  - app: transcript fills the focused field
- Languages: German, English, French, Italian; language auto-detected or
  fixed in Settings. Swiss German is transcribed to Standard German; test with
  real project dictation before promising more.
- Privacy: audio is never stored and never leaves the machine by default.
  A cloud STT tier is opt-in per workspace with an explicit warning, since the
  privacy shield cannot redact audio. Only the transcript is processed further,
  and it passes the privacy shield like typed text.
- Audit: input source (typed / voice) is recorded with the AI action it led to.
  No audio, no confidence scores in the log.

## Everything is a file
- Documents: `.md` in the project.
- Chats: `.md` in `<project>/.iterthink/chats/`, one file per conversation, versioned
  like any document. A chat can be turned into a document and back.
- Ad-hoc app outputs (tables, schedules): CSV / MD / JSON files in the project.
- Every transformation (chat → document, app → table file) is a new version.
  Nothing is lost; a misread mode costs one step.
