import React, { useState } from 'react';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { NotificationSettings } from '@/components/NotificationSettings';
import { PasswordChangePromptModal } from '@/components/PasswordChangePromptModal';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { goBackOrHome } from '@/utils/backNavigation';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'Account'>;

export const AccountScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const [changePasswordVisible, setChangePasswordVisible] = useState(false);
  const [passwordChanged, setPasswordChanged] = useState(false);
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const logoutState = useAuthStore((state) => state.logoutState);
  const changePassword = useAuthStore((state) => state.changePassword);
  const passwordChangeState = useAuthStore((state) => state.passwordChangeState);
  const error = useAuthStore((state) => state.error);

  return (
    <AppBackground>
      <SafeAreaView style={styles.screen}>
        <ScrollView
          contentContainerStyle={[styles.content, { maxWidth: metrics.formMaxWidth }]}
          keyboardShouldPersistTaps="handled"
        >
          <ScreenHeader title="Мой аккаунт" onBack={() => goBackOrHome(navigation)} />
          <View style={styles.card}>
            <MaterialCommunityIcons name="account-circle-outline" size={40} color={theme.colors.textPrimary} />
            <Text style={styles.name}>{user?.fullName || user?.login}</Text>
            {user?.plotNumber ? <Text style={styles.description}>Участок {user.plotNumber}</Text> : null}
            {user?.isAdmin ? <Text style={styles.description}>Председатель</Text> : null}
          </View>
          <NotificationSettings />
          {user?.isAdmin ? (
            <AppButton title="Панель председателя" onPress={() => navigation.navigate('Admin')} />
          ) : null}
          <AppButton
            title="Сменить пароль"
            onPress={() => { setPasswordChanged(false); setChangePasswordVisible(true); }}
            leftIcon={<MaterialCommunityIcons name="lock-outline" size={22} color={theme.colors.textPrimary} />}
          />
          {passwordChanged ? <Text style={styles.success}>Пароль изменён</Text> : null}
          <AppButton
            title="Выйти из аккаунта"
            onPress={() => void logout()}
            loading={logoutState === 'loading'}
            variant="card"
            leftIcon={<MaterialCommunityIcons name="logout" size={22} color={theme.colors.textPrimary} />}
          />
          {logoutState === 'error' && error ? <Text style={styles.error}>{error}</Text> : null}
        </ScrollView>
        <PasswordChangePromptModal
          mode="settings"
          visible={changePasswordVisible}
          loading={passwordChangeState === 'loading'}
          error={passwordChangeState === 'error' ? error : null}
          onSubmit={async (newPassword, repeatPassword) => {
            if (await changePassword({ newPassword, repeatPassword })) {
              setChangePasswordVisible(false);
              setPasswordChanged(true);
            }
          }}
          onDismiss={() => setChangePasswordVisible(false)}
        />
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { width: '100%', alignSelf: 'center', gap: 16, paddingBottom: 24 },
  card: { alignItems: 'center', gap: 10, padding: 24, borderRadius: theme.radius.md, backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border },
  name: { color: theme.colors.textPrimary, fontSize: 22, fontWeight: '600', textAlign: 'center' },
  description: { color: theme.colors.textSecondary, fontSize: 16 },
  success: { color: theme.colors.success, textAlign: 'center' },
  error: { color: theme.colors.danger, textAlign: 'center' },
});
