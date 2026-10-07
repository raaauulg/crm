"""Lógica de negocio. La web, el MCP y la CLI solo hablan con este paquete.

Cada función de escritura es una transacción completa: valida, escribe y hace commit.
"""
