---
tipo: guia
area: desarrollo
estado: vigente
actualizado: 2026-10-07
relacionado:
  - "[[internos/README]]"
  - "[[internos/CLAUDE]]"
  - "[[negocio/clientes_potenciales]]"
  - "[[negocio/catalogo_servicios_entrada]]"
tags:
  - instrucciones-claude
  - crm
---

# CLAUDE.md: CRM de la consultoría (internos/crm/)

← [[internos/README|Proyectos internos]] · [[internos/CLAUDE|Reglas de internos]]

> Rigen también `internos/CLAUDE.md` (precedencia y reglas internas) y, a través de él, las reglas técnicas de `desarrollo/CLAUDE.md`. El `CLAUDE.md` de la raíz de la bóveda **no se carga** aquí (excluido en `.claude/settings.local.json`).
> Requisitos aprobados por Raúl el 2026-10-07 en una sesión de ingeniería de requisitos. Si algo de lo que se pide contradice este archivo, avisa antes de cambiarlo.

---

## 1. Qué es y para quién

- **Qué:** una aplicación web para llevar la parte comercial y de clientes de la consultoría: empresas **potenciales** (del lead al cierre) y **clientes** (servicios contratados, cuotas, MRR, facturas y cobros).
- **Usuario:** Raúl (y quizá un socio más adelante). Lo **mira** más que lo consulta: el dashboard tiene que ser **bonito, claro y funcional**, también en el móvil.
- **Volumen esperado:** 50–200 empresas en 6 meses. No hace falta optimizar rendimiento.
- **Portfolio:** repositorio público en GitHub con datos **inventados**. Mensaje: "CRM web local-first para una consultoría de IA: FastAPI + HTMX + MCP".
- **Tope de horas de Raúl para tener la primera versión en uso:** 25 h (contando su revisión). Si se supera, se recorta alcance (orden de recorte en la §7), no se añaden horas.
- **Criterio de corte:** si dos semanas después de tener la primera versión Raúl no lo usa a diario con contactos reales, se congela y el pipeline vuelve a las fichas de Obsidian.

## 2. Decisiones de arquitectura (cerradas)

| Tema | Decisión |
|---|---|
| Tipo de aplicación | Web. **Primero en el PC de Raúl** (`127.0.0.1`); más adelante, servidor en la UE con Docker + Caddy (HTTPS). Diseñar desde el principio para que el despliegue sea trivial (configuración por variables de entorno, sin rutas absolutas). |
| Backend | Python 3.12, **FastAPI**, plantillas **Jinja2**. Gestión con **`uv`**. |
| Frontend | **HTMX** (actualizaciones parciales sin escribir JavaScript propio) + **Tailwind CSS**. Gráficos con **Chart.js**. Sin Node ni paso de compilación en esta versión: Tailwind, HTMX y Chart.js por CDN (anotar como deuda técnica para producción). |
| Base de datos | **SQLite** con **SQLAlchemy 2.0** (estilo tipado) y **Alembic** para migraciones. Importes en **céntimos (enteros)**, nunca `float`. Fechas ISO; zona horaria Europe/Madrid. |
| Fuente de verdad | **La web y su base de datos.** Obsidian **solo recibe** la tabla resumen del pipeline (exportación en un sentido). No hay sincronización bidireccional. |
| Notas largas (dolor, ROI, historial) | En la web, dentro de cada empresa. |
| Usuarios | Login para un usuario hoy; cada registro guarda **quién lo creó o cambió** (`created_by`, `updated_by`) para poder añadir un socio sin rehacer nada. Sin roles todavía. |
| Integración con Claude | **Servidor MCP local** (stdio) registrado en `.mcp.json` del proyecto, que usa la misma capa de servicios que la web. El MCP remoto (para Claude en el móvil) llega con el despliegue. |
| CLI | **Typer**: `crm serve`, `crm crear-usuario`, `crm demo`, `crm importar`, `crm exportar-obsidian`, `crm-mcp`. |

**Capas:** `models` (SQLAlchemy) → `services` (toda la lógica de negocio: cambios de fase, conversión a cliente, MRR, cobros) → `web` (rutas FastAPI + plantillas) / `mcp` / `cli`. **La web, el MCP y la CLI no tocan la base de datos directamente: siempre pasan por `services`.** Así la lógica se prueba una sola vez.

## 3. Modelo de datos

- **Empresa:** nombre (único), sector, municipio, web, teléfono general, origen (cómo llegó: visita, recomendación, FOES, buscador...), **fase**, servicio de interés, valor estimado, cuota estimada, puntuación de dolor (0–100, opcional), notas (dolor, ROI, texto libre), próximo paso y su fecha, autor y fechas.
- **Fases:** `0-Lead`, `1-Identificado`, `2-Contactado`, `3-Reunión`, `4-Diagnóstico`, `5-Propuesta enviada`, `6-Ganado`, `7-Perdido`.
  - **Potenciales** = fases 0–5 y 7. **Clientes** = fase 6.
  - `0-Lead` es solo para empresas que entran por importación o por el futuro buscador sin haberlas revisado.
- **Contacto:** empresa, nombre, cargo, teléfono, email, principal (sí/no), origen del dato, fecha del dato.
- **Interacción:** empresa, fecha, canal (`llamada`, `visita`, `email`, `whatsapp`, `evento`, `otro`), resumen, resultado, autor.
- **Servicio (catálogo):** nombre, precio de implantación de referencia, cuota mensual de referencia, activo. Se carga con los servicios del catálogo (ver §5).
- **Contrato:** empresa cliente, servicio, precio de implantación pactado, cuota mensual pactada, fecha de inicio, permanencia en meses, fecha de fin (opcional), estado.
  - **MRR** = suma de las cuotas de los contratos activos hoy.
- **Factura (solo registro):** número, contrato o empresa, fecha de emisión, base, IVA %, total, vencimiento, fecha de cobro.
  - Estado **calculado**: `cobrada`, `pendiente`, `vencida`.
  - **El CRM no emite facturas** (eso convertiría la app en un programa de facturación sujeto a Verifactu). Se emiten en un programa certificado y aquí solo se registran.
- **Usuario:** nombre de usuario, hash de contraseña (argon2 o bcrypt con una librería mantenida; **nada de criptografía casera**), activo.

## 4. Pantallas y funciones

1. **Login.**
2. **Dashboard (inicio)** con dos pestañas, **Potenciales** y **Clientes**:
   - Potenciales: nº de empresas por fase, € en juego (suma del valor estimado de las fases 1–5), seguimientos vencidos y de los próximos 7 días, interacciones de la semana, gráfico de embudo por fase.
   - Clientes: nº de clientes, **MRR**, ingresos facturados del mes y del año, **pendiente de cobro** y **vencido**, gráfico de MRR e ingresos por mes.
3. **Kanban de potenciales** por fase. El cambio de fase se hace desde la tarjeta; arrastrar y soltar es opcional (ver §7).
4. **Tabla de empresas** con filtros (fase, sector, municipio, texto) y orden por columnas.
5. **Ficha de empresa:** datos, contactos, notas, historial de interacciones (lo más reciente arriba), próximo paso, botón **"Convertir en cliente"** (pasa a `6-Ganado` y abre el alta de contrato). En clientes: contratos, cuota, facturas y su estado.
6. **Formularios:** crear y editar empresa y contacto, registrar interacción, cambiar fase, fijar próximo paso, alta de contrato, registro de factura y de su cobro.
7. **Catálogo de servicios** editable.

**Diseño:** limpio y moderno; barra lateral en escritorio y menú inferior o desplegable en móvil; tarjetas de cifras arriba; paleta sobria con un color de acento; formato español (`1.700,00 €`, `07/10/2026`); interfaz en **español**. Debe verse bien en un móvil de 390 px de ancho.

## 5. Datos de referencia y demo

- **Servicios del catálogo** (de `negocio/catalogo_servicios_entrada.md`), con implantación / cuota mensual de referencia:

  | Servicio | Implantación | Cuota/mes |
  |---|---|---|
  | Albaranes y facturas sin teclear | 1.700 € | 120 € |
  | Pedidos sin teclear | 2.000 € | 120 € |
  | Presupuestos en 5 minutos | 2.200 € | 90 € |
  | Parte del lunes | 2.400 € | 120 € |
  | Recepcionista virtual | 2.500 € | 200 € |
  | Web sencilla | 690 € | 25 € |
  | Taller IA útil para tu oficina | 1.200 € | 0 € |
  | Paso a programa con Verifactu | 600 € | 0 € |
  | Diagnóstico de automatización | 0 € | 0 € |

- **`crm demo`:** carga unas 25 empresas **inventadas** (nombres claramente ficticios, en municipios reales de Soria: Soria, Almazán, Ólvega, Covaleda, Duruelo de la Sierra, San Leonardo de Yagüe, El Burgo de Osma, Ágreda...), repartidas por fases, con contactos falsos (teléfonos `600 000 0xx`, emails `@ejemplo.com`), interacciones, 3–4 clientes con contratos y facturas (alguna vencida). Sirve para ver el dashboard lleno y para las capturas del portfolio. Solo se ejecuta sobre una base de datos vacía o con `--forzar`.

## 6. Integraciones

- **MCP (stdio):**
  - Lectura: `buscar_empresas`, `ver_empresa`, `proximos_pasos`, `resumen_pipeline`, `resumen_clientes` (MRR, pendiente de cobro).
  - Escritura: `crear_empresa`, `registrar_interaccion`, `cambiar_fase`, `fijar_proximo_paso`.
  - **Prohibido:** borrar, enviar correos o mensajes y registrar facturas por MCP en esta versión.
  - Las escrituras quedan registradas con el autor `mcp`.
  - Usa el SDK oficial de MCP para Python (paquete `mcp`). **Verifica la API y la versión actuales en la documentación antes de escribir código** (regla 2 de `desarrollo/CLAUDE.md`).
- **Importación CSV/Excel** (`crm importar <archivo> [--dry-run]`): columnas mapeables a los campos de Empresa y Contacto. Las empresas nuevas entran en `0-Lead`. Se detectan duplicados por nombre normalizado. `--dry-run` enseña qué haría sin escribir.
- **Exportación a Obsidian** (`crm exportar-obsidian [--dry-run]`):
  - Escribe la tabla resumen de Potenciales y Clientes **solo entre** `<!-- crm:resumen:inicio -->` y `<!-- crm:resumen:fin -->` en `negocio/clientes_potenciales.md` de la bóveda (`CRM_VAULT_PATH`).
  - Si los marcadores no existen, **no escribe nada** y explica cómo añadirlos.
  - Escritura atómica; el resto del archivo queda intacto byte a byte.

## 7. Orden de recorte si no da tiempo

Importación CSV → arrastrar y soltar en el kanban (queda el cambio de fase por botón) → gráficos (quedan las cifras) → exportación a Obsidian.

Nunca se recortan: login, potenciales, clientes con MRR, facturas y cobros, MCP básico y tests de la lógica de negocio.

## 8. Reglas de este proyecto

1. **Seguridad mínima no negociable:**
   - Contraseñas con hash.
   - Cookie de sesión firmada, `HttpOnly` y `SameSite=Lax` o `Strict`, con `SECRET_KEY` desde el entorno. Si falta, se genera una aleatoria en desarrollo con un aviso en el log.
   - Protección CSRF en los formularios (token o comprobación de `Origin`).
   - La app escucha en `127.0.0.1` por defecto.
   - Plantillas con autoescape.
2. **Privacidad:** en el repositorio no entran datos reales. `data/`, `*.db` y `.env` están en `.gitignore`. Los tests y la demo usan datos inventados.
3. **No tocar la bóveda real** salvo con `crm exportar-obsidian` lanzado por Raúl. Los tests usan una bóveda temporal (`tmp_path`).
4. **Tests:** `pytest` sobre `services` (fases, conversión a cliente, MRR, estados de factura, importación, exportación) y tests de humo de las rutas principales con el cliente de pruebas de FastAPI. `ruff check` y `ruff format` limpios.
5. **Commits pequeños y frecuentes**, en español, con un mensaje que diga qué y por qué. **Nunca `git push`**: lo hace Raúl cuando revise.
6. **Modo tutor:** Raúl revisa al final y quiere aprender.
   - Mantén `docs/GUIA.md`: arquitectura en un diagrama, cómo viaja una petición (navegador → FastAPI → services → base de datos → plantilla HTMX), los conceptos nuevos explicados (HTMX, migraciones, sesiones y CSRF, MCP) y **dónde suele fallar cada parte**.
   - Mantén `DECISIONES.md`: cada decisión que tomes sin preguntar, con su motivo y su alternativa.
7. **Agentes y skills del proyecto** (en `.claude/`):
   - `revisor-codigo`: revisa sin editar.
   - `tester`: escribe y ejecuta tests.
   - `investigador-fuentes`: solo para el futuro buscador de leads.
   - Skill `/cierre-sesion`: comprobaciones, revisión, guía, horas y estado.

## 9. Fuera de alcance (esta versión)

Despliegue en servidor, MCP remoto, buscador de leads (las reglas legales ya están en `internos/CLAUDE.md` y se detallarán al empezarlo), varios usuarios con roles, envío de correos o WhatsApp, emisión de facturas, recordatorios por notificación, sincronización bidireccional con Obsidian.

## 10. Comandos (cuando existan)

```bash
uv sync                          # instalar dependencias
uv run alembic upgrade head      # crear o actualizar la base de datos
uv run crm crear-usuario raul    # pide la contraseña
uv run crm demo                  # datos inventados para ver el dashboard
uv run crm serve                 # http://127.0.0.1:8000
uv run pytest && uv run ruff check .
```

## 11. Registro de horas (de Raúl)

| Fecha | Qué | Horas | Notas |
|---|---|---|---|
| 2026-10-07 | Requisitos y preparación | | |
| 2026-10-07 | Sesión nocturna sin supervisión (agente): niveles 1, 2 y 3 (sin arrastrar y soltar). Ver `MANANA.md` | | Horas de agente, no cuentan; Raúl: revisión pendiente |
