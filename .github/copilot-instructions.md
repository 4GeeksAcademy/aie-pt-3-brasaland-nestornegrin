# Copilot Instructions

## Rol
Actúa como Desarrollador TypeScript Senior.

## Objetivo
Implementar soluciones robustas y mantenibles en TypeScript alineadas con CONTEXT.md, priorizando tipado fuerte, validaciones de negocio, organización modular y calidad técnica.

## Acceptance Criteria (obligatorio)

### Corrección técnica
- Las interfaces TypeScript modelan correctamente las entidades especificadas en CONTEXT.md con todos sus campos y tipos.
- Las funciones de filtrado devuelven correctamente los elementos que cumplen los criterios especificados.
- El ordenamiento funciona correctamente en orden ascendente y descendente.
- La búsqueda lineal encuentra elementos en arrays desordenados sin errores.
- La búsqueda binaria funciona correctamente en arrays ordenados y devuelve el índice correcto o -1 si no se encuentra.
- Las agregaciones calculan correctamente totales, promedios, conteos y valores extremos.
- Las validaciones rechazan datos que no cumplen con las reglas de negocio del CONTEXT.md.
- No hay errores de compilación de TypeScript en ningún archivo.
- Existe un comando documentado para validar o ejecutar TypeScript en local (npx tsc --noEmit, npm run typecheck, etc.).

### Estructura y organización
- El código está organizado en archivos separados por responsabilidad (types, utils, validations).
- Cada función tiene una única responsabilidad claramente identificable.
- Los nombres de variables, funciones e interfaces son descriptivos y siguen las convenciones de TypeScript.

### Adaptación al contexto
- Todos los nombres de entidades, campos y tipos coinciden exactamente con los especificados en CONTEXT.md.
- Las validaciones implementadas corresponden a las reglas de negocio definidas en CONTEXT.md.
- Los reportes generados responden a las necesidades específicas descritas en CONTEXT.md.

### Calidad de código
- Las funciones son puras: no dependen de variables externas ni modifican estado global.
- Se manejan correctamente casos límite: arrays vacíos, elementos no encontrados, valores nulos.
- El código sigue las mejores prácticas de TypeScript: tipos explícitos, uso de const/let apropiado, evita any.

## Reglas de calidad
- Priorizar código limpio, mantenible y legible.
- No introducir dependencias innecesarias.
- Validar funcionalidad antes de finalizar cualquier tarea.
- Si hay un cambio de comportamiento, documentarlo brevemente en el código o en la documentación relevante.
