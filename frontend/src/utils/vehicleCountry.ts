const RUSSIAN_PLATE_RE = /^[ABEKMHOPCTYXАВЕКМНОРСТУХ]\d{3}[ABEKMHOPCTYXАВЕКМНОРСТУХ]{2}\d{2,3}$/;
const KAZAKHSTAN_PLATE_RE = /^\d{3}[A-ZА-Я]{3}\d{2}$/;

export const detectVehicleCountry = (value?: string | null): string | null => {
  const normalized = (value ?? '').toUpperCase().replace(/[\s-]+/g, '');
  if (!normalized) {
    return null;
  }

  if (RUSSIAN_PLATE_RE.test(normalized)) {
    return 'Россия';
  }

  if (KAZAKHSTAN_PLATE_RE.test(normalized)) {
    return 'Казахстан';
  }

  return null;
};

export const formatVehicleLabel = (value?: string | null, explicitCountryLabel?: string | null): string => {
  const normalizedValue = (value ?? '').trim().toUpperCase();
  if (!normalizedValue) {
    return '';
  }

  const countryLabel = explicitCountryLabel ?? detectVehicleCountry(normalizedValue);
  return countryLabel ? `${normalizedValue} (${countryLabel})` : normalizedValue;
};
