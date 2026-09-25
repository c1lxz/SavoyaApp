import React, { useEffect } from 'react';
import { AppState, Platform, StyleSheet } from 'react-native';
import { createNavigationContainerRef, DefaultTheme, NavigationContainer, type LinkingOptions } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { LoadingOverlay } from '@/components/LoadingOverlay';
import { AdminHomeScreen } from '@/screens/AdminHomeScreen';
import { AdminMonitorScreen } from '@/screens/AdminMonitorScreen';
import { AdminRequestsScreen } from '@/screens/AdminRequestsScreen';
import { AdminUsersScreen } from '@/screens/AdminUsersScreen';
import { AccountScreen } from '@/screens/AccountScreen';
import { AuthScreen } from '@/screens/AuthScreen';
import { CreatePassScreen } from '@/screens/CreatePassScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { NewsArchiveScreen } from '@/screens/NewsArchiveScreen';
import { NewsEditorScreen } from '@/screens/NewsEditorScreen';
import { ProfileSetupWebScreen } from '@/screens/ProfileSetupWebScreen';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { RootStackParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();
export const navigationRef = createNavigationContainerRef<RootStackParamList>();
const SESSION_VALIDATION_INTERVAL_MS = 5000;

const navigationTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: theme.colors.textPrimary,
    background: theme.colors.screenBackground,
    card: theme.colors.screenBackground,
    text: theme.colors.textPrimary,
    border: theme.colors.border,
    notification: theme.colors.success,
  },
};

const linking: LinkingOptions<RootStackParamList> = {
  prefixes: [],
  config: {
    initialRouteName: 'Home',
    screens: {
      Auth: 'auth',
      ProfileSetup: 'profile-setup',
      Admin: 'admin',
      AdminMonitor: 'admin/monitor',
      AdminRequests: 'admin/requests',
      AdminUsers: 'admin/users',
      Home: {
        path: '',
        initialRouteName: 'News',
        screens: {
          News: { path: '', parse: { postId: Number } },
          OpenBarrier: 'open-barrier',
          Wickets: 'wickets',
          MyPasses: 'my-passes',
        },
      },
      Account: 'account',
      CreatePass: 'create-pass',
      NewsArchive: 'news/archive',
      NewsEditor: { path: 'news/edit', parse: { postId: Number } },
    },
  },
};

export const RootNavigator = () => {
  const user = useAuthStore((state) => state.user);
  const userId = user?.id;
  const requiresProfileCompletion = useAuthStore((state) => state.requiresProfileCompletion);
  const restoreSession = useAuthStore((state) => state.restoreSession);
  const restoreState = useAuthStore((state) => state.restoreState);
  const validateSession = useAuthStore((state) => state.validateSession);

  useEffect(() => {
    if (restoreState === 'idle') {
      void restoreSession();
    }
  }, [restoreSession, restoreState]);

  useEffect(() => {
    if (!userId) {
      return undefined;
    }

    void validateSession();
    const intervalId = setInterval(() => {
      void validateSession();
    }, SESSION_VALIDATION_INTERVAL_MS);

    return () => {
      clearInterval(intervalId);
    };
  }, [userId, validateSession]);

  useEffect(() => {
    if (!userId) {
      return undefined;
    }

    const triggerValidation = () => {
      void validateSession();
    };

    if (Platform.OS === 'web') {
      const handleVisibilityChange = () => {
        if (typeof document !== 'undefined' && !document.hidden) {
          triggerValidation();
        }
      };

      if (typeof window !== 'undefined') {
        window.addEventListener('focus', triggerValidation);
      }
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', handleVisibilityChange);
      }

      return () => {
        if (typeof window !== 'undefined') {
          window.removeEventListener('focus', triggerValidation);
        }
        if (typeof document !== 'undefined') {
          document.removeEventListener('visibilitychange', handleVisibilityChange);
        }
      };
    }

    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState === 'active') {
        triggerValidation();
      }
    });

    return () => {
      subscription.remove();
    };
  }, [userId, validateSession]);

  if (restoreState === 'idle' || restoreState === 'loading') {
    return (
      <AppBackground>
        <SafeAreaView style={styles.loadingScreen}>
          <LoadingOverlay visible />
        </SafeAreaView>
      </AppBackground>
    );
  }

  const initialRouteName: keyof RootStackParamList = user
    ? !user.isAdmin && requiresProfileCompletion
      ? 'ProfileSetup'
      : 'Home'
    : 'Auth';

  return (
    <NavigationContainer ref={navigationRef} linking={linking} theme={navigationTheme}>
      <Stack.Navigator
        key={
          user
            ? user.isAdmin
              ? 'admin'
              : requiresProfileCompletion
                ? 'profile-setup'
                : 'resident'
            : 'guest'
        }
        initialRouteName={initialRouteName}
        screenOptions={{
          headerShown: false,
          animation: Platform.OS === 'ios' ? 'slide_from_right' : Platform.OS === 'web' ? 'none' : 'fade',
          gestureEnabled: Platform.OS === 'ios',
          fullScreenGestureEnabled: Platform.OS === 'ios',
        }}
      >
        {user ? (
          !user.isAdmin && requiresProfileCompletion ? (
            <Stack.Screen name="ProfileSetup" component={ProfileSetupWebScreen} />
          ) : (
            <>
              <Stack.Screen name="Home" component={HomeScreen} />
              <Stack.Screen name="Account" component={AccountScreen} />
              <Stack.Screen name="NewsArchive" component={NewsArchiveScreen} />
              {user.isAdmin ? (
                <>
                  <Stack.Screen name="Admin" component={AdminHomeScreen} />
                  <Stack.Screen name="AdminMonitor" component={AdminMonitorScreen} />
                  <Stack.Screen name="AdminRequests" component={AdminRequestsScreen} />
                  <Stack.Screen name="AdminUsers" component={AdminUsersScreen} />
                  <Stack.Screen name="NewsEditor" component={NewsEditorScreen} />
                </>
              ) : (
                <Stack.Screen name="CreatePass" component={CreatePassScreen} />
              )}
            </>
          )
        ) : (
          <Stack.Screen name="Auth" component={AuthScreen} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
};

const styles = StyleSheet.create({
  loadingScreen: {
    flex: 1,
  },
});
