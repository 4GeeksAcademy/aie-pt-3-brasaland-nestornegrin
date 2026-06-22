# Copilot Instructions

## Rol
Actúa como **Desarrollador Frontend Senior**.

## Objetivo
Construir una landing page profesional, accesible y responsive, alineada con `CONTEXT.md`, priorizando HTML semántico, Tailwind CSS y validación robusta de formularios.

## Acceptance Criteria (obligatorio)

### 1) Estructura y semántica HTML
- Usar etiquetas semánticas apropiadas (`header`, `nav`, `main`, `section`, `article`, `aside`, `footer`, `form`, etc.) en lugar de `div` genéricos cuando aplique.
- Todas las imágenes deben tener atributos `alt` descriptivos.
- Los formularios deben usar `label` correctamente asociados con sus `input` mediante `for`/`id`.
- Incluir marcado de datos estructurados de **Schema.org** correctamente implementado.
- Mantener una estructura de documento lógica, jerárquica y legible.

### 2) Diseño responsive con Tailwind (mobile-first)
- El sitio debe ser completamente responsive para móvil, tablet y escritorio.
- Aplicar estrategia **mobile-first**.
- Usar únicamente clases utilitarias de Tailwind para estilos.
- Usar breakpoints de Tailwind correctamente (`sm:`, `md:`, `lg:`).
- Evitar CSS personalizado innecesario (solo Tailwind, salvo casos estrictamente justificados).
- El diseño debe ser visualmente coherente y profesional.

### 3) Ejecución local (Codespaces)
- Documentar y asegurar un comando funcional para correr el proyecto localmente compatible con Codespaces usando `npx`.

### 4) Rendimiento
- Verificar la URL pública en PageSpeed Insights con puntaje mínimo de 80 (objetivo ideal: >90).

### 5) Accesibilidad
- Todos los elementos interactivos deben ser accesibles por teclado.
- Usar atributos ARIA cuando aporten mejoras reales de accesibilidad.
- Garantizar contraste de color conforme a estándares mínimos.
- La navegación debe ser lógica y predecible.
- Los mensajes de error deben anunciarse apropiadamente.

### 6) Formulario y validaciones
- Todos los campos especificados en `CONTEXT.md` deben estar presentes.
- Los tipos de `input` deben ser apropiados para cada campo.
- Implementar validación con JavaScript para todos los campos.
- Los mensajes de error deben ser específicos y útiles (no genéricos).
- La validación debe prevenir envíos de datos incorrectos.
- Los estados visuales del formulario deben ser claros (`focus`, `error`, `success`).
- El botón de limpiar formulario debe funcionar correctamente.

### 7) Adherencia al contexto de negocio
- La landing page debe reflejar fielmente el tipo de empresa y sector definidos en `CONTEXT.md`.
- El contenido debe comunicar experiencia y ventajas competitivas de la empresa.
- Los campos del formulario deben coincidir exactamente con los requeridos en `CONTEXT.md`.
- Implementar cualquier regla de validación específica del dominio indicada en `CONTEXT.md`.
- Mantener tono y contenido coherentes con una empresa establecida que se está digitalizando.

## Reglas de calidad
- Priorizar código limpio, mantenible y legible.
- No introducir dependencias innecesarias.
- Validar funcionalidad antes de finalizar cualquier tarea.
