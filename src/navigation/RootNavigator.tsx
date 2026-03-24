import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { AuthScreen } from '@/screens/AuthScreen';
import { CreatePassScreen } from '@/screens/CreatePassScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { MyPassesScreen } from '@/screens/MyPassesScreen';
import { OpenBarrierScreen } from '@/screens/OpenBarrierScreen';
import { WicketsScreen } from '@/screens/WicketsScreen';
import { RootStackParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();

export const RootNavigator = () => {
  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Auth" screenOptions={{ headerShown: false, animation: 'fade' }}>
        <Stack.Screen name="Auth" component={AuthScreen} />
        <Stack.Screen name="Home" component={HomeScreen} />
        <Stack.Screen name="CreatePass" component={CreatePassScreen} />
        <Stack.Screen name="OpenBarrier" component={OpenBarrierScreen} />
        <Stack.Screen name="Wickets" component={WicketsScreen} />
        <Stack.Screen name="MyPasses" component={MyPassesScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
};

