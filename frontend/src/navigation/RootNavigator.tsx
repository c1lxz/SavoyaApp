import React, { useEffect } from 'react';
import { AppState, Platform, StyleSheet } from 'react-native';
import { DefaultTheme, NavigationContainer, type LinkingOptions } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { LoadingOverlay } from '@/components/LoadingOverlay';
import { AdminHomeScreen } from '@/screens/AdminHomeScreen';
import { AdminMonitorScreen } from '@/screens/AdminMonitorScreen';
import { AdminRequestsScreen } from '@/screens/AdminRequestsScreen';
import { AdminUsersScreen } from '@/screens/AdminUsersScreen';
import { AuthScreen } from '@/screens/AuthScreen';
import { CreatePassScreen } from '@/screens/CreatePassScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { MyPassesScreen } from '@/screens/MyPassesScreen';
import { OpenBarrierScreen } from '@/screens/OpenBarrierScreen';
import { ProfileSetupWebScreen } from '@/screens/ProfileSetupWebScreen';
import { WicketsScreen } from '@/screens/WicketsScreen';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { RootStackParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();
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
    screens: {
      Auth: 'auth',
      ProfileSetup: 'profile-setup',
      Admin: 'admin',
      AdminMonitor: 'admin/monitor',
      AdminRequests: 'admin/requests',
      AdminUsers: 'admin/users',
      Home: '',
      CreatePass: 'create-pass',
      OpenBarrier: 'open-barrier',
      Wickets: 'wickets',
      MyPasses: 'my-passes',
    },
  },
};

export const RootNavigator = () => {
  const user = useAuthStore((state) => state.user);
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
    if (!user) {
      return undefined;
    }

    void validateSession();
    const intervalId = setInterval(() => {
      void validateSession();
    }, SESSION_VALIDATION_INTERVAL_MS);

    return () => {
      clearInterval(intervalId);
    };
  }, [user, validateSession]);

  useEffect(() => {
    if (!user) {
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
  }, [user, validateSession]);

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
    ? user.isAdmin
      ? 'Admin'
      : requiresProfileCompletion
        ? 'ProfileSetup'
        : 'Home'
    : 'Auth';

  return (
    <NavigationContainer linking={linking} theme={navigationTheme}>
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
          user.isAdmin ? (
            <>
              <Stack.Screen name="Admin" component={AdminHomeScreen} />
              <Stack.Screen name="AdminMonitor" component={AdminMonitorScreen} />
              <Stack.Screen name="AdminRequests" component={AdminRequestsScreen} />
              <Stack.Screen name="AdminUsers" component={AdminUsersScreen} />
              <Stack.Screen name="OpenBarrier" component={OpenBarrierScreen} />
              <Stack.Screen name="Wickets" component={WicketsScreen} />
            </>
          ) : requiresProfileCompletion ? (
            <Stack.Screen name="ProfileSetup" component={ProfileSetupWebScreen} />
          ) : (
            <>
              <Stack.Screen name="Home" component={HomeScreen} />
              <Stack.Screen name="CreatePass" component={CreatePassScreen} />
              <Stack.Screen name="OpenBarrier" component={OpenBarrierScreen} />
              <Stack.Screen name="Wickets" component={WicketsScreen} />
              <Stack.Screen name="MyPasses" component={MyPassesScreen} />
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
