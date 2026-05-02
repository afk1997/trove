"""Flask blueprints. Each blueprint owns one cohesive route group and
is registered from ``app.create_app``. Blueprints reach shared state
(JobManager, TranscribeJobManager, per-transcript locks) via
``current_app.extensions[...]`` keys set up in ``create_app``:

    trove.jobs        → JobManager
    trove.transcribe  → TranscribeJobManager
    trove.txn_locks   → dict[str, Lock] keyed by transcript base path
    trove.txn_locks_guard → Lock guarding the dict above

Splitting these routes out of app.py is purely an audit-ability win:
the prior 1100-line ``create_app`` closure made it too easy to lose
sight of which routes had auth decorators and which didn't (which is
exactly how the unauthenticated transcript-export bug shipped).
"""
