import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { apiAdminService } from '@/services/api/apiAdminService';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import type { AdminUserItem, StaffRole } from '@/types';
import { goBackOrHome } from '@/utils/backNavigation';
import { getLayoutMetrics } from '@/utils/layout';
import { canManageStaff } from '@/utils/roles';

type Props = NativeStackScreenProps<RootStackParamList, 'AdminStaff'>;
type PendingChange = { user: AdminUserItem; role?: StaffRole; block?: boolean };
const roleLabel = (role?: StaffRole | null) => role === 'dispatcher' ? 'Диспетчер' : 'Администрация';

export const AdminStaffScreen = ({ navigation }: Props) => {
  const user = useAuthStore((state) => state.user);
  const allowed = canManageStaff(user);
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const [items, setItems] = useState<AdminUserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState<StaffRole>('dispatcher');
  const [created, setCreated] = useState<AdminUserItem | null>(null);
  const [revealedId, setRevealedId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingChange | null>(null);
  const mutation = useRef(false);
  const fetchId = useRef(0);

  const load = useCallback(async (offset = 0) => {
    if (!allowed) return;
    const id = ++fetchId.current;
    setLoading(true);
    try {
      const result = await apiAdminService.getUsers({ accountType: 'staff', limit: 50, offset });
      if (id !== fetchId.current) return;
      setItems((previous) => offset ? [...previous, ...result.items.filter((item) => !previous.some((p) => p.id === item.id))] : result.items);
      setTotal(result.total);
    } catch (e) {
      if (id === fetchId.current) setError(e instanceof Error ? e.message : 'Не удалось загрузить сотрудников');
    } finally {
      if (id === fetchId.current) setLoading(false);
    }
  }, [allowed]);

  useFocusEffect(useCallback(() => {
    void load();
    return () => { fetchId.current += 1; };
  }, [load]));

  const create = async () => {
    if (!allowed || mutation.current) return;
    if (name.trim().split(/\s+/).length < 2) {
      setError('Укажите имя и фамилию сотрудника');
      return;
    }
    mutation.current = true;
    setBusy(true); setError(null); setFeedback(null); setCreated(null);
    try {
      const result = await apiAdminService.createUser({ fullName: name.trim(), phoneNumber: phone.trim(), plotNumber: '', staffRole: role });
      setCreated(result); setName(''); setPhone(''); setFeedback('Сотрудник создан');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось создать сотрудника. Обновите список перед повторной попыткой.');
    } finally {
      mutation.current = false; setBusy(false);
    }
  };

  const applyChange = async () => {
    if (!allowed || !pending || mutation.current) return;
    mutation.current = true; setBusy(true); setError(null); setFeedback(null);
    try {
      if (pending.role) await apiAdminService.setStaffRole(pending.user.id, pending.role);
      else if (pending.block) await apiAdminService.blockUser(pending.user.id);
      else await apiAdminService.unblockUser(pending.user.id);
      setPending(null); setFeedback('Права сотрудника обновлены');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось изменить доступ');
    } finally {
      mutation.current = false; setBusy(false);
    }
  };

  if (!allowed) return <AppBackground><SafeAreaView style={styles.safe}><Text style={styles.body}>Управление сотрудниками доступно администрации.</Text></SafeAreaView></AppBackground>;

  return (
    <AppBackground>
      <SafeAreaView style={styles.safe}>
        <ScrollView contentContainerStyle={[styles.content, { maxWidth: metrics.formMaxWidth }]} keyboardShouldPersistTaps="handled">
          <ScreenHeader title="Сотрудники и роли" onBack={() => goBackOrHome(navigation, 'Admin')} />
          <View style={styles.card}>
            <Text style={styles.title}>Права доступа</Text>
            <Text style={styles.body}>Администрация регистрирует пользователей, публикует новости и управляет всеми разделами.</Text>
            <Text style={styles.body}>Диспетчеры работают с пропусками, мониторингом и доступом. Новости доступны им для чтения.</Text>
          </View>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {feedback ? <Text accessibilityLiveRegion="polite" style={styles.success}>{feedback}</Text> : null}
          <View style={styles.card}>
            <Text style={styles.title}>Добавить сотрудника</Text>
            <AppInput label="Имя и фамилия" accessibilityLabel="Имя и фамилия сотрудника" value={name} onChangeText={setName} editable={!busy} maxLength={100} />
            <AppInput label="Телефон (необязательно)" accessibilityLabel="Телефон сотрудника, необязательно" value={phone} onChangeText={setPhone} editable={!busy} keyboardType="phone-pad" maxLength={30} />
            <View style={styles.roles} accessibilityRole="radiogroup">
              {(['dispatcher', 'administration'] as const).map((value) => (
                <Pressable key={value} accessibilityRole="radio" accessibilityState={{ checked: role === value, disabled: busy }} disabled={busy} onPress={() => setRole(value)} style={[styles.choice, role === value && styles.selected]}>
                  <Text style={styles.body}>{roleLabel(value)}</Text>
                </Pressable>
              ))}
            </View>
            <AppButton title="Создать сотрудника" onPress={() => void create()} loading={busy} disabled={Boolean(pending)} />
          </View>
          {created ? <View style={styles.card}>
            <Text style={styles.title}>Данные для входа</Text>
            <Text selectable style={styles.body}>{created.fullName} · {roleLabel(created.staffRole)}</Text>
            <Text selectable style={styles.body}>Логин: {created.login}</Text>
            <Text selectable style={styles.body}>Временный пароль: {created.password || 'Недоступен'}</Text>
            <Text style={styles.muted}>Передайте данные сотруднику лично. Пароль можно изменить в аккаунте.</Text>
            <AppButton title="Скрыть данные" variant="card" onPress={() => setCreated(null)} />
          </View> : null}
          <View style={styles.heading}>
            <Text style={styles.title}>Сотрудники · {total}</Text>
            <Pressable accessibilityRole="button" disabled={loading || busy} onPress={() => { setError(null); void load(); }} style={styles.smallButton}><Text style={styles.body}>Обновить</Text></Pressable>
          </View>
          {pending ? <View style={[styles.card, styles.confirmation]} accessibilityRole="alert">
            <Text style={styles.title}>Изменить доступ?</Text>
            <Text style={styles.body}>{pending.user.fullName || pending.user.login}</Text>
            <Text style={styles.body}>{pending.role ? `Новая роль: ${roleLabel(pending.role)}` : pending.block ? 'Заблокировать вход в приложение' : 'Разрешить вход в приложение'}</Text>
            <AppButton title="Подтвердить изменение" loading={busy} onPress={() => void applyChange()} />
            <AppButton title="Отмена" disabled={busy} variant="card" onPress={() => setPending(null)} />
          </View> : null}
          {items.map((item) => <View key={item.id} style={styles.card}>
            <Text style={styles.title}>{item.fullName || item.login}{item.id === user?.id ? ' (вы)' : ''}</Text>
            <Text style={styles.body}>{roleLabel(item.staffRole)} · {item.isActive ? 'Активен' : 'Заблокирован'}</Text>
            <Text selectable style={styles.muted}>{item.login}{item.phone ? ` · ${item.phone}` : ''}</Text>
            {item.password ? <>
              <Pressable accessibilityRole="button" accessibilityState={{ expanded: revealedId === item.id }} style={styles.smallButton} onPress={() => setRevealedId(revealedId === item.id ? null : item.id)}>
                <Text style={styles.body}>{revealedId === item.id ? 'Скрыть данные для входа' : 'Показать данные для входа'}</Text>
              </Pressable>
              {revealedId === item.id ? <Text selectable style={styles.body}>Временный пароль: {item.password}</Text> : null}
            </> : null}
            {item.id !== user?.id ? <View style={styles.roles}>
              <Pressable accessibilityRole="button" disabled={busy || Boolean(pending)} style={styles.smallButton} onPress={() => setPending({ user: item, role: item.staffRole === 'dispatcher' ? 'administration' : 'dispatcher' })}>
                <Text style={styles.body}>{item.staffRole === 'dispatcher' ? 'Сделать администрацией' : 'Сделать диспетчером'}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" disabled={busy || Boolean(pending)} style={styles.smallButton} onPress={() => setPending({ user: item, block: item.isActive })}>
                <Text style={styles.body}>{item.isActive ? 'Заблокировать' : 'Разблокировать'}</Text>
              </Pressable>
            </View> : null}
          </View>)}
          {loading ? <ActivityIndicator color={theme.colors.textPrimary} accessibilityLabel="Загрузка сотрудников" /> : null}
          {!loading && !items.length ? <Text style={styles.muted}>Сотрудники не найдены</Text> : null}
          {items.length < total ? <AppButton title="Показать ещё" disabled={loading || busy} onPress={() => void load(items.length)} /> : null}
        </ScrollView>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { width: '100%', alignSelf: 'center', gap: 16, paddingBottom: 32 },
  card: { borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.cardStrong, padding: 18, gap: 14 },
  title: { fontSize: 19, fontWeight: '700', color: theme.colors.textPrimary, flexShrink: 1 },
  body: { color: theme.colors.textPrimary, fontSize: 16, lineHeight: 23, flexShrink: 1 },
  muted: { color: theme.colors.textSecondary, fontSize: 14, lineHeight: 21 },
  error: { color: theme.colors.danger, fontSize: 16, lineHeight: 23 },
  success: { color: theme.colors.success, fontSize: 16 },
  roles: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  choice: { flexGrow: 1, minHeight: 48, justifyContent: 'center', alignItems: 'center', padding: 12, borderRadius: 12, borderWidth: 1, borderColor: theme.colors.border },
  selected: { borderColor: theme.colors.success, backgroundColor: theme.colors.card },
  smallButton: { minHeight: 44, paddingVertical: 10, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: theme.colors.border, justifyContent: 'center', maxWidth: '100%' },
  heading: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  confirmation: { borderColor: theme.colors.success },
});
