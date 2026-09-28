import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

const ACCESS_TOKEN_STORAGE_KEY = 'savoya:access-token:v1';
const IS_WEB = Platform.OS === 'web';

let accessToken: string | null = null;
let restorePromise: Promise<string | null> | null = null;
let tokenGeneration = 0;
let writeQueue: Promise<void> = Promise.resolve();

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
    return window.localStorage;
  } catch {
    return null;
  }
};

const getLegacyWebStorage = (): Storage | null => {
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
  const generation = ++tokenGeneration;
  accessToken = normalized;
  restorePromise = null;

  const webStorage = getWebStorage();
  if (webStorage) {
    try {
      if (normalized) {
        webStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, normalized);
      } else {
        webStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
        getLegacyWebStorage()?.removeItem(ACCESS_TOKEN_STORAGE_KEY);
      }
      return;
    } catch {
      // Fall back to in-memory token.
      return;
    }
  }

  writeQueue = writeQueue.catch(() => {}).then(async () => {
    if (generation !== tokenGeneration) return;
    try {
      if (normalized) await AsyncStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, normalized);
      else await AsyncStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    } catch {
      // Keep the in-memory token even if persistent storage is unavailable.
    }
  });
  await writeQueue;
};

export const restoreAccessToken = async (): Promise<string | null> => {
  if (accessToken !== null) {
    return accessToken;
  }

  if (!restorePromise) {
    const generation = tokenGeneration;
    restorePromise = (async () => {
      const webStorage = getWebStorage();
      if (webStorage) {
        try {
          accessToken = normalizeToken(webStorage.getItem(ACCESS_TOKEN_STORAGE_KEY));
          if (!accessToken) {
            const legacyToken = normalizeToken(getLegacyWebStorage()?.getItem(ACCESS_TOKEN_STORAGE_KEY));
            if (legacyToken) {
              accessToken = legacyToken;
              webStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, legacyToken);
            }
          }
        } catch {
          accessToken = null;
        }
        return accessToken;
      }

      try {
        // A logout write may still be waiting for native storage. Read only
        // after it finishes, and never install a result from an older session.
        await writeQueue;
        if (generation !== tokenGeneration) return accessToken;
        const restored = normalizeToken(await AsyncStorage.getItem(ACCESS_TOKEN_STORAGE_KEY));
        if (generation === tokenGeneration) accessToken = restored;
      } catch {
        if (generation === tokenGeneration) accessToken = null;
      }
      return accessToken;
    })();
  }

  const pending = restorePromise;
  try {
    return await pending;
  } finally {
    if (restorePromise === pending) restorePromise = null;
  }
};

export const getAccessToken = (): string | null => accessToken;
