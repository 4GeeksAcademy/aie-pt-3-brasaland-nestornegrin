/** Marca Brasaland: llama + nombre. SVG propio, sin dependencias. */
export function FlameMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden="true" focusable="false">
      <path
        d="M24 3c2 7-1 10-4 14-3 4-6 8-6 14a10 10 0 0 0 20 0c0-4-2-7-4-9 0 3-1 5-3 6 1-5 0-9-3-13-1-3-1-7 0-12Z"
        fill="#e8622a"
      />
      <path
        d="M24 24c1 3 4 5 4 9a4 4 0 0 1-8 0c0-4 3-6 4-9Z"
        fill="#f5b82e"
      />
    </svg>
  );
}

export function Logo({ tone = "light" }: { tone?: "light" | "dark" }) {
  return (
    <span className="inline-flex items-center gap-2">
      <FlameMark className="h-8 w-8 animate-flicker" />
      <span
        className={`font-display text-2xl font-bold uppercase tracking-[0.12em] ${
          tone === "light" ? "text-cream" : "text-ink"
        }`}
      >
        Brasaland
      </span>
    </span>
  );
}
