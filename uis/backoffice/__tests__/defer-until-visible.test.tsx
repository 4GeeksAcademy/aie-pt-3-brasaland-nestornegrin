import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { DeferUntilVisible } from "../components/defer-until-visible";

type ObserverCallback = (entries: Array<{ isIntersecting: boolean }>) => void;

let container: HTMLDivElement;
let root: Root;
let callbacks: ObserverCallback[];
let disconnected: number;

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  callbacks = [];
  disconnected = 0;
  (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = class {
    constructor(callback: ObserverCallback) {
      callbacks.push(callback);
    }
    observe() {}
    disconnect() {
      disconnected += 1;
    }
  };
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
});

function render() {
  act(() => {
    root.render(
      <DeferUntilVisible id="anchor" minHeight={200} label="Cargando sección">
        <p data-testid="content">Contenido pesado</p>
      </DeferUntilVisible>,
    );
  });
}

describe("DeferUntilVisible", () => {
  test("no monta los hijos mientras no sean visibles y conserva el ancla y la altura reservada", () => {
    render();

    expect(container.querySelector("[data-testid=content]")).toBeNull();
    const wrapper = container.querySelector<HTMLElement>("#anchor")!;
    expect(wrapper.style.minHeight).toBe("200px");
    expect(wrapper.textContent).toBe("Cargando sección");
  });

  test("monta los hijos al entrar en el viewport y deja de observar", () => {
    render();

    act(() => callbacks[0]([{ isIntersecting: false }]));
    expect(container.querySelector("[data-testid=content]")).toBeNull();

    act(() => callbacks[0]([{ isIntersecting: true }]));
    expect(container.querySelector("[data-testid=content]")?.textContent).toBe("Contenido pesado");
    expect(container.querySelector("#anchor")).not.toBeNull(); // el ancla sigue ahí tras cargar
    expect(disconnected).toBeGreaterThanOrEqual(1);
  });

  test("sin IntersectionObserver monta los hijos igualmente (se pierde la optimización, no el contenido)", async () => {
    delete (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;

    render();
    await act(async () => {
      await Promise.resolve();
    });

    expect(container.querySelector("[data-testid=content]")).not.toBeNull();
  });
});
