"""Ira — Machinecraft AI Pantheon."""

from __future__ import annotations

import warnings

# Suppress requests' urllib3/chardet version warning (transitive deps; requests 2.32.x works)
warnings.filterwarnings("ignore", message=".*doesn't match a supported version.*")
