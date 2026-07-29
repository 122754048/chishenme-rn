import {createHash} from 'node:crypto';

const canonicalValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map(canonicalValue);
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonicalValue(child)]),
    );
  }
  return value;
};

export const canonicalJson = (value: unknown): string => JSON.stringify(canonicalValue(value));

export const canonicalSha256 = (value: unknown): string =>
  createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex');

export const bytesSha256 = (value: Uint8Array): string =>
  createHash('sha256').update(value).digest('hex');
