"use client";

import { useMemo, useState } from "react";
import type {
  City,
  Country,
  DietaryPreference,
  HowDidYouHearAboutUs,
} from "../../../src/types/models";
import {
  brasaPointsErrorMessages,
  isAdult,
  isValidEmail,
  isValidFullName,
  isValidPhone,
  validateRegistration,
} from "../../../src/validations";
import {
  cityOptionsByCountry,
  dietaryPreferenceOptions,
  locationsByCountryAndCity,
  sourceOptions,
} from "@/lib/locations-data";

type FormState = {
  fullName: string;
  email: string;
  phone: string;
  country: Country | "";
  city: City | "";
  favoriteLocation: string;
  preferences: DietaryPreference[];
  source: HowDidYouHearAboutUs | "";
  birthDate: string;
  acceptedTerms: boolean;
  wantsOffers: boolean;
};

const initialState: FormState = {
  fullName: "",
  email: "",
  phone: "",
  country: "",
  city: "",
  favoriteLocation: "",
  preferences: [],
  source: "",
  birthDate: "",
  acceptedTerms: false,
  wantsOffers: false,
};

type FieldErrors = Partial<Record<keyof typeof brasaPointsErrorMessages, string>>;

export function BrasaPointsForm() {
  const [form, setForm] = useState<FormState>(initialState);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitted, setSubmitted] = useState(false);

  const cityOptions = useMemo(
    () => (form.country ? cityOptionsByCountry[form.country] : []),
    [form.country],
  );

  const locationOptions = useMemo(() => {
    if (!form.country || !form.city) return [];
    return locationsByCountryAndCity[form.country]?.[form.city] ?? [];
  }, [form.country, form.city]);

  function validateField(field: keyof typeof brasaPointsErrorMessages, value: unknown) {
    let isValid = true;

    if (field === "fullName") isValid = isValidFullName(String(value));
    if (field === "email") isValid = isValidEmail(String(value));
    if (field === "phone") isValid = isValidPhone(String(value), (form.country || "Colombia") as Country);
    if (field === "country") isValid = value !== "";
    if (field === "city") isValid = value !== "";
    if (field === "source") isValid = value !== "";
    if (field === "birthDate") isValid = isAdult(String(value));
    if (field === "terms") isValid = value === true;

    setErrors((previous) => ({
      ...previous,
      [field]: isValid ? undefined : brasaPointsErrorMessages[field],
    }));

    return isValid;
  }

  function handleCountryChange(value: string) {
    const nextCountry = value as Country | "";
    setForm((previous) => ({
      ...previous,
      country: nextCountry,
      city: "",
      favoriteLocation: "",
    }));
    setSubmitted(false);
    validateField("country", nextCountry);
  }

  function handleCityChange(value: string) {
    const nextCity = value as City | "";
    setForm((previous) => ({ ...previous, city: nextCity, favoriteLocation: "" }));
    setSubmitted(false);
    validateField("city", nextCity);
  }

  function togglePreference(preference: DietaryPreference) {
    setForm((previous) => {
      const alreadySelected = previous.preferences.includes(preference);
      return {
        ...previous,
        preferences: alreadySelected
          ? previous.preferences.filter((item) => item !== preference)
          : [...previous.preferences, preference],
      };
    });
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(false);

    const registration = {
      id: Date.now(),
      fullName: form.fullName,
      email: form.email,
      phone: form.phone,
      country: (form.country || "Colombia") as Country,
      city: (form.city || "Medellín") as City,
      favoriteLocation: form.favoriteLocation || undefined,
      dietaryPreferences: form.preferences,
      source: (form.source || "Otro") as HowDidYouHearAboutUs,
      birthDate: form.birthDate,
      acceptedTerms: form.acceptedTerms,
      wantsOffers: form.wantsOffers,
    };

    // Reuses the exact Hito 2 validation logic (src/validations.ts) instead
    // of re-implementing the business rules here.
    const result = validateRegistration(registration);

    const fieldChecks: Array<[keyof typeof brasaPointsErrorMessages, unknown]> = [
      ["fullName", form.fullName],
      ["email", form.email],
      ["phone", form.phone],
      ["country", form.country],
      ["city", form.city],
      ["source", form.source],
      ["birthDate", form.birthDate],
      ["terms", form.acceptedTerms],
    ];
    fieldChecks.forEach(([field, value]) => validateField(field, value));

    if (!result.isValid) {
      return;
    }

    setSubmitted(true);
    setForm(initialState);
  }

  return (
    <>
      {submitted ? (
        <div
          className="mt-6 rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-emerald-800"
          role="status"
          aria-live="polite"
        >
          <strong>¡Bienvenido a Brasa Points!</strong>
          <br />
          <br />
          Tu registro ha sido exitoso. Recibirás un email de confirmación en
          los próximos minutos con los detalles de tu cuenta y cómo empezar a
          acumular puntos.
          <br />
          <br />
          ¡Ya puedes disfrutar de tus beneficios en cualquiera de nuestras 14
          ubicaciones!
        </div>
      ) : null}

      <form className="mt-6 space-y-6" noValidate onSubmit={handleSubmit}>
        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-2 text-base font-bold text-zinc-900">Datos personales</legend>

          <div className="sm:col-span-2">
            <label htmlFor="fullName" className="mb-1 block text-sm font-semibold text-zinc-800">
              Nombre completo *
            </label>
            <input
              id="fullName"
              name="fullName"
              type="text"
              required
              autoComplete="name"
              value={form.fullName}
              onChange={(event) => setForm((previous) => ({ ...previous, fullName: event.target.value }))}
              onBlur={(event) => validateField("fullName", event.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700"
              aria-describedby="fullNameError"
              aria-invalid={Boolean(errors.fullName)}
            />
            <p id="fullNameError" className="mt-1 text-sm text-red-700" aria-live="polite">
              {errors.fullName}
            </p>
          </div>

          <div>
            <label htmlFor="email" className="mb-1 block text-sm font-semibold text-zinc-800">
              Email *
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="email"
              value={form.email}
              onChange={(event) => setForm((previous) => ({ ...previous, email: event.target.value }))}
              onBlur={(event) => validateField("email", event.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700"
              aria-describedby="emailError"
              aria-invalid={Boolean(errors.email)}
            />
            <p id="emailError" className="mt-1 text-sm text-red-700" aria-live="polite">
              {errors.email}
            </p>
          </div>

          <div>
            <label htmlFor="phone" className="mb-1 block text-sm font-semibold text-zinc-800">
              Teléfono *
            </label>
            <input
              id="phone"
              name="phone"
              type="tel"
              required
              autoComplete="tel"
              placeholder="+57 300 123 4567"
              value={form.phone}
              onChange={(event) => setForm((previous) => ({ ...previous, phone: event.target.value }))}
              onBlur={(event) => validateField("phone", event.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700"
              aria-describedby="phoneError"
              aria-invalid={Boolean(errors.phone)}
            />
            <p id="phoneError" className="mt-1 text-sm text-red-700" aria-live="polite">
              {errors.phone}
            </p>
          </div>

          <div>
            <label htmlFor="birthDate" className="mb-1 block text-sm font-semibold text-zinc-800">
              Fecha de nacimiento *
            </label>
            <input
              id="birthDate"
              name="birthDate"
              type="date"
              required
              value={form.birthDate}
              onChange={(event) => setForm((previous) => ({ ...previous, birthDate: event.target.value }))}
              onBlur={(event) => validateField("birthDate", event.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700"
              aria-describedby="birthDateError"
              aria-invalid={Boolean(errors.birthDate)}
            />
            <p id="birthDateError" className="mt-1 text-sm text-red-700" aria-live="polite">
              {errors.birthDate}
            </p>
          </div>
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-2 text-base font-bold text-zinc-900">Ubicación y preferencia</legend>

          <div>
            <label htmlFor="country" className="mb-1 block text-sm font-semibold text-zinc-800">
              País *
            </label>
            <select
              id="country"
              name="country"
              required
              value={form.country}
              onChange={(event) => handleCountryChange(event.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700"
              aria-describedby="countryError"
              aria-invalid={Boolean(errors.country)}
            >
              <option value="">Selecciona una opción</option>
              <option value="Colombia">Colombia</option>
              <option value="Estados Unidos">Estados Unidos</option>
            </select>
            <p id="countryError" className="mt-1 text-sm text-red-700" aria-live="polite">
              {errors.country}
            </p>
          </div>

          <div>
            <label htmlFor="city" className="mb-1 block text-sm font-semibold text-zinc-800">
              Ciudad *
            </label>
            <select
              id="city"
              name="city"
              required
              disabled={cityOptions.length === 0}
              value={form.city}
              onChange={(event) => handleCityChange(event.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700 disabled:bg-zinc-100"
              aria-describedby="cityError"
              aria-invalid={Boolean(errors.city)}
            >
              <option value="">
                {cityOptions.length ? "Selecciona una ciudad" : "Selecciona primero el país"}
              </option>
              {cityOptions.map((city) => (
                <option key={city} value={city}>
                  {city}
                </option>
              ))}
            </select>
            <p id="cityError" className="mt-1 text-sm text-red-700" aria-live="polite">
              {errors.city}
            </p>
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="favoriteLocation" className="mb-1 block text-sm font-semibold text-zinc-800">
              Ubicación favorita de Brasaland
            </label>
            <select
              id="favoriteLocation"
              name="favoriteLocation"
              disabled={locationOptions.length === 0}
              value={form.favoriteLocation}
              onChange={(event) => setForm((previous) => ({ ...previous, favoriteLocation: event.target.value }))}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700 disabled:bg-zinc-100"
            >
              <option value="">
                {locationOptions.length ? "Selecciona una ubicación" : "Selecciona país y ciudad primero"}
              </option>
              {locationOptions.map((location) => (
                <option key={location} value={location}>
                  {location}
                </option>
              ))}
            </select>
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-2 text-base font-bold text-zinc-900">Preferencias alimentarias (opcional)</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {dietaryPreferenceOptions.map((preference) => (
              <label key={preference} className="inline-flex items-center gap-2 text-sm text-zinc-700">
                <input
                  type="checkbox"
                  checked={form.preferences.includes(preference)}
                  onChange={() => togglePreference(preference)}
                  className="h-4 w-4 rounded border-zinc-300 text-red-700 focus:ring-red-700"
                />
                {preference}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="grid gap-4">
          <legend className="mb-2 text-base font-bold text-zinc-900">Programa y contacto</legend>

          <div>
            <label htmlFor="source" className="mb-1 block text-sm font-semibold text-zinc-800">
              ¿Cómo nos conociste? *
            </label>
            <select
              id="source"
              name="source"
              required
              value={form.source}
              onChange={(event) => {
                const value = event.target.value as HowDidYouHearAboutUs | "";
                setForm((previous) => ({ ...previous, source: value }));
                validateField("source", value);
              }}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-red-700 focus:ring-2 focus:ring-red-700"
              aria-describedby="sourceError"
              aria-invalid={Boolean(errors.source)}
            >
              <option value="">Selecciona una opción</option>
              {sourceOptions.map((source) => (
                <option key={source} value={source}>
                  {source}
                </option>
              ))}
            </select>
            <p id="sourceError" className="mt-1 text-sm text-red-700" aria-live="polite">
              {errors.source}
            </p>
          </div>

          <label className="inline-flex items-start gap-3 text-sm text-zinc-700">
            <input
              id="terms"
              name="terms"
              type="checkbox"
              required
              checked={form.acceptedTerms}
              onChange={(event) => {
                setForm((previous) => ({ ...previous, acceptedTerms: event.target.checked }));
                validateField("terms", event.target.checked);
              }}
              className="mt-0.5 h-4 w-4 rounded border-zinc-300 text-red-700 focus:ring-red-700"
              aria-describedby="termsError"
            />
            <span>Acepto términos del programa *</span>
          </label>
          <p id="termsError" className="-mt-2 text-sm text-red-700" aria-live="polite">
            {errors.terms}
          </p>

          <label className="inline-flex items-start gap-3 text-sm text-zinc-700">
            <input
              id="offers"
              name="offers"
              type="checkbox"
              checked={form.wantsOffers}
              onChange={(event) => setForm((previous) => ({ ...previous, wantsOffers: event.target.checked }))}
              className="mt-0.5 h-4 w-4 rounded border-zinc-300 text-red-700 focus:ring-red-700"
            />
            <span>Quiero recibir ofertas por email</span>
          </label>
        </fieldset>

        <div className="flex flex-col gap-3 sm:flex-row">
          <button
            type="submit"
            className="inline-flex items-center justify-center rounded-lg bg-red-700 px-5 py-3 text-sm font-bold text-white transition hover:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-800"
          >
            Enviar registro
          </button>
          <button
            type="button"
            onClick={() => {
              setForm(initialState);
              setErrors({});
              setSubmitted(false);
            }}
            className="inline-flex items-center justify-center rounded-lg border border-zinc-400 px-5 py-3 text-sm font-bold text-zinc-800 transition hover:bg-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-500"
          >
            Limpiar formulario
          </button>
        </div>
      </form>
    </>
  );
}
