---
tipo: guia
area: internos
proyecto: crm
actualizado: 2026-10-07
---

# Guía del CRM (modo tutor)

Para alguien con buena base técnica que todavía no conoce HTMX, Alembic ni MCP. Léela con el código abierto al lado.

## 1. Arquitectura en un diagrama

```
                ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
                │  Navegador   │   │ Claude (MCP) │   │   Terminal   │
                │ HTML + HTMX  │   │    stdio     │   │  crm <cmd>   │
                └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
                       │ HTTP             │ JSON-RPC         │
                ┌──────▼───────┐   ┌──────▼───────┐   ┌──────▼───────┐
                │ crm.web      │   │ crm.mcp_...  │   │ crm.cli      │
                │ rutas+plant. │   │ herramientas │   │ Typer        │
                └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
                       └─────────┬────────┴──────────────────┘
                          ┌──────▼───────┐
                          │ crm.services │  ← TODA la lógica de negocio
                          └──────┬───────┘
                          ┌──────▼───────┐
                          │ crm.models   │  SQLAlchemy 2.0
                          └──────┬───────┘
                          ┌──────▼───────┐
                          │ SQLite       │  data/crm.db  (migraciones: Alembic)
                          └──────────────┘
```

**La regla de oro:** web, MCP y CLI nunca hacen consultas por su cuenta; llaman a funciones de `crm/services/`. Si mañana cambias cómo se calcula el MRR, lo cambias en un sitio y lo ven las tres puertas de entrada. Los tests se centran en `services` por eso mismo.

Mapa de archivos:

| Archivo | Qué hay |
|---|---|
| `src/crm/config.py` | Configuración desde variables de entorno / `.env` (pydantic-settings). |
| `src/crm/db.py` | Motor de SQLite, fábrica de sesiones, `PRAGMA foreign_keys=ON`. |
| `src/crm/models.py` | Tablas: empresas, contactos, interacciones, servicios, contratos, facturas, usuarios. |
| `src/crm/services/companies.py` | Empresas, fases, próximo paso, contactos, interacciones, búsqueda. |
| `src/crm/services/clients.py` | Conversión a cliente, contratos, MRR, facturas, cobros. |
| `src/crm/services/dashboard.py` | Cifras de las dos pestañas del inicio. |
| `src/crm/services/money.py` | Céntimos, IVA y lectura de importes escritos a mano. |
| `src/crm/services/clock.py` | "Qué día es hoy" en Europe/Madrid. |
| `src/crm/web/deps.py` | Login obligatorio, CSRF, sesión de BD, `render` y `redirect`. |
| `src/crm/web/routes/*.py` | Rutas por pantalla. |
| `src/crm/web/templates/` | Plantillas Jinja2 (HTML + clases de Tailwind + atributos HTMX). |
| `migrations/` | Migraciones de Alembic. |

## 2. Cómo viaja una petición

Ejemplo: en la ficha de una empresa pulsas **Cambiar** fase.

1. **Navegador.** El `<body>` tiene `hx-boost="true"`, así que HTMX intercepta el envío del formulario y lo manda por AJAX (`POST /empresas/12/fase`). Añade la cabecera `HX-Request: true` y, por el `hx-headers` del `<body>`, `X-CSRF-Token`.
2. **Middleware de sesión** (`SessionMiddleware` de Starlette). Lee la cookie `crm_session`, comprueba su firma con `SECRET_KEY` y deja el diccionario en `request.session`.
3. **Dependencias del router** (`routes/companies.py`, línea del `APIRouter`):
   - `require_user`: si no hay `user_id` en la sesión, lanza `LoginRequired` → la app redirige a `/login`.
   - `csrf_protect`: en POST compara el token enviado con el de la sesión.
4. **Ruta** `change_phase`: lee el formulario y llama a `companies.change_phase(session, id, fase, autor)`.
5. **Servicio**: valida (fase conocida, no `6-Ganado`, no la misma…), cambia el campo, apunta `updated_by` y hace `commit`. Si algo no cuadra lanza `ServiceError` con un mensaje para el usuario.
6. **Respuesta**: la ruta guarda un mensaje "flash" en la sesión y devuelve `redirect(...)`. Como la petición vino de HTMX, en vez de un 303 devuelve la cabecera `HX-Location: /empresas/12`; HTMX pide esa página y sustituye el `<body>` sin recargar.
7. **Plantilla**: `render()` añade al contexto el usuario, el token CSRF y los mensajes flash; Jinja2 genera el HTML **con autoescape** (lo que escribas en una nota no se ejecuta como HTML).

Sin JavaScript (o con HTMX caído) todo sigue funcionando: los formularios son formularios normales y la ruta responde con un 303 clásico.

## 3. Conceptos nuevos

### HTMX

Una librería de ~14 kB que añade atributos al HTML para pedir fragmentos al servidor y colocarlos en la página. Aquí se usan tres ideas:

- `hx-boost="true"` en `<body>`: convierte enlaces y formularios en peticiones AJAX que reemplazan el `<body>`. La sensación es de aplicación de una sola página sin escribir JS.
- **Filtros en vivo** (`companies/list.html`): el formulario de filtros tiene `hx-get="/empresas" hx-target="#company-table" hx-trigger="change, input changed delay:300ms ..."`. Al teclear o cambiar un desplegable, HTMX pide `/empresas?...` con la cabecera `HX-Target: company-table`, y la ruta devuelve **solo** `_table.html`. `hx-push-url` actualiza la URL para que puedas copiarla.
- **Cabeceras de respuesta**: `HX-Location` (navega sin recargar) y `HX-Redirect` (recarga completa). Se usa la segunda al entrar y salir porque cambia el token CSRF de la página.

### Migraciones con Alembic

La base de datos tiene un esquema (tablas y columnas) que evoluciona. Alembic guarda cada cambio como un archivo Python en `migrations/versions/` con `upgrade()` y `downgrade()`, y apunta en la tabla `alembic_version` cuál es el último aplicado.

- `uv run alembic upgrade head`: aplica lo que falte.
- Cuando cambies `models.py`: `uv run alembic revision --autogenerate -m "qué cambia"`, **lee** el archivo generado y luego `upgrade head`.
- `render_as_batch=True` (en `migrations/env.py`): SQLite no sabe modificar columnas; Alembic recrea la tabla por debajo.
- El test `tests/test_migrations.py` aplica las migraciones en una BD temporal y comprueba que coinciden con los modelos: si cambias un modelo y olvidas la migración, falla.

### Sesiones, cookies y CSRF

- **Sesión**: un diccionario (`user_id`, token CSRF, mensajes flash) guardado **dentro de la cookie**, firmado con `SECRET_KEY` (itsdangerous). El navegador no puede modificarlo sin romper la firma, pero sí puede leerlo (está en base64): por eso no se mete nada secreto.
- **`HttpOnly`**: el JavaScript de la página no puede leer la cookie. **`SameSite=Lax`**: el navegador no la envía en POST que vengan de otras webs.
- **CSRF**: aun así, cada formulario lleva un token aleatorio que también está en la sesión. Una web maliciosa no puede conocerlo, así que no puede hacerte enviar formularios.
- **Contraseñas**: hash argon2 (`argon2-cffi`). Ni siquiera con la base de datos se pueden leer.

## 4. Dónde suele fallar cada parte

| Parte | Síntoma | Causa típica / qué mirar |
|---|---|---|
| Arranque | `RuntimeError: La base de datos no está creada…` | Falta `uv run alembic upgrade head`, o `CRM_DB_PATH` apunta a otro sitio. |
| Login | Te echa al reiniciar el servidor | `SECRET_KEY` no está en `.env`: se genera una nueva en cada arranque (lo avisa el log). |
| Formularios | "Formulario caducado o no válido (CSRF)" | Página abierta desde antes de reiniciar sin `SECRET_KEY`, o plantilla nueva sin `<input name="csrf_token">`. Recarga la página. |
| HTMX | Un botón "no hace nada" | La respuesta fue 4xx/5xx: HTMX no las pinta. Mira la pestaña Red del navegador y el log del servidor. Las rutas devuelven 200 con el error en la página a propósito. |
| Fechas | Un seguimiento sale vencido un día antes/después | Todo usa `services/clock.py` (Europe/Madrid). Si alguien usa `date.today()` directamente, puede desfasarse en un servidor con otra zona. |
| Dinero | Céntimos que bailan | Los importes son `int` en céntimos; `parse_euros` interpreta "1.700" como mil setecientos y "1700.5" como decimal. Nunca `float`. |
| Migraciones | `test_migrations` falla | Cambiaste `models.py` sin generar migración. |
| Plantillas | Error 500 en una ficha | Un campo `None` usado sin comprobar (por ejemplo `.isoformat()` sobre una fecha vacía). Mira la traza en la terminal. |
