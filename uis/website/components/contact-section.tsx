export function ContactSection() {
  return (
    <section
      id="contacto"
      className="mx-auto max-w-6xl px-4 py-14 sm:px-6 lg:px-8"
      aria-labelledby="contacto-title"
    >
      <h2 id="contacto-title" className="text-2xl font-black text-red-900 sm:text-3xl">
        Contacto
      </h2>
      <div className="mt-5 grid gap-4 text-zinc-700 sm:grid-cols-2 lg:grid-cols-3">
        <p>
          <strong>Email:</strong> hola@brasaland.com
        </p>
        <p>
          <strong>Colombia:</strong> +57 4 123 4567
        </p>
        <p>
          <strong>Florida:</strong> +1 305 123 4567
        </p>
      </div>
    </section>
  );
}
