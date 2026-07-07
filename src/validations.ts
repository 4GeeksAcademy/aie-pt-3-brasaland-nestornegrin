import type { BrasaPointsRegistration, Country, HowDidYouHearAboutUs } from './types/models';

export const brasaPointsErrorMessages = {
  fullName: 'Ingresa tu nombre completo (nombre y apellido)',
  email: 'Ingresa un email válido (ejemplo: <nombre@correo.com>)',
  phone: 'El teléfono debe incluir código de país (ejemplo: +57 300 123 4567 o +1 305 123 4567)',
  country: 'Selecciona tu país',
  city: 'Selecciona tu ciudad',
  source: 'Cuéntanos cómo conociste Brasaland',
  birthDate: 'Debes ser mayor de 18 años para registrarte en Brasa Points',
  terms: 'Debes aceptar los términos del programa Brasa Points para continuar',
} as const;

export function isValidFullName(value: string): boolean {
  const parts = value.trim().split(/\s+/).filter(Boolean);
  return parts.length >= 2;
}

export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

export function isValidPhone(value: string, country: Country): boolean {
  const trimmed = value.trim();

  if (!/^\+(57|1)\s?[0-9\s-]{7,}$/.test(trimmed)) {
    return false;
  }

  if (country === 'Colombia') {
    return trimmed.startsWith('+57');
  }

  return trimmed.startsWith('+1');
}

export function isAdult(birthDate: string): boolean {
  if (!birthDate) {
    return false;
  }

  const parsedDate = new Date(birthDate);
  if (Number.isNaN(parsedDate.getTime())) {
    return false;
  }

  const today = new Date();
  let age = today.getFullYear() - parsedDate.getFullYear();
  const monthDifference = today.getMonth() - parsedDate.getMonth();

  if (monthDifference < 0 || (monthDifference === 0 && today.getDate() < parsedDate.getDate())) {
    age -= 1;
  }

  return age >= 18;
}

export function isValidCountry(value: string): value is Country {
  return value === 'Colombia' || value === 'Estados Unidos';
}

export function isValidSource(value: string): value is HowDidYouHearAboutUs {
  return [
    'Redes sociales',
    'Recomendación',
    'Pasando por el local',
    'Búsqueda en internet',
    'Otro',
  ].includes(value);
}

export function validateRegistration(registration: BrasaPointsRegistration): { isValid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (!isValidFullName(registration.fullName)) {
    errors.push(brasaPointsErrorMessages.fullName);
  }

  if (!isValidEmail(registration.email)) {
    errors.push(brasaPointsErrorMessages.email);
  }

  if (!isValidPhone(registration.phone, registration.country)) {
    errors.push(brasaPointsErrorMessages.phone);
  }

  if (!isValidCountry(registration.country)) {
    errors.push(brasaPointsErrorMessages.country);
  }

  if (!registration.city) {
    errors.push(brasaPointsErrorMessages.city);
  }

  if (!isValidSource(registration.source)) {
    errors.push(brasaPointsErrorMessages.source);
  }

  if (!isAdult(registration.birthDate)) {
    errors.push(brasaPointsErrorMessages.birthDate);
  }

  if (!registration.acceptedTerms) {
    errors.push(brasaPointsErrorMessages.terms);
  }

  return {
    isValid: errors.length === 0,
    errors,
  };
}
