import React, { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { AuthScreen } from '@/screens/AuthScreen';
import { CreatePassScreen } from '@/screens/CreatePassScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { MyPassesScreen } from '@/screens/MyPassesScreen';
import { OpenBarrierScreen } from '@/screens/OpenBarrierScreen';
import { WicketsScreen } from '@/screens/WicketsScreen';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { RootStackParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();

export const RootNavigator = () => {
  const user = useAuthStore((state) => state.user);
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
    <NavigationContainer>
      <Stack.Navigator
        initialRouteName={user ? 'Home' : 'Auth'}
        screenOptions={{ headerShown: false, animation: 'fade' }}
      >
        {user ? (
          <>
            <Stack.Screen name="Home" component={HomeScreen} />
            <Stack.Screen name="CreatePass" component={CreatePassScreen} />
            <Stack.Screen name="OpenBarrier" component={OpenBarrierScreen} />
            <Stack.Screen name="Wickets" component={WicketsScreen} />
            <Stack.Screen name="MyPasses" component={MyPassesScreen} />
          </>
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
