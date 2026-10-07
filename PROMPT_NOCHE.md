# Encargo de esta noche: construir el CRM sin supervisión

Raúl se va a dormir. Cuando se despierte quiere **una aplicación que funcione y que pueda abrir en el navegador**. Nadie va a contestar preguntas hasta mañana. Este documento te dice hasta dónde llegar, cómo trabajar sin preguntar y qué dejar preparado.

**Antes de nada, lee `CLAUDE.md` de este proyecto entero.** Es la especificación: modelo de datos, pantallas, arquitectura y reglas. Este prompt no la repite; solo fija el objetivo de la noche y la forma de trabajar.

---

## 1. Hasta dónde queremos llegar

El trabajo se ordena en tres niveles. **No empieces un nivel sin haber cerrado el anterior** (tests en verde y commit). Si se acaba el tiempo o el contexto, mejor un nivel 1 impecable que tres niveles a medias.

### Nivel 1: lo mínimo para que mañana haya algo tangible (obligatorio)
- Proyecto con `uv`, FastAPI, SQLAlchemy 2.0, Alembic, Jinja2, HTMX, Tailwind y Chart.js (estos tres últimos por CDN), Typer, pytest y ruff.
- Modelo de datos completo de la §3 con su primera migración, aunque algunas pantallas lleguen después.
- `crm crear-usuario`, login y logout, y todas las rutas protegidas.
- `crm demo` con los datos inventados de la §5 (incluidos clientes, contratos y facturas).
- **Dashboard con las pestañas Potenciales y Clientes y sus cifras** (sin gráficos todavía): nº por fase, € en juego, seguimientos vencidos y próximos, MRR, facturado, pendiente y vencido.
- Tabla de empresas con filtros. Ficha de empresa con contactos, notas e historial.
- Formularios: crear y editar empresa, registrar interacción, cambiar fase, fijar próximo paso.
- Tests de `services` (fases, MRR, estados de factura) y de humo de las rutas principales.
- `README.md` actualizado con cómo arrancarlo.

### Nivel 2: el CRM completo para usarlo a diario
- "Convertir en cliente", alta de contrato, registro de facturas y cobros, y catálogo de servicios editable.
- Kanban de potenciales, con cambio de fase por botón.
- Gráficos: embudo por fase; MRR e ingresos por mes.
- Pulido visual y adaptación al móvil (390 px).

### Nivel 3: integraciones
- Servidor MCP (stdio) con las herramientas de la §6 y su `.mcp.json` en la raíz del proyecto. Comprueba antes, en la documentación oficial, la API del paquete `mcp` y el formato de `.mcp.json`.
- `crm importar` (CSV; Excel solo si sale fácil) con `--dry-run`.
- `crm exportar-obsidian` con `--dry-run`, probado **solo con una bóveda temporal**.
- Arrastrar y soltar en el kanban, si sobra tiempo.

**Fuera de esta noche:** todo lo de la §9 de `CLAUDE.md`.

## 2. Cómo trabajar sin supervisión

1. **No hagas preguntas.** Ante cualquier duda, elige la opción más simple que cumpla `CLAUDE.md` y apúntala en `DECISIONES.md` (decisión, motivo, alternativa descartada). Raúl lo revisará por la mañana.
2. **No pares hasta acabar el nivel 3 o quedarte sin opciones.** Cuando termines una parte, pasa a la siguiente sin esperar confirmación. Usa una lista de tareas para no perder el hilo.
3. **La aplicación siempre tiene que arrancar.** Después de cada bloque: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .` y **un commit**. Si algo se rompe y no lo arreglas en un intento razonable, vuelve al último commit bueno (`git restore` o `git checkout -- <archivo>`) y sigue por otro camino. Apúntalo en `DECISIONES.md`.
4. **Permisos:** estás en un modo en el que lo que no está permitido se deniega sin preguntar. Si un comando se deniega, **no insistas**: busca la alternativa con las herramientas permitidas (`uv`, `python`, `git` local, edición de archivos del proyecto). Nunca intentes `git push`, leer `.env` ni tocar archivos fuera de esta carpeta.
5. **Nada fuera de `internos/crm/`.** La bóveda de Obsidian está en la carpeta de arriba: **no la leas ni la escribas**. Para la exportación usa siempre una bóveda temporal en los tests.
6. **Dependencias:** solo librerías conocidas y mantenidas, con versión mínima en `pyproject.toml`. Si dudas de una API, consúltala en la documentación oficial (WebFetch) antes de escribir código. **No inventes APIs.**
7. **Entorno:** Windows con el ordenador de Raúl; los comandos pasan por Git Bash. Usa rutas relativas y `pathlib`. Si `uv` no estuviera instalado, apúntalo en `MANANA.md` como primer paso para Raúl y no intentes instalar software del sistema.
8. **Subagentes:**
   - Al cerrar **cada nivel**, pide al subagente `tester` que revise y complete los tests de lo nuevo.
   - Después, pide al subagente `revisor-codigo` una revisión.
   - Corrige todo lo **crítico** y lo **importante**; lo menor va a `MANANA.md`.
9. **Modo tutor:** al cerrar cada nivel, actualiza `docs/GUIA.md` (ver §8.6 de `CLAUDE.md`). Escribe para alguien con buena base técnica que no conoce aún HTMX, Alembic ni MCP.

## 3. Lo que tiene que estar listo por la mañana

Al terminar, o si ves que no puedes seguir, ejecuta la skill `/cierre-sesion` y asegúrate de que existe **`MANANA.md`** en la raíz del proyecto con:

1. **Qué funciona**, por niveles, marcado ✅ / ⚠️ / ❌.
2. **Cómo verlo en 3 comandos** (instalar, crear usuario, cargar la demo y arrancar), en el orden exacto, para PowerShell o Git Bash.
3. **Qué revisar primero:** los 5 puntos donde más le conviene a Raúl mirar el código.
4. **Pendiente y deuda técnica**, por prioridad.
5. **Resumen de `DECISIONES.md`:** las decisiones que quizá quiera cambiar.
6. **Avisos:** cualquier cosa que no hayas podido verificar (por ejemplo, el MCP sin probar con Claude real, dependencias no instaladas).

Último paso: commit final con el mensaje `Sesión nocturna: <resumen>`.
