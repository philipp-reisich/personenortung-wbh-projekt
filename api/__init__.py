# path: personenortung-wbh-projekt/api/__init__.py
"""FastAPI application for the RTLS prototype.

This package contains the REST and WebSocket endpoints, configuration,
database models and helper utilities. The application is started via
`main.py` when running in a Docker container or local development.
"""

__all__ = ["create_app"]
