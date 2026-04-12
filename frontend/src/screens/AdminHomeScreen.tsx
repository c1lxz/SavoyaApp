import React from 'react';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'Admin'>;

export const AdminHomeScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const logout = useAuthStore((state) => state.logout);

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View style={[styles.page, { maxWidth: metrics.formMaxWidth, gap: metrics.panelGap }]}>
          <ScreenHeader title="Админка" />

          <View style={[styles.summaryCard, { gap: metrics.isDesktop ? 12 : 10 }]}>
            <Text style={[styles.summaryTitle, { fontSize: metrics.isDesktop ? 24 : 21 }]}>Управление доступом</Text>
            <Text style={styles.summaryText}>
              Админу доступны просмотр заявок и открытие точек доступа. Создание пропусков и список личных пропусков
              здесь скрыты.
            </Text>
          </View>

          <View style={[styles.actions, { gap: metrics.panelGap }]}>
            <AppButton
              title="Пропуски"
              onPress={() => navigation.push('AdminRequests')}
              leftIcon={<MaterialCommunityIcons name="clipboard-text-outline" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Открыть шлагбаум"
              onPress={() => navigation.push('OpenBarrier')}
              leftIcon={<MaterialCommunityIcons name="gate-open" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Калитки"
              onPress={() => navigation.push('Wickets')}
              leftIcon={<MaterialCommunityIcons name="door" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Выйти"
              onPress={() => void logout()}
              variant="card"
              leftIcon={<MaterialCommunityIcons name="logout" size={22} color={theme.colors.textPrimary} />}
            />
          </View>
        </View>
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
    alignSelf: 'center',
  },
  summaryCard: {
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
    padding: theme.spacing.lg,
  },
  summaryTitle: {
    color: theme.colors.textPrimary,
    fontWeight: '700',
  },
  summaryText: {
    color: theme.colors.textSecondary,
    fontSize: 16,
    lineHeight: 24,
  },
  actions: {
    width: '100%',
  },
});
