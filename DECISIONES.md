---
tipo: decisiones
area: internos
proyecto: crm
actualizado: 2026-10-07
---

# Decisiones tomadas sin preguntar

Cada entrada: **decisión**, motivo y alternativa descartada. Las marcadas con ⭐ son las que más probablemente quieras revisar.

## Entorno

1. ⭐ **Commits con `dulwich` en lugar de `git`.** En el PC no hay `git` en el PATH de PowerShell (ni en las rutas habituales), y Claude Code ejecuta los comandos en PowerShell, no en Git Bash. Se usa `dulwich` (implementación de git en Python puro, vía `uv run --with dulwich`) desde un script fuera del proyecto. El repositorio `.git` es estándar: `git log` funcionará en cuanto tengas git. Autor de los commits: `Claude Code (sesion nocturna) <claude-code@localhost>` para no publicar tu correo; si prefieres tu nombre, se reescribe antes del primer push.
   *Descartado:* trabajar sin commits (se perdía la red de seguridad para volver atrás).
2. **Python 3.12 descargado con `uv python install 3.12`.** No había Python en el sistema. `uv` lo guarda en su carpeta de usuario; no es una instalación del sistema.
3. **Versiones instaladas más nuevas de lo esperado** (Starlette 1.7, FastAPI 0.142, SQLAlchemy 2.1). Se revisaron en el código instalado las APIs usadas (`TemplateResponse(request, name, ...)`, `SessionMiddleware`). El aviso `StarletteDeprecationWarning` sobre `httpx` en los tests es solo eso, un aviso: el cliente de pruebas funciona.

## Datos

4. **Autor (`created_by`/`updated_by`) como texto, no como clave foránea a `users`.** Permite autores que no son usuarios (`mcp`, `demo`, `importacion`) sin trucos.
   *Descartado:* FK a `users` + usuario ficticio "mcp".
5. **El catálogo de servicios se carga al arrancar la web (o la demo) si la tabla está vacía**, desde `services/catalog.py`. Una sola fuente de verdad en Python.
   *Descartado:* meterlo como datos en la migración (habría dos copias de la lista).
6. **IVA como porcentaje entero** (21, 10, 4, 0). El total se calcula al registrar la factura con redondeo al céntimo mitad hacia arriba, en aritmética entera.
7. **"Servicio de interés" es una referencia al catálogo** (desplegable), no texto libre.
8. **Interacción.fecha se llama `occurred_on` en el código** para no pisar el tipo `date` de Python dentro del modelo.

## Reglas de negocio

9. ⭐ **Cambio de fase:** se puede ir a cualquier fase de 1 a 5 y a `7-Perdido` desde cualquier fase. **No** se puede ir a `0-Lead` (solo importación) ni a `6-Ganado` (solo con "Convertir en cliente", que crea el contrato). Un cliente con contratos activos no puede cambiar de fase hasta cancelarlos.
   *Descartado:* forzar un orden estricto 1→2→3… (en la vida real se saltan fases).
10. **Contrato activo** = estado `activo`, fecha de inicio ≤ hoy y (sin fecha de fin o fin ≥ hoy). El día de fin cuenta como activo.
11. **Factura:** `cobrada` si tiene fecha de cobro; `vencida` si no y el vencimiento es anterior a hoy; `pendiente` en el resto. El día del vencimiento todavía es `pendiente`.
12. ⭐ **Dashboard de clientes:** "facturado" (mes/año) suma **bases imponibles** (sin IVA: el IVA no es ingreso). "Pendiente" y "vencido" suman **totales con IVA** (es lo que te deben). "Pendiente" excluye lo vencido; se muestran por separado.
13. **"Seguimientos"** del dashboard: empresas no perdidas con próximo paso fechado; vencidos = fecha < hoy; próximos = hoy … hoy+7. Incluye clientes (también se les hace seguimiento).
14. **"Interacciones de la semana"** = desde el lunes de esta semana hasta hoy.
15. **Duplicados por nombre normalizado:** sin tildes, minúsculas, signos convertidos en espacios, espacios simples. "Bodega S.L." y "Bodega SL" **no** se consideran iguales.

## Web

16. **CSRF con token en la sesión** (campo oculto en formularios + cabecera `X-CSRF-Token` que HTMX envía en todas sus peticiones vía `hx-headers` en `<body>`).
   *Descartado:* solo comprobar `Origin` (más frágil con proxies y algunos navegadores).
17. **`hx-boost` en todo el `<body>`**: enlaces y formularios normales se cargan por HTMX sin recargar la página. Tras un POST, la app responde con `HX-Location` (navega sin recarga) o, al entrar/salir, `HX-Redirect` (recarga completa, porque cambia el token CSRF).
18. **Filtros de la tabla en vivo con HTMX**: si la petición trae `HX-Target: company-table`, se devuelve solo la tabla.
19. **Cada función de escritura de `services` hace su propio `commit`.** Más simple para web, CLI y MCP. *Descartado:* commit en la dependencia de FastAPI (el orden de ejecución tras `yield` ha cambiado entre versiones de FastAPI).
20. **Sesión de 14 días**; al entrar se limpia la sesión (evita fijación de sesión). `CRM_SECURE_COOKIES=true` activa la cookie `Secure` para cuando haya HTTPS.
