import * as ExpoLocation from 'expo-location';

export type SavedAreaKey = 'home' | 'work';

export interface SavedAreaContext {
  label: string;
  query: string;
  latitude?: number;
  longitude?: number;
}

export interface LiveLocationContext {
  mode: 'live';
  label: string;
  latitude: number;
  longitude: number;
  updatedAt: number;
}

export interface ManualAreaContext {
  mode: 'manual';
  label: string;
  query: string;
  latitude?: number;
  longitude?: number;
  updatedAt: number;
}

export type LocationContext = LiveLocationContext | ManualAreaContext;

export async function requestForegroundLocation() {
  const permission = await ExpoLocation.requestForegroundPermissionsAsync();
  if (permission.status !== 'granted') {
    return null;
  }
  return permission;
}

export async function getBestEffortLocationContext(): Promise<LocationContext | null> {
  const permission = await requestForegroundLocation();
  if (!permission) return null;

  const lastKnown = await ExpoLocation.getLastKnownPositionAsync();
  if (lastKnown?.coords) {
    return {
      mode: 'live',
      label: 'Current area',
      latitude: lastKnown.coords.latitude,
      longitude: lastKnown.coords.longitude,
      updatedAt: Date.now(),
    };
  }

  const current = await ExpoLocation.getCurrentPositionAsync({
    accuracy: ExpoLocation.Accuracy.Balanced,
  });

  return {
    mode: 'live',
    label: 'Current area',
    latitude: current.coords.latitude,
    longitude: current.coords.longitude,
    updatedAt: Date.now(),
  };
}

export function buildManualAreaContext(query: string): ManualAreaContext {
  const trimmed = query.trim();
  return {
    mode: 'manual',
    label: trimmed,
    query: trimmed,
    updatedAt: Date.now(),
  };
}

export function formatDistanceMiles(distanceMeters?: number | null) {
  if (distanceMeters == null) return null;
  const miles = distanceMeters / 1609.34;
  if (miles < 0.2) return '<0.2 mi';
  return `${miles.toFixed(miles < 10 ? 1 : 0)} mi`;
}
