import type { AggregationSummary, BrasaPointsRegistration, Country, RestaurantLocation } from '../types/models';

export function filterRegistrationsByCriteria(
  registrations: BrasaPointsRegistration[],
  criteria: Partial<Pick<BrasaPointsRegistration, 'country' | 'city' | 'source' | 'acceptedTerms' | 'wantsOffers'>>,
): BrasaPointsRegistration[] {
  return registrations.filter((registration) => {
    return Object.entries(criteria).every(([field, value]) => {
      if (value === undefined) {
        return true;
      }

      return registration[field as keyof BrasaPointsRegistration] === value;
    });
  });
}

export function filterLocationsByCriteria(
  locations: RestaurantLocation[],
  criteria: Partial<Pick<RestaurantLocation, 'country' | 'city'>>,
): RestaurantLocation[] {
  return locations.filter((location) => {
    return Object.entries(criteria).every(([field, value]) => {
      if (value === undefined) {
        return true;
      }

      return location[field as keyof RestaurantLocation] === value;
    });
  });
}

export function sortBy<T>(items: T[], key: keyof T, direction: 'asc' | 'desc' = 'asc'): T[] {
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

export function sortByMultiple<T>(items: T[], sortDefinitions: Array<{ key: keyof T; direction: 'asc' | 'desc' }>): T[] {
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

export function aggregateNumbers(values: number[]): AggregationSummary {
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

export function countRegistrationsByCountry(registrations: BrasaPointsRegistration[]): Record<Country, number> {
  return registrations.reduce<Record<Country, number>>(
    (summary, registration) => {
      summary[registration.country] += 1;
      return summary;
    },
    { Colombia: 0, 'Estados Unidos': 0 },
  );
}

export function countRegistrationsBySource(registrations: BrasaPointsRegistration[]): Record<string, number> {
  return registrations.reduce<Record<string, number>>((summary, registration) => {
    summary[registration.source] = (summary[registration.source] ?? 0) + 1;
    return summary;
  }, {});
}
