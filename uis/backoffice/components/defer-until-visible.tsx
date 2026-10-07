"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

type DeferUntilVisibleProps = {
  children: ReactNode;
  /** Altura reservada mientras no se muestra el contenido (px). */
  minHeight: number;
  /** Texto accesible del hueco reservado. */
  label: string;
  /** Ancla del contenedor: tiene que existir aunque el contenido aún no, para que `#id` siga funcionando. */
  id?: string;
  /** Margen para empezar a cargar un poco antes de que sea visible. */
  rootMargin?: string;
};

/**
 * Monta a sus hijos solo cuando entran (o están a punto de entrar) en el
 * viewport. Combinado con `next/dynamic`, evita descargar el JavaScript, y
 * lanzar las peticiones de datos, de secciones que están muy por debajo del
 * pliegue hasta que el usuario llega a ellas.
 *
 * Sin IntersectionObserver (navegadores muy antiguos) monta los hijos de
 * inmediato: se pierde la optimización, nunca el contenido.
 */
export function DeferUntilVisible({ children, minHeight, label, id, rootMargin = "300px" }: DeferUntilVisibleProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    if (typeof IntersectionObserver === "undefined") {
      // Diferido a un microtask: react-hooks/set-state-in-effect (mismo patrón que el resto del backoffice).
      void Promise.resolve().then(() => setVisible(true));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [rootMargin]);

  return (
    <div ref={containerRef} id={id} style={visible ? undefined : { minHeight }} aria-busy={!visible}>
      {visible ? children : <p className="text-sm text-zinc-500">{label}</p>}
    </div>
  );
}
