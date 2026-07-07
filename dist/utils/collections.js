export function filterRegistrationsByCriteria(registrations, criteria) {
    return registrations.filter((registration) => {
        return Object.entries(criteria).every(([field, value]) => {
            if (value === undefined) {
                return true;
            }
            return registration[field] === value;
        });
    });
}
export function filterLocationsByCriteria(locations, criteria) {
    return locations.filter((location) => {
        return Object.entries(criteria).every(([field, value]) => {
            if (value === undefined) {
                return true;
            }
            return location[field] === value;
        });
    });
}
export function sortBy(items, key, direction = 'asc') {
    return [...items].sort((leftItem, rightItem) => {
        const leftValue = leftItem[key];
        const rightValue = rightItem[key];
        if (typeof leftValue === 'number' && typeof rightValue === 'number') {
            return direction === 'asc' ? leftValue - rightValue : rightValue - leftValue;
        }
        const leftText = String(leftValue).toLowerCase();
        const rightText = String(rightValue).toLowerCase();
        if (leftText < rightText) {
            return direction === 'asc' ? -1 : 1;
        }
        if (leftText > rightText) {
            return direction === 'asc' ? 1 : -1;
        }
        return 0;
    });
}
export function sortByMultiple(items, sortDefinitions) {
    return [...items].sort((leftItem, rightItem) => {
        for (const definition of sortDefinitions) {
            const leftValue = leftItem[definition.key];
            const rightValue = rightItem[definition.key];
            if (leftValue === rightValue) {
                continue;
            }
            if (typeof leftValue === 'number' && typeof rightValue === 'number') {
                return definition.direction === 'asc' ? leftValue - rightValue : rightValue - leftValue;
            }
            const leftText = String(leftValue).toLowerCase();
            const rightText = String(rightValue).toLowerCase();
            if (leftText < rightText) {
                return definition.direction === 'asc' ? -1 : 1;
            }
            return definition.direction === 'asc' ? 1 : -1;
        }
        return 0;
    });
}
export function aggregateNumbers(values) {
    if (values.length === 0) {
        return { total: 0, average: 0, min: 0, max: 0 };
    }
    const total = values.reduce((sum, value) => sum + value, 0);
    return {
        total,
        average: total / values.length,
        min: Math.min(...values),
        max: Math.max(...values),
    };
}
export function countRegistrationsByCountry(registrations) {
    return registrations.reduce((summary, registration) => {
        summary[registration.country] += 1;
        return summary;
    }, { Colombia: 0, 'Estados Unidos': 0 });
}
export function countRegistrationsBySource(registrations) {
    return registrations.reduce((summary, registration) => {
        summary[registration.source] = (summary[registration.source] ?? 0) + 1;
        return summary;
    }, {});
}
