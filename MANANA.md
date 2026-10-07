---
tipo: estado
area: internos
proyecto: crm
actualizado: 2026-10-07
---

# Para mañana

Sesión nocturna terminada: **niveles 1, 2 y 3 hechos**, salvo el arrastrar y soltar del kanban, que probé y retiré. Cada nivel pasó por el `tester` y el `revisor-codigo`; se corrigió todo lo crítico (no hubo) y lo importante. Hay 236 tests en verde y `ruff` y `mypy` están limpios.

## 1. Qué funciona

**Nivel 1**
- ✅ Modelo completo (§3) y migración `0001` (con un test que comprueba que coincide con los modelos).
- ✅ Login y logout, rutas protegidas, CSRF, cookie `HttpOnly`/`SameSite=Lax`, contraseñas argon2.
- ✅ `crm demo`: 25 empresas inventadas, 4 clientes con contratos y facturas (una vencida).
- ✅ Dashboard con las pestañas Potenciales y Clientes y todas sus cifras.
- ✅ Tabla de empresas con filtros en vivo (HTMX) y búsqueda sin tildes; ficha con contactos, notas e historial; formularios.

**Nivel 2**
- ✅ Convertir en cliente, contratos y bajas, registro de facturas y cobros, página `/facturas`, catálogo editable en `/servicios`.
- ✅ Kanban con botones ← → / Ganar / ✕.
- ✅ Gráficos: embudo, MRR por mes y facturado por mes (vistos en Chrome).
- ⚠️ Móvil a 390 px: el diseño lo contempla (menú inferior, tablas con scroll propio), pero **no lo he podido ver**: Chrome no cambió el tamaño de la ventana.

**Nivel 3**
- ✅ Servidor MCP (`crm-mcp`) con las 9 herramientas de la §6 y `.mcp.json`. Probado en proceso y por stdio real con JSON-RPC.
- ⚠️ El MCP **no está probado desde Claude Code real**.
- ✅ `crm importar archivo.csv [--dry-run] [--columna campo=Cabecera]`.
- ✅ `crm exportar-obsidian [--dry-run]`, probado solo con bóvedas temporales.
- ❌ Arrastrar y soltar en el kanban: SortableJS congelaba Chrome. Retirado (DECISIONES 27).

## 2. Cómo verlo (PowerShell, en esta carpeta)

```powershell
# uv y git no están en el PATH de PowerShell (git es MinGit portátil en ~/.local/mingit)
$env:PATH = "$env:USERPROFILE\.local\mingit\cmd;$env:USERPROFILE\.local\bin;$env:PATH"
uv sync; uv run alembic upgrade head; uv run crm crear-usuario raul
uv run crm demo; uv run crm serve                      # http://127.0.0.1:8000
```

**Estado al terminar la sesión de mañana:** `data/crm.db` ya existe con la migración y la demo, y el servidor quedó arrancado en segundo plano. Solo falta `crear-usuario`, que pide tu contraseña.

Crea `.env` a partir de `.env.example` y pon una `SECRET_KEY`. Sin ella, la sesión se pierde cada vez que reinicias el servidor.

Para pasar a datos reales después de mirar la demo: borra `data/crm.db` (solo contiene la demo), vuelve a ejecutar `alembic upgrade head` y crea el usuario. No uses `crm demo` sobre la base real.

## 3. Qué revisar primero

1. `src/crm/services/clients.py`: `contract_is_active`, el MRR y los estados de factura. Es la lógica de dinero.
2. `src/crm/web/deps.py`: login obligatorio, CSRF, `redirect` con HTMX y `safe_path`.
3. `src/crm/services/companies.py`: `change_phase`, con las transiciones permitidas (DECISIONES 9 y 22).
4. `src/crm/mcp_server.py`: qué puede hacer Claude y qué datos ve (DECISIONES 30, privacidad).
5. `src/crm/services/export_obsidian.py`: lo único que escribe en tu bóveda.

## 4. Pendiente y deuda técnica (por prioridad)

1. **Git:** ya está, como MinGit 2.56 portátil en `%USERPROFILE%\.local\mingit` (descargado de la release oficial de Git for Windows, con el SHA-256 verificado). `git fsck` está limpio. Antes del primer push: configura tu identidad (`git config user.name` / `user.email`, ahora vacías) y revisa `git log`. El autor de los commits es `Claude Code (sesion nocturna)`; si quieres que figures tú, reescríbelo antes de publicar. Si prefieres el instalador completo de Git for Windows, puedes borrar esa carpeta.
2. **Probar el MCP en Claude Code**: abre Claude Code en esta carpeta, acepta el servidor `crm` y pregunta "¿qué seguimientos tengo vencidos?". Si no arranca, el problema es que `uv` no está en el PATH (DECISIONES 29).
3. Ver la web en el móvil (390 px).
4. Arrastrar y soltar: retomarlo con Tailwind compilado en lugar del CDN (DECISIONES 27).
5. Deuda técnica:
   - Tailwind, HTMX y Chart.js por CDN, sin SRI. Antes de desplegar, servirlos en local.
   - La sesión vive en la cookie y no hay límite de intentos de login. Aceptable en `127.0.0.1`; no en un servidor.
   - La regla de "contrato vigente" está en dos sitios (DECISIONES 22).
   - `services` importa el formato de `crm.web.formatting` (DECISIONES 24).
   - La exportación no detecta que edites la nota en Obsidian justo en el mismo segundo.
   - Aviso `httpx` → `httpx2` en los tests (Starlette 1.x).

## 5. Decisiones que quizá quieras cambiar

Las tienes todas en `DECISIONES.md`, marcadas con ⭐:

- **9:** a qué fases se puede mover una empresa.
- **10:** un contrato es activo solo por sus fechas; "cancelado" significa baja registrada.
- **12:** "facturado" suma bases sin IVA; "pendiente" y "vencido" suman con IVA.
- **26:** el dashboard se carga sin HTMX.
- **27:** sin arrastrar y soltar.
- **30:** el MCP envía teléfonos y emails de los contactos a Claude.

## 6. Avisos

- **No verificado:**
  - El MCP desde Claude Code real.
  - La vista móvil.
  - Las confirmaciones con `hx-confirm` (baja de contrato y marcar como perdida) en el navegador.
- He descargado Python 3.12 con `uv` (en la carpeta de usuario de `uv`, no es una instalación del sistema).
- La bóveda real no se ha tocado en ningún momento.
- La base de datos real `data/crm.db` no existe todavía: todas las pruebas usaron bases temporales.
