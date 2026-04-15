import AsyncStorage from '@react-native-async-storage/async-storage';

export type LoggedOutRoute = 'Auth' | 'RegisterAccount';

const AUTH_ENTRY_STORAGE_KEY = 'savoya:auth-entry-seen:v1';

export const resolveInitialLoggedOutRoute = async (): Promise<LoggedOutRoute> => {
  try {
    const stored = await AsyncStorage.getItem(AUTH_ENTRY_STORAGE_KEY);
    if (stored === 'seen') {
      return 'Auth';
    }

    await AsyncStorage.setItem(AUTH_ENTRY_STORAGE_KEY, 'seen');
    return 'RegisterAccount';
  } catch {
    return 'Auth';
  }
};
