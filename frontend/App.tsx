import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { Platform } from 'react-native';

import { RootNavigator } from './src/navigation/RootNavigator';
import { theme } from './src/theme';

const WEB_VIEWPORT_STYLE_ID = 'savoya-web-viewport-styles';
const WEB_VIEWPORT_META_ID = 'savoya-web-viewport-meta';

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
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: ${theme.colors.screenBackground};
    }

    body {
      overscroll-behavior-x: none;
      overscroll-behavior-y: none;
    }

    #root,
    body > div:first-child {
      width: 100%;
      min-height: 100dvh;
      max-width: 100vw;
      overflow: hidden;
      background: ${theme.colors.screenBackground};
    }

    #root > div,
    body > div:first-child > div {
      width: 100%;
      min-height: 100dvh;
      max-width: 100vw;
      overflow-x: hidden;
      background: ${theme.colors.screenBackground};
    }
  `;
};

export default function App() {
  useEffect(() => {
    ensureWebViewport();
  }, []);

  return (
    <>
      <StatusBar style="light" />
      <RootNavigator />
    </>
  );
}
