"""One module per area, each exposing `router`. Mounted automatically by app.py.

Ownership (one slice per module, so parallel runs don't collide):
- home.py, projects.py, files.py, search.py  → slice A1
- history.py, review.py, log.py             → slice A5
- line.py                                   → slice C3
- chats.py → C5 · apps.py → C6 · tasks.py → C8 · models.py → C9 · settings.py → C15
- dictation.py → C16
"""
