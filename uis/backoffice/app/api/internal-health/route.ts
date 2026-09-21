import { NextResponse } from "next/server";

// Esta ruta corre del lado del SERVIDOR, dentro del proceso de Next.js del
// contenedor "interfaces" -- nunca en el navegador. Su único propósito es
// demostrar, de forma verificable, que los dos contenedores de este
// docker-compose sí pueden comunicarse por el nombre de servicio Docker
// ("api"), tal como pide el ticket #infra-40.
//
// El resto de la aplicación (lib/api-client.ts, lib/inventory.ts) llama a
// la API directamente desde el NAVEGADOR (son componentes cliente), y el
// navegador nunca puede resolver nombres de la red interna de Docker --
// solo el puerto publicado en el host (NEXT_PUBLIC_API_URL=localhost:8000).
// Esa es la razón documentada en el .env.example de por qué esas llamadas
// siguen usando localhost: no es un descuido, es la única URL que el
// navegador puede alcanzar. Esta ruta es la contraparte que sí demuestra
// la comunicación servicio-a-servicio dentro de la red de Docker.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://api:8000";

export async function GET() {
  try {
    const response = await fetch(`${API_INTERNAL_URL}/docs`);
    return NextResponse.json({
      reachable: response.ok,
      calledFrom: "servidor (contenedor interfaces)",
      target: API_INTERNAL_URL,
    });
  } catch (error) {
    return NextResponse.json(
      {
        reachable: false,
        calledFrom: "servidor (contenedor interfaces)",
        target: API_INTERNAL_URL,
        error: error instanceof Error ? error.message : String(error),
      },
      { status: 502 },
    );
  }
}
