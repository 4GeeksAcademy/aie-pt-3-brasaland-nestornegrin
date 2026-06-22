const cityOptionsByCountry = {
  Colombia: ["Medellín", "Bogotá", "Cali"],
  "Estados Unidos": ["Miami", "Orlando"],
};

const locationsByCountryAndCity = {
  Colombia: {
    "Medellín": ["Brasaland El Poblado", "Brasaland Laureles", "Brasaland Envigado", "Brasaland Sabaneta"],
    "Bogotá": ["Brasaland Usaquén", "Brasaland Chapinero", "Brasaland Zona Rosa"],
    Cali: ["Brasaland Granada", "Brasaland Ciudad Jardín", "Brasaland Unicentro"],
  },
  "Estados Unidos": {
    Miami: ["Brasaland Brickell", "Brasaland Coral Gables"],
    Orlando: ["Brasaland Downtown", "Brasaland International Drive"],
  },
};

const errorMessages = {
  fullName: "Ingresa tu nombre completo (nombre y apellido)",
  email: "Ingresa un email válido (ejemplo: <nombre@correo.com>)",
  phone: "El teléfono debe incluir código de país (ejemplo: +57 300 123 4567 o +1 305 123 4567)",
  country: "Selecciona tu país",
  city: "Selecciona tu ciudad",
  source: "Cuéntanos cómo conociste Brasaland",
  birthDate: "Debes ser mayor de 18 años para registrarte en Brasa Points",
  terms: "Debes aceptar los términos del programa Brasa Points para continuar",
};

const form = document.querySelector("#applicationForm");
const successMessage = document.querySelector("#successMessage");

const fields = {
  fullName: document.querySelector("#fullName"),
  email: document.querySelector("#email"),
  phone: document.querySelector("#phone"),
  country: document.querySelector("#country"),
  city: document.querySelector("#city"),
  favoriteLocation: document.querySelector("#favoriteLocation"),
  source: document.querySelector("#source"),
  birthDate: document.querySelector("#birthDate"),
  terms: document.querySelector("#terms"),
};

function setError(inputEl, message) {
  const errorEl = document.querySelector(`#${inputEl.id}Error`);
  if (!errorEl) return;

  errorEl.textContent = message;
  inputEl.setAttribute("aria-invalid", "true");
  inputEl.classList.remove("border-zinc-300", "border-emerald-500");
  inputEl.classList.add("border-red-600");
}

function clearError(inputEl) {
  const errorEl = document.querySelector(`#${inputEl.id}Error`);
  if (!errorEl) return;

  errorEl.textContent = "";
  inputEl.removeAttribute("aria-invalid");
  inputEl.classList.remove("border-red-600");
  inputEl.classList.add("border-emerald-500");
}

function clearSuccess() {
  successMessage.classList.add("hidden");
  successMessage.textContent = "";
}

function fullNameIsValid(value) {
  const parts = value.trim().split(/\s+/).filter(Boolean);
  return parts.length >= 2;
}

function emailIsValid(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function phoneIsValid(value) {
  const country = fields.country.value;
  const trimmed = value.trim();

  if (!/^\+(57|1)\s?[0-9\s-]{7,}$/.test(trimmed)) {
    return false;
  }

  if (country === "Colombia") {
    return trimmed.startsWith("+57");
  }
  if (country === "Estados Unidos") {
    return trimmed.startsWith("+1");
  }

  return true;
}

function isAdult(dateStr) {
  if (!dateStr) return false;

  const birthDate = new Date(dateStr);
  if (Number.isNaN(birthDate.getTime())) return false;

  const today = new Date();
  let age = today.getFullYear() - birthDate.getFullYear();
  const monthDiff = today.getMonth() - birthDate.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
    age -= 1;
  }
  return age >= 18;
}

function validateField(fieldName) {
  const input = fields[fieldName];
  if (!input) return true;

  let isValid = true;

  if (fieldName === "fullName") {
    isValid = fullNameIsValid(input.value);
  }
  if (fieldName === "email") {
    isValid = emailIsValid(input.value);
  }
  if (fieldName === "phone") {
    isValid = phoneIsValid(input.value);
  }
  if (fieldName === "country") {
    isValid = input.value.trim() !== "";
  }
  if (fieldName === "city") {
    isValid = input.value.trim() !== "";
  }
  if (fieldName === "source") {
    isValid = input.value.trim() !== "";
  }
  if (fieldName === "birthDate") {
    isValid = isAdult(input.value);
  }
  if (fieldName === "terms") {
    isValid = input.checked;
  }

  if (!isValid) {
    setError(input, errorMessages[fieldName]);
    return false;
  }

  clearError(input);
  return true;
}

function fillSelect(selectEl, options, placeholder) {
  selectEl.innerHTML = "";
  const first = document.createElement("option");
  first.value = "";
  first.textContent = placeholder;
  selectEl.appendChild(first);

  options.forEach((optionValue) => {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = optionValue;
    selectEl.appendChild(option);
  });
}

function updateCitiesByCountry() {
  const country = fields.country.value;
  const cities = cityOptionsByCountry[country] || [];

  fields.city.disabled = cities.length === 0;
  fillSelect(fields.city, cities, cities.length ? "Selecciona una ciudad" : "Selecciona primero el país");

  fields.favoriteLocation.disabled = true;
  fillSelect(fields.favoriteLocation, [], "Selecciona país y ciudad primero");

  validateField("country");
  if (fields.city.value === "") {
    setError(fields.city, errorMessages.city);
  }
}

function updateLocationsByCountryAndCity() {
  const country = fields.country.value;
  const city = fields.city.value;
  const options = (locationsByCountryAndCity[country] && locationsByCountryAndCity[country][city]) || [];

  fields.favoriteLocation.disabled = options.length === 0;
  fillSelect(fields.favoriteLocation, options, options.length ? "Selecciona una ubicación" : "Selecciona país y ciudad primero");

  validateField("city");
}

function clearVisualStates() {
  Object.values(fields).forEach((fieldEl) => {
    fieldEl.classList.remove("border-red-600", "border-emerald-500");
    if (fieldEl.classList.contains("border-zinc-300") === false) {
      fieldEl.classList.add("border-zinc-300");
    }
    fieldEl.removeAttribute("aria-invalid");
  });
}

function clearErrors() {
  Object.values(fields).forEach((fieldEl) => {
    const errorEl = document.querySelector(`#${fieldEl.id}Error`);
    if (errorEl) errorEl.textContent = "";
  });
}

function validateAllRequiredFields() {
  const requiredFields = ["fullName", "email", "phone", "country", "city", "source", "birthDate", "terms"];
  const results = requiredFields.map((name) => validateField(name));
  return results.every(Boolean);
}

fields.country.addEventListener("change", () => {
  clearSuccess();
  updateCitiesByCountry();
});

fields.city.addEventListener("change", () => {
  clearSuccess();
  updateLocationsByCountryAndCity();
});

["fullName", "email", "phone", "birthDate", "country", "city", "source"].forEach((name) => {
  fields[name].addEventListener("input", () => {
    clearSuccess();
    validateField(name);
  });
  fields[name].addEventListener("blur", () => {
    clearSuccess();
    validateField(name);
  });
});

fields.terms.addEventListener("change", () => {
  clearSuccess();
  validateField("terms");
});

form.addEventListener("submit", (event) => {
  clearSuccess();
  const isValid = validateAllRequiredFields();
  if (!isValid) {
    event.preventDefault();
    return;
  }

  event.preventDefault();
  successMessage.innerHTML =
    "<strong>¡Bienvenido a Brasa Points!</strong><br><br>Tu registro ha sido exitoso. Recibirás un email de confirmación en los próximos minutos con los detalles de tu cuenta y cómo empezar a acumular puntos.<br><br>¡Ya puedes disfrutar de tus beneficios en cualquiera de nuestras 14 ubicaciones!";
  successMessage.classList.remove("hidden");
  form.reset();
  updateCitiesByCountry();
  clearErrors();
  clearVisualStates();
});

form.addEventListener("reset", () => {
  clearSuccess();
  window.setTimeout(() => {
    updateCitiesByCountry();
    clearErrors();
    clearVisualStates();
  }, 0);
});

updateCitiesByCountry();