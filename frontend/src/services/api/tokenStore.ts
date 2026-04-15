import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

const ACCESS_TOKEN_STORAGE_KEY = 'savoya:access-token:v1';
const IS_WEB = Platform.OS === 'web';

let accessToken: string | null = null;
let restorePromise: Promise<string | null> | null = null;

const normalizeToken = (value: string | null | undefined): string | null => {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  return trimmed ? trimmed : null;
};

const getWebStorage = (): Storage | null => {
  if (!IS_WEB || typeof window === 'undefined') {
    return null;
  }

  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
};

export const setAccessToken = async (token: string | null): Promise<void> => {
  const normalized = normalizeToken(token);
  accessToken = normalized;

  const webStorage = getWebStorage();
  if (webStorage) {
    try {
      if (normalized) {
        webStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, normalized);
      } else {
        webStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
      }
      return;
    } catch {
      // Fall back to in-memory token.
      return;
    }
  }

  try {
    if (normalized) {
      await AsyncStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, normalized);
    } else {
      await AsyncStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    }
  } catch {
    // Keep the in-memory token even if persistent storage is unavailable.
  }
};

export const restoreAccessToken = async (): Promise<string | null> => {
  if (accessToken !== null) {
    return accessToken;
  }

  if (!restorePromise) {
    restorePromise = (async () => {
      const webStorage = getWebStorage();
      if (webStorage) {
        try {
          accessToken = normalizeToken(webStorage.getItem(ACCESS_TOKEN_STORAGE_KEY));
        } catch {
          accessToken = null;
        }
        return accessToken;
      }

      try {
        accessToken = normalizeToken(await AsyncStorage.getItem(ACCESS_TOKEN_STORAGE_KEY));
      } catch {
        accessToken = null;
      }
      return accessToken;
    })();
  }

  try {
    return await restorePromise;
  } finally {
    restorePromise = null;
  }
};

export const getAccessToken = (): string | null => accessToken;
