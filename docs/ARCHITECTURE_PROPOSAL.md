# Propuesta de arquitectura para el backend de Brasaland

## 1. Resumen ejecutivo

Para Brasaland, la opción más adecuada no es un backend minimalista de una sola capa ni una abstracción demasiado genérica. La empresa tiene una operación real con múltiples restaurantes, dos países, un programa de fidelización digital (Brasa Points), una web pública y una interfaz interna de gestión. Eso exige un backend con claridad de dominio, reglas de negocio explícitas y una separación de responsabilidades que permita crecer sin acoplar el negocio a la capa HTTP.

La propuesta es una arquitectura en capas con orientación a dominio, implementada como una API monolítica modular en FastAPI. En práctica, esto significa:

- una capa de entrada HTTP con routers y endpoints;
- una capa de servicios/aplicación con lógica de negocio;
- una capa de dominio con modelos y reglas del negocio;
- una capa de infraestructura con acceso a base de datos, integraciones y utilidades.

Esto encaja mejor que una arquitectura puramente MVC, porque en APIs modernas la lógica relevante no debe depender de un controlador web. Tampoco es la mejor opción un modelo serverless puro para la fase inicial, porque Brasaland tiene requisitos de operación, administración y evolución del dominio que no son triviales y podrían volverse difíciles de sostener si se fragmentan en funciones aisladas sin una estructura clara. La decisión se basa en la realidad del negocio, no en una preferencia técnica genérica.

---

## 2. Contexto del negocio que justifica la arquitectura

La arquitectura debe responder a cuatro realidades del negocio:

1. Brasaland no es un proyecto de una sola pantalla. Tiene una operación multi-local con 14 restaurantes y dos mercados: Colombia y Estados Unidos.
2. El sistema de negocio central no es solamente marketing; incluye datos operativos y de fidelización, así como reglas de validación que deben mantenerse consistentes.
3. La web pública y la app interna son consumidores del backend, pero representan experiencias distintas: una para clientes y otra para gestión interna.
4. El proyecto ya muestra una tendencia a crecer en dominio y especialización: programar la lógica de negocio en un módulo reusable de TypeScript y luego conectar frontend y backend es evidencia de que la empresa quiere separar claramente el negocio de la presentación.

Esto vuelve esencial una arquitectura que permita:

- definir claramente qué pertenece al dominio de restaurantes, clientes, fidelización y administración;
- evitar mezclar validaciones, infraestructura y endpoints en un mismo archivo;
- soportar crecimiento posterior con nuevas funciones de inventario, analítica, campañas, gestión de empleados o automatizaciones.

---

## 3. Patrón arquitectónico propuesto

### 3.1 Decisión: arquitectura en capas con enfoque de dominio

Se propone una arquitectura basada en capas, con una organización de dominios muy similar a una implementación “clean architecture” o “hexagonal” aplicada dentro de FastAPI. La idea no es imponer una filosofía abstracta, sino darle al equipo una estructura que haga explícita la separación entre:

- HTTP y transporte
- lógica de aplicación
- dominio del negocio
- persistencia e integraciones externas

### 3.2 Por qué no MVC tradicional

MVC suele ser útil en aplicaciones monolíticas de UI renderizadas en servidor, pero aquí el backend es una API que servirá a varios clientes: la web pública, un panel interno y posiblemente futuras interfaces móviles, herramientas internas o automatizaciones. En ese escenario, el “controlador” no es la unidad central del diseño; el dominio del negocio sí lo es.

Si la arquitectura se hiciera como un “controlador gigante” con validaciones, acceso a DB y lógica de negocio mezclada, el sistema se volvería difícil de mantener a medida que aparezcan más reglas, más locales y más procesos de negocio.

### 3.3 Por qué no serverless puro en esta fase

El enfoque serverless puede ser atractivo para microservicios o cargas muy variables, pero aquí no parece ser la mejor opción inicial por varias razones:

- La empresa necesita claridad operativa y organización del dominio desde el principio.
- El backend tendrá varias entidades de negocio que deben evolucionar juntos: restaurantes, ubicaciones, clientes, Brasa Points, campañas, analytics.
- La coordinación entre dominios y la trazabilidad de errores es más sencilla cuando se trabaja con una API monolítica modular bien organizada que con un conjunto de funciones muy pequeñas, sin una estructura estable.

En otras palabras: una arquitectura modular monolítica con fronteras por dominio es una mejor base para una empresa que aún está definiendo flujo de negocio y reglas operativas, y luego se puede descomponer en servicios si el crecimiento realmente lo exige.

---

## 4. Estructura propuesta del backend

La organización recomendada para el proyecto backend debe reflejar dos ideas clave:

1. separación por dominio del negocio;
2. separación por responsabilidad técnica.

### 4.1 Estructura de carpetas sugerida

Una estructura típica y reconocible en FastAPI sería la siguiente:

```text
services/
  api/
    app/
      main.py
      core/
        __init__.py
        config.py
        security.py
        dependencies.py
        cors.py
      api/
        v1/
          routers/
            locations.py
            loyalty.py
            auth.py
            customers.py
            analytics.py
          routers.py
      domains/
        restaurants/
          __init__.py
          models.py
          schemas.py
          service.py
          repository.py
        loyalty/
          __init__.py
          models.py
          schemas.py
          service.py
          repository.py
        customers/
          __init__.py
          models.py
          schemas.py
          service.py
          repository.py
        operations/
          __init__.py
          models.py
          schemas.py
          service.py
          repository.py
      infrastructure/
        database/
          session.py
          base.py
        repositories/
          restaurant_repository.py
          loyalty_repository.py
        integrations/
          email_client.py
          notification_service.py
      schemas/
        common.py
        response.py
      shared/
        exceptions.py
        utils.py
        logging.py
      tests/
        api/
        domains/
```

### 4.2 Criterio de separación

La separación no debe ser por “archivo de la técnica” únicamente, sino por dominio y responsabilidad:

- `routers`: exponen HTTP y rutean la entrada del cliente.
- `schemas`: describen contratos de entrada/salida para validación y serialización.
- `service`: contiene la lógica de negocio, validaciones de caso de uso y orquestación de operaciones.
- `repository`: encapsula acceso a la base de datos o persistencia.
- `core`: configuración central del sistema, seguridad y dependencias.
- `infrastructure`: implementaciones concretas de conexiones, servicios externos y adaptadores.

Esto es importante porque, en un negocio como Brasaland, un mismo endpoint puede implicar restaurante, validación de cliente, puntos del programa y notificaciones. Si todo se mete en el router, el código se vuelve difícil de rastrear y de probar.

---

## 5. Organización de routers y endpoints en FastAPI

La convención estándar en FastAPI es agrupar rutas por dominio y versionar la API. Para Brasaland, esto es especialmente útil porque el negocio tiene claros “núcleos” de funcionalidad.

### 5.1 Ruta base y versionado

La API debería vivir bajo un prefijo como:

- `/api/v1/...`

Esto permite evolucionar la API sin romper clientes actuales, y también refleja la práctica estándar de FastAPI cuando una aplicación empieza a crecer.

### 5.2 Agrupación por dominio

Los routers deberían agruparse de la siguiente manera:

#### a) Restaurantes y ubicaciones

- `GET /api/v1/locations`
- `GET /api/v1/locations/{location_id}`
- `GET /api/v1/locations/countries`
- `GET /api/v1/locations/{location_id}/hours`

Justificación: la web pública, la búsqueda de locales y la lógica propia del negocio necesitan datos de ubicación y acceso a sucursales. Este dominio es la base operativa del negocio y afecta tanto al cliente final como a la operación diaria.

#### b) Clientes y registro de Brasa Points

- `POST /api/v1/loyalty/register`
- `GET /api/v1/loyalty/customers/{customer_id}`
- `PATCH /api/v1/loyalty/customers/{customer_id}`
- `GET /api/v1/loyalty/customers/{customer_id}/points`
- `POST /api/v1/loyalty/customers/{customer_id}/redeem`

Justificación: Brasa Points es un dominio clave para la empresa. Aquí existen reglas de negocio claras: datos del cliente, elegibilidad, aceptación de términos, país, ciudad, ubicación favorita, edad mínima, y cálculo de puntos. Este dominio debe estar aislado del resto para no mezclarlo con la API pública general.

#### c) Autenticación y perfil

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/profile`

Justificación: aunque Brasaland no es una app transaccional de e-commerce, sí va a manejar perfiles, clientes y acceso a servicios del programa. La autenticación debe ser modular y segura, separada del resto de las entidades del negocio.

#### d) Campañas y marketing

- `GET /api/v1/marketing/campaigns`
- `POST /api/v1/marketing/campaigns`
- `GET /api/v1/marketing/campaigns/{campaign_id}`

Justificación: la marca y la campaña de fidelización requieren gestión de experiencias y promociones. Esto no debe mezclarse con la lógica de restaurantes o con la capa de autenticación.

#### e) Analytics y reportes internos

- `GET /api/v1/analytics/summary`
- `GET /api/v1/analytics/locations/{location_id}/performance`
- `GET /api/v1/analytics/loyalty/points`

Justificación: esta empresa quiere crecer con decisiones basadas en datos y la estructura futura del agente de IA de inventario/compra. La analítica es una capa transversal que puede reutilizar información de otros dominios sin duplicar lógica.

### 5.3 Regla de diseño para el equipo

Cada router debe delegar la operación a un servicio del dominio. El router no debe resolver validaciones complejas ni hacer consultas directas de base de datos. Su responsabilidad es recibir la solicitud HTTP y devolver la respuesta adecuada.

Esto hace que la API sea predecible, testeable y fácil de mantener.

---

## 6. Relación con la estructura estándar de FastAPI

La estructura que propone FastAPI en la práctica suele seguir una lógica muy parecida a la que se usa en proyectos reales y bien mantenidos:

- `main.py` como entrada principal de la app;
- `core/` para configuración, seguridad y dependencias;
- `api/` o `routers/` para la capa HTTP;
- `models/` o `schemas/` para validación de entrada y salida;
- `crud/`, `repositories/` o `services/` para acceso a datos y lógica;
- `config.py` y variables de entorno para manejar entornos.

Esto no es solo una convención estética: es una forma de mantener un proyecto escalable y legible, y es la base que se observa en muchos proyectos FastAPI de producción. La razón fundamental es que un backend de empresa, aunque empiece pequeño, necesita que cada cambio tenga un sitio claro. Si el equipo sigue la convención estándar de FastAPI, el proyecto será más fácil de leer, de revisar y de extender.

La propuesta aquí toma esa base y la adapta al contexto de Brasaland, incorporando organización por dominio del negocio y no solo por capas técnicas.

---

## 7. Frontend y backend separados: cómo coexistirían

En este proyecto, el frontend y el backend no son una misma aplicación. Ya se observa una separación natural entre la web pública, la app interna y la lógica del negocio. La solución adecuada es mantenerlos como sistemas separados, aunque compartan un mismo repositorio monolítico en una primera etapa.

### 7.1 Monorepo vs repositorio separado

Para esta etapa, el esquema actual del monorepo es razonable:

- `uis/website` para la experiencia pública;
- `uis/backoffice` para uso interno;
- `services/` para el backend API.

Esto favorece:

- visibilidad de la arquitectura global;
- compartición de contexto de negocio;
- facilidad de evolución conjunta durante el sprint inicial.

Si el sistema crece mucho, podrían separarse repositorios de frontend y backend, pero no es la decisión necesaria desde el inicio. La separación funcional ya está presente y no exige una distribución artificial de código.

### 7.2 Comunicación por API

La comunicación entre frontend y backend debe ser por API REST JSON, con contratos claros y validaciones de entrada/salida. Esto evita acoplar la lógica del negocio a React o Next.js.

El backend no debería devolver HTML ni mezclar representación visual con datos. Debe exponer JSON estructurado y todos los clientes, tanto web como internal tools, lo consumirán de la misma manera.

### 7.3 Variables de entorno

La configuración del backend debe estar en variables de entorno, por ejemplo:

- `APP_ENV`
- `DATABASE_URL`
- `SECRET_KEY`
- `CORS_ALLOWED_ORIGINS`
- `SMTP_HOST`
- `REDIS_URL` (si se añade caché más adelante)

Esto permite separar entorno local, staging y producción, y evita que la aplicación dependa de valores fijos embebidos en el código.

### 7.4 CORS

Como el frontend y el backend serán sistemas separados, el backend debe configurar CORS con una política restrictiva. Es decir:

- permitir solamente orígenes conocidos (`localhost` en desarrollo, dominio web oficial, dominio del backoffice);
- no abrir la API a cualquier origen;
- mantener reglas específicas por entorno.

Esto es importante porque Brasaland manejará datos de clientes y de negocio, y no debería exponer una API sin límites.

---

## 8. Decisiones técnicas iniciales recomendadas

1. FastAPI como framework base del backend, por su velocidad de desarrollo, validación basada en Pydantic y estructura clara para APIs modernas.
2. PostgreSQL como base de datos de referencia, por su madurez, soporte relacional y facilidad para modelar datos de locales, clientes, puntos y campañas.
3. Pydantic v2 para validación de modelos y serialización.
4. SQLAlchemy o un ORM equivalente, con interacción por capas y repositorios, para desacoplar la lógica del dominio de la infraestructura de base de datos.
5. Estructura de versionado `/api/v1` para soportar evolución de la API sin romper clientes.
6. Logging, trazabilidad y manejo centralizado de errores en la capa `core` o `shared`.
7. Seguridad con autenticación, roles y permisos básicos definidos por tipo de usuario: cliente, administración local, administración corporativa.

---

## 9. Riesgos y puntos de atención

### Riesgo 1: mezclar rutas, negocio y persistencia

Si el equipo comienza creando endpoints con validaciones, consultas a base de datos y lógica de negocio todo en un mismo archivo, la API crecerá muy rápido y se volverá inmanejable. Esto puede provocar:

- duplicación de reglas;
- errores difíciles de depurar;
- cambios que rompen datos de clientes o puntos de fidelidad;
- tests frágiles y poco reutilizables.

### Riesgo 2: no definir claramente los dominios

Si el equipo no separa correctamente restaurantes, clientes y Brasa Points, será muy fácil mezclar responsabilidades. Por ejemplo, un endpoint de registro de cliente podría terminar validando operaciones que pertenecen a merchandising, campañas o administración. La consecuencia será una base de conocimiento confusa y una mayor probabilidad de inconsistencias.

### Riesgo 3: CORS y configuración de entorno mal definidos

Si se permiten orígenes abiertos o se hardcodean URLs y secretos, la aplicación puede funcionar en local pero romperse en producción o crear vulnerabilidades de seguridad. Esto afecta tanto a la web pública como al backoffice.

### Riesgo 4: modelar todo como una sola “tabla gigante”

Presenta una tendencia muy común en proyectos pequeños: guardar todo en una entidad muy amplia. En Brasaland eso es especialmente riesgoso porque el negocio tiene varios dominios con reglas distintas. Un modelo centralizado sin claridad de dominio hará más difícil mantener la lógica de puntos, ubicaciones, campañas y administración.

---

## 10. Conclusión

La arquitectura recomendada para Brasaland es una API backend en FastAPI con una estructura en capas y orientación a dominio, no una app monolítica sin organización ni una solución basada en funciones aisladas sin un modelo de negocio claro.

La razón principal es que Brasaland tiene un negocio real, con múltiples locales, dos mercados, un programa de fidelización, reglas de negocio no triviales y varios clientes de software. Eso exige claridad de dominio, separación de responsabilidades, escalabilidad evolutiva y una API bien versionada.

La propuesta combina lo mejor de dos cosas:

- la estructura estándar de FastAPI, que favorece legibilidad y mantenibilidad;
- una organización por dominio del negocio, que responde a la realidad operacional de la empresa.

Si el equipo sigue esta estructura desde el inicio, reducirá el riesgo de que el backend se convierta en un conjunto de endpoints sin sentido, y creará una base sólida para el crecimiento del sistema de fidelización, operaciones y analítica de Brasaland.
