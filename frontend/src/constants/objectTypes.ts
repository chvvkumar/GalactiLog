export const DEEP_SKY_TYPES = [
  "Emission Nebula",
  "Reflection Nebula",
  "Dark Nebula",
  "Planetary Nebula",
  "Supernova Remnant",
  "Galaxy",
  "Open Cluster",
  "Globular Cluster",
  "Star",
] as const;

export const SOLAR_SYSTEM_TYPES = [
  "Planet",
  "Moon",
  "Sun",
  "Comet",
  "Asteroid",
] as const;

export const OBJECT_TYPE_OPTIONS: string[] = [
  ...DEEP_SKY_TYPES,
  ...SOLAR_SYSTEM_TYPES,
  "Other",
];

export const isSolarSystemType = (t: string | null | undefined): boolean =>
  !!t && (SOLAR_SYSTEM_TYPES as readonly string[]).includes(t);
