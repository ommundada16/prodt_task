"""Configuration values, read from environment variables with sensible local defaults."""

import os

ATLAS_API_BASE_URL = os.getenv("ATLAS_API_BASE_URL", "http://localhost:9001")
NOVA_API_BASE_URL = os.getenv("NOVA_API_BASE_URL", "http://localhost:9002")
