```
id: C16
status: done
depends_on: [C3, C15]
```
# C16 · Dictation

**Goal:** speak instead of typing, in the line, documents, chats and apps,
processed locally; it behaves exactly like typing.

**Spec sections:** The line → Voice input (full); Repository layout
(`services/dictation.py`, `ai/local_stt.py`); article §5.

## Scope
- `iterthink/ai/local_stt.py`, `iterthink/services/dictation.py`
- `iterthink/web/routes/dictation.py`, `static/js/it-dictation.js`
- `tests/v2/services/test_dictation.py`, `tests/v2/fixtures/audio/` (short WAVs)
- `scripts/strict_paths.d/C16.txt`

## Out of scope
- A cloud speech-to-text tier (spec: opt-in per workspace; not in this slice).
- Packaging the macOS microphone entitlement (C18).

## Decided for you
- faster-whisper (`voice` extra), model downloaded on first use into the
  machine state dir; size from settings (`dictation.model`, default `small`).
- Audio capture in Python with `sounddevice` in `services/dictation.py`, not
  in the WebView. The page only sends start / stop.
- Trigger: hold the dot, or hold Mod+Shift+Space (configurable in settings);
  release to stop. Never Ctrl+Space. Optional hands-free toggle. The dot shows
  listening, then transcribing.
- Partial transcripts stream into the focused input over SSE. Dictation never
  presses Enter; by mode it fills the line, inserts at the cursor in a
  document, fills the chat input, or fills the focused app field.
- Languages: auto-detect, or fixed in settings (de, en, fr, it). Swiss German
  is transcribed to Standard German; report quality honestly in the run
  report with the fixture results.
- Audio is never stored and never leaves the machine. The input source
  (`voice`) is recorded with the AI action it leads to; no audio and no
  confidence scores in the log.
- Tests use a fake capture device that plays the fixture WAVs; tests needing
  the model skip only if the `voice` extra is missing locally, and fail in CI.

## Acceptance
- [x] `test_transcribes_fixture_standard_german`
- [x] `test_transcript_streams_into_field_without_enter`
- [x] `test_capture_runs_in_python_not_webview`
- [x] `test_default_key_is_mod_shift_space_and_configurable`
- [x] `test_no_network_during_dictation`
- [x] `test_audio_not_written_to_disk`
- [x] `test_voice_source_recorded_on_following_ai_action`
