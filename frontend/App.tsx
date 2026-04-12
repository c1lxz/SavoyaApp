import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { Platform } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { RootNavigator } from './src/navigation/RootNavigator';

const WEB_VIEWPORT_STYLE_ID = 'savoya-web-viewport-styles';
const WEB_VIEWPORT_META_ID = 'savoya-web-viewport-meta';
const WEB_VIEWPORT_BACKDROP = 'rgb(6, 12, 10)';

const ensureWebViewport = () => {
  if (Platform.OS !== 'web' || typeof document === 'undefined') {
    return;
  }

  let viewportMeta = document.getElementById(WEB_VIEWPORT_META_ID) as HTMLMetaElement | null;
  if (!viewportMeta) {
    viewportMeta = document.createElement('meta');
    viewportMeta.id = WEB_VIEWPORT_META_ID;
    viewportMeta.name = 'viewport';
    document.head.appendChild(viewportMeta);
  }
  viewportMeta.content = 'width=device-width, initial-scale=1, viewport-fit=cover';

  let styleTag = document.getElementById(WEB_VIEWPORT_STYLE_ID) as HTMLStyleElement | null;
  if (!styleTag) {
    styleTag = document.createElement('style');
    styleTag.id = WEB_VIEWPORT_STYLE_ID;
    document.head.appendChild(styleTag);
  }

  styleTag.textContent = `
    html, body {
      position: fixed;
      inset: 0;
      margin: 0;
      padding: 0;
      width: 100vw;
      height: 100dvh;
      overflow: hidden;
      overscroll-behavior: none;
      background: ${WEB_VIEWPORT_BACKDROP};
    }

    body {
      position: fixed;
      inset: 0;
      overscroll-behavior-x: none;
      overscroll-behavior-y: none;
      touch-action: manipulation;
    }

    #root,
    body > div:first-child {
      position: fixed;
      inset: 0;
      display: flex;
      width: 100%;
      height: 100dvh;
      min-height: 100dvh;
      max-height: 100dvh;
      max-width: 100%;
      overflow: hidden;
      overscroll-behavior: none;
      background: ${WEB_VIEWPORT_BACKDROP};
    }

    #root > div,
    body > div:first-child > div {
      flex: 1 1 auto;
      width: 100%;
      height: 100dvh;
      min-height: 100dvh;
      max-height: 100dvh;
      max-width: 100%;
      overflow: hidden;
      overscroll-behavior: none;
      background: ${WEB_VIEWPORT_BACKDROP};
    }
  `;
};

export default function App() {
  useEffect(() => {
    ensureWebViewport();
  }, []);

  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <RootNavigator />
    </SafeAreaProvider>
  );
}
