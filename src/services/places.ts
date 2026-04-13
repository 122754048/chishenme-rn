import { backendApi, type NearbyRestaurant } from '../api/backend';

export interface NearbyDiscoveryInput {
  latitude?: number;
  longitude?: number;
  query?: string;
  radiusMeters?: number;
}

export async function fetchNearbyRestaurants(
  token: string,
  input: NearbyDiscoveryInput
): Promise<{ restaurants: NearbyRestaurant[]; source: 'google_places' | 'fallback' }> {
  if (typeof input.latitude === 'number' && typeof input.longitude === 'number') {
    return backendApi.searchNearbyRestaurants(token, {
      kind: 'coordinates',
      latitude: input.latitude,
      longitude: input.longitude,
      radiusMeters: input.radiusMeters,
    });
  }

  return backendApi.searchNearbyRestaurants(token, {
    kind: 'query',
    query: input.query?.trim() || 'current area',
  });
}
