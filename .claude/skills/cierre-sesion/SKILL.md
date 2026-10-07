---
name: cierre-sesion
description: Cierre de una sesión de trabajo en el CRM. Pasa las comprobaciones, lanza la revisión, actualiza la guía de aprendizaje (modo tutor), DECISIONES.md y MANANA.md, y deja un commit limpio. Úsalo al terminar una sesión larga o cuando Raúl escriba /cierre-sesion.
---

# Cierre de sesión del CRM

Sigue estos pasos en orden. Si uno falla, no lo escondas: anótalo en `MANANA.md`.

1. **Comprobaciones:** `uv run ruff format .`, `uv run ruff check .` y `uv run pytest`. Arregla lo que sea rápido. Lo que no, apúntalo.
2. **Tests:** pide al subagente `tester` que revise los huecos de cobertura de lo hecho en la sesión.
3. **Revisión:** pide al subagente `revisor-codigo` que revise los cambios de la sesión (`git log` desde el primer commit de hoy). Corrige los **CRÍTICOS** e **IMPORTANTES**; los MENORES van a `MANANA.md`.
4. **Modo tutor:** actualiza `docs/GUIA.md`:
   - El diagrama de arquitectura y el recorrido de una petición.
   - Los conceptos nuevos de la sesión, explicados para alguien con buena base técnica que no los ha usado.
   - **Dónde suele fallar** cada parte y cómo diagnosticarlo.
   - Tres preguntas de autoevaluación para que Raúl compruebe que lo ha entendido.
5. **Decisiones:** comprueba que cada decisión tomada sin preguntar está en `DECISIONES.md` (decisión, motivo, alternativa).
6. **`MANANA.md`:** qué funciona (✅ / ⚠️ / ❌), cómo verlo en 3 comandos, qué revisar primero, pendiente por prioridad, decisiones discutibles y avisos de lo no verificado.
7. **Estado del proyecto:** en `CLAUDE.md` (§11, Registro de horas) añade una fila con la fecha y lo hecho; deja las horas en blanco para que las rellene Raúl.
8. **Commit final:** `git add -A` (comprobando antes con `git status` que no entra `.env`, `data/` ni ninguna base de datos) y commit con un mensaje que resuma la sesión. **Nunca `git push`.**

Termina con un resumen de 5 líneas como máximo: qué se hizo, qué queda y el primer paso recomendado para Raúl.
