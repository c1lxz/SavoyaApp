import React, { useEffect } from 'react';
import { ActivityIndicator, Platform, StyleSheet, View } from 'react-native';
import { DefaultTheme, NavigationContainer, type LinkingOptions } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

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
  const restoreState = useAuthStore((state) => state.restoreState);
  const restoreSession = useAuthStore((state) => state.restoreSession);

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  if (restoreState === 'idle' || restoreState === 'loading') {
    return (
      <View style={styles.bootstrap}>
        <ActivityIndicator size="large" color={theme.colors.textPrimary} />
      </View>
    );
  }

  return (
    <NavigationContainer linking={linking} theme={navigationTheme}>
      <Stack.Navigator
        initialRouteName={user ? (requiresProfileCompletion ? 'ProfileSetup' : 'Home') : 'Auth'}
        screenOptions={{
          headerShown: false,
          animation: Platform.OS === 'ios' ? 'slide_from_right' : Platform.OS === 'web' ? 'none' : 'fade',
          gestureEnabled: Platform.OS === 'ios',
          fullScreenGestureEnabled: Platform.OS === 'ios',
        }}
      >
        {user ? (
          requiresProfileCompletion ? (
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
  bootstrap: {
    flex: 1,
    backgroundColor: theme.colors.screenBackground,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
