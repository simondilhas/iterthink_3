"""Core services. Import submodules explicitly.

Eager imports here pull NumPy (and the rest of the 1.x stack) while
coverage resolves ``--cov=iterthink.services.*``. Coverage then restores
``sys.modules`` and the extension cannot load a second time.
"""
