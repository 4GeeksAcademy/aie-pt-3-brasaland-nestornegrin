# Regla: campos en cascada de Brasa Points

**Alcance:** por patrón de archivo — aplica a cualquier archivo que implemente o modifique los selects de País / Ciudad / Ubicación favorita del formulario de registro Brasa Points (en Hito 1: `validation.js`; en `uis/website`, cualquier componente bajo `components/brasa-points/` o similar que renderice ese formulario).

## Por qué existe

El formulario de Brasa Points tiene tres campos dependientes: **País → Ciudad → Ubicación favorita**. Esta relación está definida como datos de negocio en `CONTEXT.es.md`, no como una decisión de UI libre. Si un agente la reimplementa "de memoria" al migrar de HTML a React, es fácil que omita una ciudad o una ubicación y rompa silenciosamente el formulario (el campo simplemente no ofrece una opción válida).

## Qué debe cumplirse

1. El mapa País → Ciudades debe ser exactamente:
   - Colombia → Medellín, Bogotá, Cali
   - Estados Unidos → Miami, Orlando
2. El mapa (País, Ciudad) → Ubicaciones debe ser exactamente (14 ubicaciones en total):
   - Colombia/Medellín → Brasaland El Poblado, Brasaland Laureles, Brasaland Envigado, Brasaland Sabaneta
   - Colombia/Bogotá → Brasaland Usaquén, Brasaland Chapinero, Brasaland Zona Rosa
   - Colombia/Cali → Brasaland Granada, Brasaland Ciudad Jardín, Brasaland Unicentro
   - Estados Unidos/Miami → Brasaland Brickell, Brasaland Coral Gables
   - Estados Unidos/Orlando → Brasaland Downtown, Brasaland International Drive
3. Estos datos viven en **un solo lugar** (una constante o módulo), no se duplican entre `validation.js` y el nuevo componente React — al migrar, la fuente de verdad pasa a ser el componente de `uis/website`, y `validation.js` queda como referencia histórica del Hito 1 (no se borra, no se sincroniza a mano de ahí en adelante).
4. Cambiar "Ciudad" reinicia siempre "Ubicación favorita" a su placeholder ("Selecciona país y ciudad primero") — nunca debe quedar una ubicación seleccionada que no corresponda a la ciudad actual.

## Cómo verificar

Seleccionar cada combinación de País + Ciudad en el formulario renderizado y confirmar que el select de "Ubicación favorita" ofrece exactamente las opciones listadas arriba, ni más ni menos.
