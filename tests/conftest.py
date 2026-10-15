"""Prevent tests from reading or writing the user's live demo database."""

import pytest


@pytest.fixture(autouse=True)
def isolated_runtime_database(monkeypatch):
    """Each test application receives its own in-memory SQLite store."""
    monkeypatch.setenv("CASE_DB_PATH", ":memory:")
    monkeypatch.setenv("EVALUATION_DB_PATH", ":memory:")
