/**
 * SupplierDirectory: la tabla (la parte cara del componente) no debe volver a
 * calcularse cuando cambia estado que no la afecta, p. ej. al teclear en el
 * formulario de alta. Cada fila llama una vez a Date#toLocaleString, así que
 * contar esas llamadas cuenta cuántas filas se han vuelto a construir.
 *
 * Benchmark opcional (no forma parte de la suite normal):
 *   BENCH=1 npx jest __tests__/supplier-directory.test.tsx -t benchmark
 */
import { act, Profiler } from "react";
import { createRoot, type Root } from "react-dom/client";
import { apiFetch } from "@/lib/api-client";
import { SupplierDirectory } from "../components/supplier-directory";

jest.mock("@/lib/api-client", () => ({
  apiFetch: jest.fn(),
  readApiError: jest.fn(async () => "error"),
}));

type SupplierFixture = {
  id: number;
  name: string;
  categories: string[];
  country: string;
  rate: number;
  status: "Activo" | "Suspendido";
  updated_at: string;
};

const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

function makeSuppliers(count: number): SupplierFixture[] {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    name: `Proveedor ${index + 1}`,
    categories: ["Carnes"],
    country: "Colombia",
    rate: 1.5 + index / 100,
    status: "Activo" as const,
    updated_at: new Date(2026, 0, 1 + (index % 28)).toISOString(),
  }));
}

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, status: ok ? 200 : 500, json: async () => body } as Response;
}

let container: HTMLDivElement;
let root: Root;

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mockedApiFetch.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  jest.restoreAllMocks();
});

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function mount(suppliers: SupplierFixture[], onRender?: (phase: string, duration: number) => void) {
  mockedApiFetch.mockImplementation(async () => jsonResponse(suppliers));
  await act(async () => {
    root.render(
      <Profiler id="suppliers" onRender={(_id, phase, actualDuration) => onRender?.(phase, actualDuration)}>
        <SupplierDirectory />
      </Profiler>,
    );
  });
  await flush();
}

function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const nameInput = () => container.querySelector<HTMLInputElement>('input[placeholder="Nombre del proveedor"]')!;

describe("SupplierDirectory", () => {
  test("teclear en el formulario de alta no reconstruye las filas de la tabla", async () => {
    await mount(makeSuppliers(40));
    expect(container.querySelectorAll("tbody tr")).toHaveLength(40);
    const rowBuilds = jest.spyOn(Date.prototype, "toLocaleString");

    "Nuevo".split("").forEach((_, index) => typeInto(nameInput(), "Nuevo".slice(0, index + 1)));

    expect(nameInput().value).toBe("Nuevo");
    expect(rowBuilds).not.toHaveBeenCalled();
  });

  test("editar una tarifa sí actualiza su fila y Guardar envía el valor tecleado", async () => {
    await mount(makeSuppliers(3));
    const rateInput = container.querySelector<HTMLInputElement>('input[aria-label="Tarifa de Proveedor 2"]')!;

    typeInto(rateInput, "9.75");
    expect(container.querySelector<HTMLInputElement>('input[aria-label="Tarifa de Proveedor 2"]')!.value).toBe("9.75");

    mockedApiFetch.mockImplementation(async () => jsonResponse({ ...makeSuppliers(3)[1], rate: 9.75 }));
    const saveButton = [...container.querySelectorAll("tbody tr")[1].querySelectorAll("button")].find((b) => b.textContent === "Guardar")!;
    await act(async () => saveButton.click());
    await flush();

    const [url, init] = mockedApiFetch.mock.calls.at(-1)!;
    expect(url).toBe("/api/suppliers/2/rate");
    expect(JSON.parse(String(init?.body))).toEqual({ current_rate: 9.75 });
  });

  test("cambiar el estado de un proveedor actualiza su fila (los manejadores no quedan obsoletos)", async () => {
    await mount(makeSuppliers(2));
    const toggle = () => container.querySelectorAll("tbody tr")[0].querySelector<HTMLButtonElement>("td:nth-child(4) button")!;
    expect(toggle().textContent).toBe("Activo");

    mockedApiFetch.mockImplementation(async () => jsonResponse({ ...makeSuppliers(2)[0], status: "Suspendido" }));
    await act(async () => toggle().click());
    await flush();

    expect(toggle().textContent).toBe("Suspendido");
    const [url, init] = mockedApiFetch.mock.calls.at(-1)!;
    expect(url).toBe("/api/suppliers/1/status");
    expect(JSON.parse(String(init?.body))).toEqual({ status: "Suspendido" });
  });

  const bench = process.env.BENCH ? test : test.skip;
  bench("benchmark: coste de renderizar al teclear en el formulario de alta", async () => {
    const lines: string[] = [];
    for (const count of [10, 200, 1500]) {
      const durations: number[] = [];
      let measuring = false;
      act(() => root.unmount());
      container.remove();
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
      await mount(makeSuppliers(count), (phase, duration) => {
        if (measuring && phase === "update") durations.push(duration);
      });
      measuring = true;
      for (let keystroke = 1; keystroke <= 20; keystroke += 1) typeInto(nameInput(), "x".repeat(keystroke));
      const sorted = [...durations].sort((a, b) => a - b);
      lines.push(`${String(count).padStart(5)} proveedores | mediana por tecla: ${sorted[Math.floor(sorted.length / 2)].toFixed(1)} ms | total 20 teclas: ${durations.reduce((a, b) => a + b, 0).toFixed(0)} ms`);
    }
    process.stdout.write(`\n${lines.join("\n")}\n`);
  });
});
