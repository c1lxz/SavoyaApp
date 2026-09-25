import React from 'react';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';
import { goBackOrHome } from '@/utils/backNavigation';

type Props = NativeStackScreenProps<RootStackParamList, 'Admin'>;

export const AdminHomeScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const logout = useAuthStore((state) => state.logout);

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[
            styles.scrollContent,
            {
              maxWidth: metrics.formMaxWidth,
              gap: metrics.panelGap,
            },
          ]}
          showsVerticalScrollIndicator={false}
          bounces={false}
          alwaysBounceVertical={false}
          overScrollMode="never"
        >
          <ScreenHeader title="Управление" onBack={() => goBackOrHome(navigation)} />

          <View style={[styles.summaryCard, { gap: metrics.isDesktop ? 12 : 10 }]}>
            <Text style={[styles.summaryTitle, { fontSize: metrics.isDesktop ? 24 : 21 }]}>Панель председателя</Text>
            <Text style={styles.summaryText}>
              Новости посёлка, заявки жителей, пользователи и управление доступом.
            </Text>
          </View>

          <View style={[styles.actions, { gap: metrics.panelGap }]}>
            <AppButton
              title="Опубликовать новость"
              onPress={() => navigation.navigate('NewsEditor')}
              leftIcon={<MaterialCommunityIcons name="newspaper-plus" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Новости посёлка"
              onPress={() => navigation.navigate('Home', { screen: 'News' })}
              leftIcon={<MaterialCommunityIcons name="newspaper-variant-outline" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Мониторинг"
              onPress={() => navigation.push('AdminMonitor')}
              leftIcon={<MaterialCommunityIcons name="monitor-eye" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Пропуски"
              onPress={() => navigation.push('AdminRequests')}
              leftIcon={<MaterialCommunityIcons name="clipboard-text-outline" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Пользователи"
              onPress={() => navigation.push('AdminUsers')}
              leftIcon={<MaterialCommunityIcons name="account-multiple-outline" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Открыть шлагбаум"
              onPress={() => navigation.navigate('Home', { screen: 'OpenBarrier' })}
              leftIcon={<MaterialCommunityIcons name="gate-open" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Калитки"
              onPress={() => navigation.navigate('Home', { screen: 'Wickets' })}
              leftIcon={<MaterialCommunityIcons name="door" size={22} color={theme.colors.textPrimary} />}
            />
            <AppButton
              title="Выход"
              onPress={() => void logout()}
              variant="card"
              leftIcon={<MaterialCommunityIcons name="logout" size={22} color={theme.colors.textPrimary} />}
            />
          </View>
        </ScrollView>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  scroll: {
    flex: 1,
    width: '100%',
  },
  scrollContent: {
    flexGrow: 1,
    alignSelf: 'center',
    width: '100%',
    paddingBottom: theme.spacing.xl,
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
