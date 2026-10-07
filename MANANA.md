---
tipo: estado
area: internos
proyecto: crm
actualizado: 2026-10-07
---

# Para mañana

> La sesión se cortó por **límite de uso**: no dio tiempo al nivel 3, a la revisión del nivel 2 ni a `/cierre-sesion`.

## 1. Qué funciona

**Nivel 1** ✅ (tests en verde, revisado por `tester` y `revisor-codigo`, críticos e importantes corregidos)
- ✅ Modelo completo y migración `0001`; login y logout, rutas protegidas y CSRF.
- ✅ `crm demo` con 25 empresas inventadas, 4 clientes, contratos y facturas (una vencida).
- ✅ Dashboard con las pestañas Potenciales y Clientes; tabla con filtros HTMX y búsqueda sin tildes; ficha y formularios.

**Nivel 2** ⚠️ (hecho y con tests, `pytest` en verde, pero **sin la revisión de los subagentes y sin verlo en el navegador**)
- ✅ Convertir en cliente, contratos y bajas, registro de facturas y cobros, página `/facturas`, catálogo editable en `/servicios`.
- ✅ Kanban con botones ← → / Ganar / ✕.
- ⚠️ Gráficos con Chart.js: un embudo, el MRR y lo facturado por mes. No los he visto renderizados.
- ⚠️ Adaptación a 390 px: el diseño la tiene en cuenta, pero no está comprobada en pantalla.

**Nivel 3** ❌ Falta el MCP, `crm importar`, `crm exportar-obsidian` y el arrastrar y soltar.

## 2. Cómo verlo (PowerShell)

`uv` está en `%USERPROFILE%\.local\bin`, que no está en el PATH de PowerShell. En la misma sesión de PowerShell, antes de los comandos:

```powershell
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
uv sync; uv run alembic upgrade head
uv run crm crear-usuario raul; uv run crm demo
uv run crm serve   # http://127.0.0.1:8000
```

Pon `SECRET_KEY` en `.env`: si no está, la sesión se pierde cada vez que reinicias el servidor.

## 3. Qué revisar primero

1. `src/crm/services/clients.py`: `contract_is_active` y MRR. El estado del contrato lo deciden solo las fechas.
2. `src/crm/web/deps.py`: CSRF, `require_user`, `redirect` con HTMX y `safe_path`.
3. `src/crm/services/dashboard.py`: qué suma cada cifra (bases o totales).
4. `src/crm/services/companies.py`: `change_phase`, con las transiciones permitidas.
5. `src/crm/services/money.py`: `parse_euros`.

## 4. Pendiente, por prioridad

1. Revisión del nivel 2 con `revisor-codigo` y `tester`. Abrir la app en el navegador, en escritorio y a 390 px.
2. Nivel 3: el MCP (verifica antes la API del paquete `mcp`), importar CSV y exportar a Obsidian con `--dry-run`.
3. **Git:** no hay `git` instalado. Los commits se hicieron con `dulwich`; el `.git` es estándar. Instala Git y revisa el log.
4. Deuda técnica:
   - Las librerías de CDN no llevan SRI.
   - La sesión vive en la cookie (sin estado) y no hay límite de intentos de login.
   - Falta `mypy` en las dependencias de desarrollo.
   - Avisos `httpx` → `httpx2` en los tests.
5. `docs/GUIA.md`: falta añadir el nivel 2 (kanban, contratos, gráficos).
6. Falta rellenar el registro de horas de `CLAUDE.md`.

## 5. Decisiones que quizá quieras cambiar

Las de `DECISIONES.md` marcadas con ⭐: commits con dulwich, transiciones de fase, y facturado como base frente a pendiente con IVA.

Hay además una decisión nueva que aún no está en `DECISIONES.md`: un contrato cuenta como activo **solo por sus fechas**. "Cancelado" significa que la baja ya está registrada, y sigue sumando al MRR hasta la fecha de fin.

## 6. Avisos

- Nada del nivel 2 se ha visto en un navegador.
- La base de datos real (`data/crm.db`) no existe todavía. Las pruebas usaron una base temporal.
- Puede quedar un servidor de prueba en el puerto 8765. Si sigue abierto, ciérralo: `Stop-Process -Name crm`.
