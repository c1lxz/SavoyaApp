import React from 'react';
import { Image, StyleSheet, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { PasswordChangePromptModal } from '@/components/PasswordChangePromptModal';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;

const LOGO_IMAGE = require('../../assets/home-logo-reference.png');
const LOGO_IMAGE_RATIO = 711 / 586;
const HOME_ACTIONS = [
  { key: 'CreatePass', title: 'Создать пропуск', route: 'CreatePass' as const },
  { key: 'OpenBarrier', title: 'Открыть шлагбаум', route: 'OpenBarrier' as const },
  { key: 'Wickets', title: 'Калитки', route: 'Wickets' as const },
  { key: 'MyPasses', title: 'Мои пропуски', route: 'MyPasses' as const },
] as const;

export const HomeScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const metrics = getLayoutMetrics(width, height);
  const logout = useAuthStore((state) => state.logout);
  const error = useAuthStore((state) => state.error);
  const shouldPromptPasswordChange = useAuthStore((state) => state.shouldPromptPasswordChange);
  const passwordChangeState = useAuthStore((state) => state.passwordChangeState);
  const changePassword = useAuthStore((state) => state.changePassword);
  const dismissPasswordChangePrompt = useAuthStore((state) => state.dismissPasswordChangePrompt);

  const shellPaddingTop = metrics.isHandset ? (metrics.isCompactHeight ? 4 : 10) : metrics.isCompactHeight ? 8 : 16;
  const shellPaddingBottom = metrics.isHandset ? (metrics.isCompactHeight ? 8 : 12) : metrics.isCompactHeight ? 12 : 20;
  const pageGap = metrics.isHandset ? (metrics.isShortHeight ? 4 : metrics.isCompactHeight ? 6 : 10) : metrics.panelGap + 2;
  const actionGap = metrics.isHandset ? (metrics.isShortHeight ? 6 : metrics.isCompactHeight ? 8 : 10) : metrics.panelGap;
  const pagePaddingTop = metrics.isHandset ? (metrics.isShortHeight ? 2 : metrics.isCompactHeight ? 4 : 10) : metrics.isCompactHeight ? 2 : 12;
  const pagePaddingBottom = metrics.isHandset
    ? metrics.isShortHeight
      ? 6
      : metrics.isCompactHeight
        ? 8
        : 12
    : metrics.isCompactHeight
      ? 4
      : 12;
  const buttonMinHeight = metrics.isHandset ? (metrics.isShortHeight ? 42 : metrics.isCompactHeight ? 46 : 50) : metrics.buttonMinHeight;
  const buttonLabelFontSize = metrics.isHandset ? (metrics.isShortHeight ? 15 : 16) : metrics.isCompactHeight ? 17 : 18;
  const availableHeight =
    height - insets.top - insets.bottom - shellPaddingTop - shellPaddingBottom - pagePaddingTop - pagePaddingBottom;
  const buttonsHeight = (HOME_ACTIONS.length + 1) * buttonMinHeight + HOME_ACTIONS.length * actionGap;
  const defaultLogoHeight = metrics.isDesktop ? 248 : metrics.isTablet ? 220 : metrics.isCompactHeight ? 118 : 144;
  const minLogoHeight = metrics.isHandset ? (metrics.isShortHeight ? 72 : metrics.isCompactHeight ? 84 : 96) : 120;
  const logoHeight = Math.max(minLogoHeight, Math.min(defaultLogoHeight, availableHeight - buttonsHeight - pageGap));
  const logoWidth = Math.min(metrics.heroLogoWidth, width - metrics.horizontalPadding * 2, logoHeight * LOGO_IMAGE_RATIO);

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View
          style={[
            styles.page,
            {
              gap: pageGap,
              paddingTop: pagePaddingTop,
              paddingBottom: pagePaddingBottom,
            },
          ]}
        >
          <View style={styles.logoBlock}>
            <Image
              source={LOGO_IMAGE}
              style={[
                styles.logoImage,
                {
                  width: logoWidth,
                  height: logoHeight,
                },
              ]}
              resizeMode="contain"
            />
          </View>

          <View style={[styles.actions, { maxWidth: metrics.formMaxWidth, gap: actionGap }]}>
            {HOME_ACTIONS.map((item) => (
              <AppButton
                key={item.key}
                title={item.title}
                onPress={() => navigation.push(item.route)}
                minHeight={buttonMinHeight}
                labelFontSize={buttonLabelFontSize}
              />
            ))}
            <AppButton
              title="Выход"
              onPress={() => void logout()}
              minHeight={buttonMinHeight}
              labelFontSize={buttonLabelFontSize}
            />
          </View>
        </View>

        <PasswordChangePromptModal
          visible={shouldPromptPasswordChange}
          loading={passwordChangeState === 'loading'}
          error={passwordChangeState === 'error' ? error : null}
          onSubmit={async (newPassword, repeatPassword) => {
            await changePassword({ newPassword, repeatPassword });
          }}
          onDismiss={dismissPasswordChangePrompt}
        />
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  page: {
    flex: 1,
    width: '100%',
    alignItems: 'center',
    justifyContent: 'flex-start',
  },
  logoBlock: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'flex-start',
    flexShrink: 1,
  },
  logoImage: {
    alignSelf: 'center',
    aspectRatio: LOGO_IMAGE_RATIO,
  },
  actions: {
    width: '100%',
    alignSelf: 'center',
    flexShrink: 0,
  },
});
