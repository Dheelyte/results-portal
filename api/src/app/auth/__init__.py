"""Authentication primitives: hashing, tokens, and the current-user dependency.

Pure mechanism. The *rules* that use these — lockout, rotation, reuse
detection — live in `services/auth.py` (CLAUDE.md rule 2).
"""
