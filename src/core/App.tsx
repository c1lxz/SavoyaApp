import React from 'react';
import { StatusBar } from 'expo-status-bar';

import { RootNavigator } from '@/navigation/RootNavigator';

export const App = () => {
  return (
    <>
      <StatusBar style="light" />
      <RootNavigator />
    </>
  );
};

