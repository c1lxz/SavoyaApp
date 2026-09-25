import React from 'react';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useIsFocused } from '@react-navigation/native';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BottomDock } from '@/components/BottomDock';
import { PasswordChangePromptModal } from '@/components/PasswordChangePromptModal';
import { MainTabParamList, RootStackParamList } from '@/navigation/types';
import { MyPassesScreen } from '@/screens/MyPassesScreen';
import { NewsScreen } from '@/screens/NewsScreen';
import { OpenBarrierScreen } from '@/screens/OpenBarrierScreen';
import { WicketsScreen } from '@/screens/WicketsScreen';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';

const Tabs = createBottomTabNavigator<MainTabParamList>();
type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;

export const HomeScreen = ({ navigation }: Props) => {
  const focused = useIsFocused();
  const user = useAuthStore((state) => state.user);
  const error = useAuthStore((state) => state.error);
  const shouldPromptPasswordChange = useAuthStore((state) => state.shouldPromptPasswordChange);
  const passwordChangeState = useAuthStore((state) => state.passwordChangeState);
  const changePassword = useAuthStore((state) => state.changePassword);
  const dismissPasswordChangePrompt = useAuthStore((state) => state.dismissPasswordChangePrompt);

  return (
    <View style={styles.root}>
      <SafeAreaView edges={['top', 'left', 'right']} style={styles.toolbarSafeArea}>
        <View style={styles.toolbar}>
          <View style={styles.brand}>
            <MaterialCommunityIcons name="pine-tree" size={22} color={theme.colors.textPrimary} />
            <Text style={styles.brandName}>САВОЯ</Text>
          </View>
          <View style={styles.actions}>
            {user?.isAdmin ? (
              <Pressable
                onPress={() => navigation.navigate('Admin')}
                accessibilityRole="button"
                accessibilityLabel="Панель председателя"
                style={({ pressed }) => [styles.toolbarButton, pressed && styles.pressed]}
              >
                <MaterialCommunityIcons name="shield-account-outline" size={23} color={theme.colors.textSecondary} />
              </Pressable>
            ) : null}
            <Pressable
              onPress={() => navigation.navigate('Account')}
              accessibilityRole="button"
              accessibilityLabel="Мой аккаунт"
              style={({ pressed }) => [styles.toolbarButton, pressed && styles.pressed]}
            >
              <MaterialCommunityIcons name="account-circle-outline" size={25} color={theme.colors.textSecondary} />
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
      <Tabs.Navigator
        initialRouteName="News"
        backBehavior="history"
        tabBar={(props) => <BottomDock {...props} />}
        screenOptions={{ headerShown: false, lazy: true, tabBarHideOnKeyboard: true }}
        sceneContainerStyle={styles.scene}
      >
        <Tabs.Screen name="OpenBarrier" component={OpenBarrierScreen} options={{ title: 'Шлагбаумы' }} />
        <Tabs.Screen name="Wickets" component={WicketsScreen} options={{ title: 'Калитки' }} />
        <Tabs.Screen name="MyPasses" component={MyPassesScreen} options={{ title: user?.isAdmin ? 'Пропуски' : 'Мои пропуска' }} />
        <Tabs.Screen name="News" component={NewsScreen} options={{ title: 'Новости' }} />
      </Tabs.Navigator>
      <PasswordChangePromptModal
        visible={focused && shouldPromptPasswordChange}
        loading={passwordChangeState === 'loading'}
        error={passwordChangeState === 'error' ? error : null}
        onSubmit={async (newPassword, repeatPassword) => {
          await changePassword({ newPassword, repeatPassword });
        }}
        onDismiss={dismissPasswordChangePrompt}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.colors.screenBackground },
  scene: { backgroundColor: theme.colors.screenBackground },
  toolbarSafeArea: { backgroundColor: '#101F18' },
  toolbar: {
    width: '100%',
    maxWidth: 1060,
    alignSelf: 'center',
    paddingHorizontal: 16,
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  brandName: { color: theme.colors.textPrimary, fontSize: 14, fontWeight: '600', letterSpacing: 3 },
  actions: { flexDirection: 'row', gap: 4 },
  toolbarButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22 },
  pressed: { backgroundColor: theme.colors.cardStrong },
});
