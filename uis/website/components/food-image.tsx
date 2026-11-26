"use client";

import Image from "next/image";
import { useState } from "react";
import { FlameMark } from "./logo";

/**
 * Imagen con respaldo: si la foto remota no carga, se muestra un degradado
 * de marca en lugar de un icono roto.
 */
export function FoodImage({
  src,
  alt,
  className = "",
  sizes = "(min-width: 1024px) 33vw, 100vw",
  priority = false,
}: {
  src?: string;
  alt: string;
  className?: string;
  sizes?: string;
  priority?: boolean;
}) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <div
        role="img"
        aria-label={alt}
        className={`absolute inset-0 flex items-center justify-center bg-gradient-to-br from-char via-coal to-ember-dark/60`}
      >
        <FlameMark className="h-12 w-12 opacity-70" />
      </div>
    );
  }

  return (
    <Image
      src={src}
      alt={alt}
      fill
      sizes={sizes}
      priority={priority}
      onError={() => setFailed(true)}
      className={`object-cover ${className}`}
    />
  );
}
