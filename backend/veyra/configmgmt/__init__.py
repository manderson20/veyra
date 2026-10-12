"""Configuration management: the database is authoritative for Veyra-managed
engine configuration. HTTP handlers create *draft* revisions only; a separate,
privileged deployer service validates, writes and reloads engine
configuration. See docs/ARCHITECTURE.md §Configuration management.
"""
