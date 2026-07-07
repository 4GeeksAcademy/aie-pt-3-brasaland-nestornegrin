import { aggregateNumbers, binarySearch, countRegistrationsByCountry, countRegistrationsBySource, filterRegistrationsByCriteria, linearSearch, sortByMultiple, validateRegistration, } from './index';
const registrations = [
    {
        id: 1,
        fullName: 'Ana Gómez',
        email: 'ana@brasaland.com',
        phone: '+57 300 123 4567',
        country: 'Colombia',
        city: 'Medellín',
        favoriteLocation: 'Brasaland El Poblado',
        dietaryPreferences: ['Sin gluten'],
        source: 'Recomendación',
        birthDate: '1990-05-10',
        acceptedTerms: true,
        wantsOffers: true,
    },
    {
        id: 2,
        fullName: 'Luis Pérez',
        email: 'luis@example.com',
        phone: '+1 305 123 4567',
        country: 'Estados Unidos',
        city: 'Miami',
        favoriteLocation: 'Brasaland Brickell',
        dietaryPreferences: ['Vegetariano'],
        source: 'Redes sociales',
        birthDate: '2001-02-15',
        acceptedTerms: true,
        wantsOffers: false,
    },
    {
        id: 3,
        fullName: 'Camila Torres',
        email: 'camila@domain.org',
        phone: '+57 310 456 7890',
        country: 'Colombia',
        city: 'Bogotá',
        favoriteLocation: 'Brasaland Chapinero',
        dietaryPreferences: ['Sin restricciones'],
        source: 'Pasando por el local',
        birthDate: '2005-11-20',
        acceptedTerms: false,
        wantsOffers: true,
    },
];
const filteredRegistrations = filterRegistrationsByCriteria(registrations, { country: 'Colombia' });
const orderedRegistrations = sortByMultiple(registrations, [
    { key: 'country', direction: 'asc' },
    { key: 'fullName', direction: 'asc' },
]);
const searchResult = linearSearch(registrations.map((registration) => registration.email), 'luis@example.com');
const binaryResult = binarySearch([10, 20, 30, 40, 50], 30);
const stats = aggregateNumbers([10, 20, 30, 40]);
const countryCounts = countRegistrationsByCountry(registrations);
const sourceCounts = countRegistrationsBySource(registrations);
const validationResult = validateRegistration(registrations[0]);
const demoResults = {
    filteredCount: filteredRegistrations.length,
    sortedNames: orderedRegistrations.map((registration) => registration.fullName),
    linearSearchIndex: searchResult,
    binarySearchIndex: binaryResult,
    stats,
    countryCounts,
    sourceCounts,
    validationResult,
};
const output = document.getElementById('demo-output');
function renderResult(value) {
    if (output) {
        output.textContent = JSON.stringify(value, null, 2);
    }
}
renderResult(demoResults);
const filterButton = document.getElementById('filter-button');
const sortButton = document.getElementById('sort-button');
const searchButton = document.getElementById('search-button');
const validateButton = document.getElementById('validate-button');
if (filterButton) {
    filterButton.addEventListener('click', () => {
        renderResult(filterRegistrationsByCriteria(registrations, { country: 'Colombia' }));
    });
}
if (sortButton) {
    sortButton.addEventListener('click', () => {
        renderResult(sortByMultiple(registrations, [{ key: 'fullName', direction: 'asc' }]));
    });
}
if (searchButton) {
    searchButton.addEventListener('click', () => {
        renderResult({
            index: linearSearch(registrations.map((registration) => registration.email), 'luis@example.com'),
            found: linearSearch(registrations.map((registration) => registration.email), 'luis@example.com') >= 0,
        });
    });
}
if (validateButton) {
    validateButton.addEventListener('click', () => {
        renderResult(validateRegistration(registrations[0]));
    });
}
