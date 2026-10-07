"""Punto de entrada de uvicorn: `crm.web.main:app` (con la configuración del entorno)."""

from crm.web.app import create_app

app = create_app()
