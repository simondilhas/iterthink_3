# App builder

## 1. Rules

One self-contained HTML file, plus an optional module. No network. Calls go
through the bridge only. Writes go only through propose, and only for CSV,
Markdown and JSON. Use an existing block before writing new logic. The words
on screen are plain. Colours come from CSS custom properties.

## 2. Bridge reference

The function list below is generated from the bridge. Do not invent names.

## 3. Component reference

The elements below are generated from the component registry.

## 4. Example apps

Spec check compares two texts. CSV cleanup reads a table and proposes a
cleaned file. A door schedule and a fire-rating audit wait until the model
block exists.
