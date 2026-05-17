#!/usr/bin/env python3
"""Shared helpers for schema validators."""


def budget_error(path: str, actual: int, max_len: int) -> str:
    return f"{path} exceeds budget ({actual} > {max_len} chars)"
