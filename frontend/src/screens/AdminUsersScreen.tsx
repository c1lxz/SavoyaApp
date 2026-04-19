import React, { useCallback, useDeferredValue, useEffect, useState } from 'react';
import { Alert, Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppInput } from '@/components/AppInput';
import { EmptyState } from '@/components/EmptyState';
import { LoadingOverlay } from '@/components/LoadingOverlay';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { apiAdminService } from '@/services/api/apiAdminService';
import { theme } from '@/theme';
import { AdminUserItem, RequestState } from '@/types';
import { goBackOrHome } from '@/utils/backNavigation';
import { formatDateTime } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'AdminUsers'>;

const USERS_REFRESH_MS = 15000;
const COLUMNS = {
  login: 190,
  password: 190,
  fullName: 240,
  phone: 170,
  plot: 110,
  status: 130,
  actions: 260,
} as const;

const TABLE_WIDTH = Object.values(COLUMNS).reduce((sum, width) => sum + width, 0);

const TableCell = ({
  width,
  children,
  header = false,
  alignStart = true,
}: {
  width: number;
  children: React.ReactNode;
  header?: boolean;
  alignStart?: boolean;
}) => (
  <View style={[styles.cell, { width }, !alignStart && styles.cellCentered]}>
    {typeof children === 'string' ? (
      <Text numberOfLines={2} style={header ? styles.headerCellText : styles.cellText}>
        {children}
      </Text>
    ) : (
      children
    )}
  </View>
);

const statusLabel = (item: AdminUserItem) => {
  if (!item.isActive) {
    return 'Заблокирован';
  }
  if (item.passwordChangeRequired) {
    return 'Активен\nСмена пароля';
  }
  return 'Активен';
};

const statusColor = (item: AdminUserItem) => (item.isActive ? theme.colors.success : theme.colors.danger);

const passwordLabel = (item: AdminUserItem) => {
  if (item.password) {
    return `${item.password}${item.passwordChangeRequired ? '\nНужно сменить' : ''}`;
  }
  return item.passwordChangeRequired ? 'Временный пароль недоступен' : 'Скрыт после смены';
};

const ActionButton = ({
  title,
  icon,
  onPress,
  danger = false,
}: {
  title: string;
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  onPress: () => void;
  danger?: boolean;
}) => (
  <Pressable style={[styles.actionButton, danger && styles.actionButtonDanger]} onPress={onPress}>
    <MaterialCommunityIcons name={icon} size={16} color={danger ? theme.colors.danger : theme.colors.textPrimary} />
    <Text style={[styles.actionButtonText, danger && styles.actionButtonTextDanger]}>{title}</Text>
  </Pressable>
);

const UsersTable = ({
  users,
  onBlockToggle,
  onDelete,
}: {
  users: AdminUserItem[];
  onBlockToggle: (item: AdminUserItem) => Promise<void>;
  onDelete: (item: AdminUserItem) => void;
}) => (
  <ScrollView horizontal showsHorizontalScrollIndicator>
    <View style={[styles.table, { width: TABLE_WIDTH }]}>
      <View style={[styles.tableRow, styles.tableHeader]}>
        <TableCell header width={COLUMNS.login}>Логин</TableCell>
        <TableCell header width={COLUMNS.password}>Пароль</TableCell>
        <TableCell header width={COLUMNS.fullName}>ФИО</TableCell>
        <TableCell header width={COLUMNS.phone}>Телефон</TableCell>
        <TableCell header width={COLUMNS.plot}>Участок</TableCell>
        <TableCell header width={COLUMNS.status}>Статус</TableCell>
        <TableCell header width={COLUMNS.actions}>Действия</TableCell>
      </View>

      {users.map((item, index) => (
        <View key={item.id} style={[styles.tableRow, index % 2 === 1 ? styles.tableRowAlt : null]}>
          <TableCell width={COLUMNS.login}>{item.login}</TableCell>
          <TableCell width={COLUMNS.password}>{passwordLabel(item)}</TableCell>
          <TableCell width={COLUMNS.fullName}>{item.fullName || '-'}</TableCell>
          <TableCell width={COLUMNS.phone}>{item.phone || '-'}</TableCell>
          <TableCell width={COLUMNS.plot}>{item.plotNumber || '-'}</TableCell>
          <TableCell width={COLUMNS.status}>
            <Text style={[styles.cellText, { color: statusColor(item) }]}>{statusLabel(item)}</Text>
          </TableCell>
          <TableCell width={COLUMNS.actions}>
            <View style={styles.actionsCell}>
              <ActionButton
                title={item.isActive ? 'Заблокировать' : 'Разблокировать'}
                icon={item.isActive ? 'lock-outline' : 'lock-open-outline'}
                onPress={() => void onBlockToggle(item)}
              />
              <ActionButton title="Удалить" icon="trash-can-outline" onPress={() => onDelete(item)} danger />
            </View>
          </TableCell>
        </View>
      ))}
    </View>
  </ScrollView>
);

export const AdminUsersScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const [users, setUsers] = useState<AdminUserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loadState, setLoadState] = useState<RequestState>('idle');
  const [actionState, setActionState] = useState<RequestState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [lastCreatedUser, setLastCreatedUser] = useState<AdminUserItem | null>(null);
  const [search, setSearch] = useState('');
  const [fullName, setFullName] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [plotNumber, setPlotNumber] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  const loadUsers = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoadState('loading');
    }
    setError(null);

    try {
      const result = await apiAdminService.getUsers({
        search: deferredSearch || undefined,
        limit: 250,
      });
      setUsers(result.items);
      setTotal(result.total);
      setLastUpdated(new Date().toISOString());
      setLoadState('success');
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : 'Не удалось загрузить пользователей';
      setError(message);
      setLoadState('error');
    }
  }, [deferredSearch]);

  useEffect(() => {
    void loadUsers(true);
    const intervalId = setInterval(() => {
      void loadUsers(false);
    }, USERS_REFRESH_MS);
    const unsubscribe = navigation.addListener('focus', () => {
      void loadUsers(false);
    });

    return () => {
      clearInterval(intervalId);
      unsubscribe();
    };
  }, [loadUsers, navigation]);

  useEffect(() => {
    if (!feedback) {
      return undefined;
    }

    const timeoutId = setTimeout(() => {
      setFeedback(null);
    }, 2500);

    return () => clearTimeout(timeoutId);
  }, [feedback]);

  const handleCreateUser = async () => {
    const normalizedFullName = fullName.trim();
    const normalizedPhoneNumber = phoneNumber.trim();
    const normalizedPlotNumber = plotNumber.trim();

    if (!normalizedFullName || normalizedFullName.split(/\s+/).filter(Boolean).length < 2) {
      setFormError('Укажите ФИО');
      return;
    }

    if (!normalizedPhoneNumber) {
      setFormError('Введите номер телефона');
      return;
    }

    if (!normalizedPlotNumber) {
      setFormError('Введите номер участка');
      return;
    }

    setFormError(null);
    setActionState('loading');
    setError(null);

    try {
      const createdUser = await apiAdminService.createUser({
        fullName: normalizedFullName,
        phoneNumber: normalizedPhoneNumber,
        plotNumber: normalizedPlotNumber,
      });
      setLastCreatedUser(createdUser);
      setFeedback(`Создан пользователь ${createdUser.login}`);
      setFullName('');
      setPhoneNumber('');
      setPlotNumber('');
      await loadUsers(false);
      setActionState('success');
    } catch (createError) {
      const message = createError instanceof Error ? createError.message : 'Не удалось создать пользователя';
      setError(message);
      setActionState('error');
    }
  };

  const handleBlockToggle = async (item: AdminUserItem) => {
    setActionState('loading');
    setError(null);

    try {
      if (item.isActive) {
        await apiAdminService.blockUser(item.id);
        setFeedback(`Пользователь ${item.login} заблокирован`);
      } else {
        await apiAdminService.unblockUser(item.id);
        setFeedback(`Пользователь ${item.login} разблокирован`);
      }
      await loadUsers(false);
      setActionState('success');
    } catch (actionError) {
      const message = actionError instanceof Error ? actionError.message : 'Не удалось обновить пользователя';
      setError(message);
      setActionState('error');
    }
  };

  const confirmDeleteUser = (item: AdminUserItem) => {
    const runDelete = async () => {
      setActionState('loading');
      setError(null);
      try {
        await apiAdminService.deleteUser(item.id);
        setFeedback(`Пользователь ${item.login} удалён`);
        if (lastCreatedUser?.id === item.id) {
          setLastCreatedUser(null);
        }
        await loadUsers(false);
        setActionState('success');
      } catch (deleteError) {
        const message = deleteError instanceof Error ? deleteError.message : 'Не удалось удалить пользователя';
        setError(message);
        setActionState('error');
      }
    };

    if (Platform.OS === 'web' && typeof globalThis.confirm === 'function') {
      if (globalThis.confirm(`Удалить пользователя?\n${item.fullName || item.login}\n${item.login}`)) {
        void runDelete();
      }
      return;
    }

    Alert.alert('Удалить пользователя?', `${item.fullName || item.login}\n${item.login}`, [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          void runDelete();
        },
      },
    ]);
  };

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View style={[styles.content, { maxWidth: metrics.isDesktop ? 1360 : metrics.contentMaxWidth }]}>
          <ScreenHeader title="Пользователи" onBack={() => goBackOrHome(navigation, 'Admin')} />

          <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
            <View style={styles.summaryCard}>
              <View style={styles.summaryTitleRow}>
                <MaterialCommunityIcons name="account-multiple-outline" size={24} color={theme.colors.textPrimary} />
                <Text style={[styles.summaryTitle, { fontSize: metrics.isDesktop ? 22 : 19 }]}>Пользователи в локальной БД</Text>
              </View>
              <Text style={styles.summaryText}>
                Здесь видны логины, текущие пароли, контактные данные и статус блокировки пользователей из SQLite.
              </Text>
              <View style={styles.summaryMetaRow}>
                <Text style={styles.summaryMeta}>Пользователей: {total}</Text>
                {lastUpdated ? <Text style={styles.summaryMeta}>Обновлено: {formatDateTime(lastUpdated)}</Text> : null}
              </View>
              {feedback ? <Text style={styles.feedbackText}>{feedback}</Text> : null}
              {error ? <Text style={styles.errorText}>{error}</Text> : null}
            </View>

            <View style={styles.createCard}>
              <Text style={styles.cardTitle}>Создать пользователя</Text>
              <View style={[styles.createGrid, metrics.isDesktop && styles.createGridDesktop]}>
                <View style={styles.createField}>
                  <AppInput
                    label="ФИО"
                    icon="account"
                    value={fullName}
                    onChangeText={setFullName}
                    autoCapitalize="words"
                    placeholder="Иванов Иван Иванович"
                  />
                </View>
                <View style={styles.createField}>
                  <AppInput
                    label="Телефон"
                    icon="phone"
                    value={phoneNumber}
                    onChangeText={setPhoneNumber}
                    keyboardType="phone-pad"
                    placeholder="+79991234567"
                  />
                </View>
                <View style={styles.createField}>
                  <AppInput
                    label="Участок"
                    icon="home"
                    value={plotNumber}
                    onChangeText={setPlotNumber}
                    keyboardType="number-pad"
                    placeholder="25"
                  />
                </View>
              </View>
              {formError ? <Text style={styles.errorText}>{formError}</Text> : null}
              <View style={styles.toolbarRow}>
                <Pressable style={styles.refreshButton} onPress={() => void loadUsers(true)}>
                  <Text style={styles.refreshButtonText}>Обновить</Text>
                </Pressable>
                <Pressable style={[styles.refreshButton, styles.createButton]} onPress={() => void handleCreateUser()}>
                  <Text style={styles.refreshButtonText}>{actionState === 'loading' ? 'Сохранение...' : 'Создать пользователя'}</Text>
                </Pressable>
              </View>
            </View>

            {lastCreatedUser ? (
              <View style={styles.credentialsCard}>
                <View style={styles.credentialsTitleRow}>
                  <MaterialCommunityIcons name="account-key-outline" size={22} color={theme.colors.textPrimary} />
                  <Text style={styles.cardTitle}>Последние созданные данные</Text>
                </View>
                <View style={[styles.credentialsGrid, metrics.isDesktop && styles.credentialsGridDesktop]}>
                  <View style={styles.credentialsField}>
                    <Text style={styles.credentialsLabel}>Логин</Text>
                    <Text style={styles.credentialsValue}>{lastCreatedUser.login}</Text>
                  </View>
                  <View style={styles.credentialsField}>
                    <Text style={styles.credentialsLabel}>Пароль</Text>
                    <Text style={styles.credentialsValue}>{lastCreatedUser.password ?? 'Недоступно'}</Text>
                  </View>
                  <View style={styles.credentialsField}>
                    <Text style={styles.credentialsLabel}>Участок</Text>
                    <Text style={styles.credentialsValue}>{lastCreatedUser.plotNumber || '-'}</Text>
                  </View>
                </View>
              </View>
            ) : null}

            <View style={styles.searchCard}>
              <AppInput
                label="Поиск"
                icon="magnify"
                value={search}
                onChangeText={setSearch}
                autoCapitalize="none"
                placeholder="Логин, ФИО, телефон или участок"
              />
            </View>

            {users.length > 0 ? (
              <UsersTable users={users} onBlockToggle={handleBlockToggle} onDelete={confirmDeleteUser} />
            ) : loadState === 'loading' ? null : (
              <EmptyState text="Пользователи не найдены" />
            )}
          </ScrollView>

          <LoadingOverlay visible={loadState === 'loading' || actionState === 'loading'} />
        </View>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  content: {
    flex: 1,
    width: '100%',
    alignSelf: 'center',
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: theme.spacing.xl,
    gap: theme.spacing.md,
  },
  summaryCard: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
    padding: theme.spacing.lg,
    gap: 10,
  },
  summaryTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
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
  summaryMetaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: theme.spacing.md,
  },
  summaryMeta: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  feedbackText: {
    color: theme.colors.success,
    fontSize: 15,
    fontWeight: '600',
  },
  errorText: {
    color: theme.colors.danger,
    fontSize: 15,
  },
  createCard: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    padding: theme.spacing.lg,
    gap: theme.spacing.md,
  },
  cardTitle: {
    color: theme.colors.textPrimary,
    fontSize: 18,
    fontWeight: '700',
  },
  createGrid: {
    gap: theme.spacing.md,
  },
  createGridDesktop: {
    flexDirection: 'row',
  },
  createField: {
    flex: 1,
  },
  searchCard: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    padding: theme.spacing.lg,
  },
  credentialsCard: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
    padding: theme.spacing.lg,
    gap: theme.spacing.md,
  },
  credentialsTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  credentialsGrid: {
    gap: theme.spacing.md,
  },
  credentialsGridDesktop: {
    flexDirection: 'row',
  },
  credentialsField: {
    flex: 1,
    gap: 6,
  },
  credentialsLabel: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  credentialsValue: {
    color: theme.colors.textPrimary,
    fontSize: 18,
    fontWeight: '700',
  },
  toolbarRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: theme.spacing.sm,
  },
  refreshButton: {
    minHeight: 42,
    justifyContent: 'center',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 18,
    backgroundColor: theme.colors.cardStrong,
  },
  createButton: {
    backgroundColor: 'rgba(47, 77, 61, 0.92)',
  },
  refreshButtonText: {
    color: theme.colors.textPrimary,
    fontSize: 15,
    fontWeight: '700',
  },
  table: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 8,
    overflow: 'hidden',
    backgroundColor: theme.colors.card,
  },
  tableRow: {
    minHeight: 56,
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(219, 193, 134, 0.22)',
  },
  tableHeader: {
    minHeight: 44,
    backgroundColor: theme.colors.cardStrong,
  },
  tableRowAlt: {
    backgroundColor: 'rgba(255, 255, 255, 0.035)',
  },
  cell: {
    justifyContent: 'center',
    borderRightWidth: 1,
    borderRightColor: 'rgba(219, 193, 134, 0.2)',
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  cellCentered: {
    alignItems: 'center',
  },
  headerCellText: {
    color: theme.colors.textPrimary,
    fontSize: 13,
    fontWeight: '700',
  },
  cellText: {
    color: theme.colors.textSecondary,
    fontSize: 14,
    lineHeight: 18,
  },
  actionsCell: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  actionButton: {
    minHeight: 34,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
    paddingHorizontal: 10,
  },
  actionButtonDanger: {
    backgroundColor: 'rgba(88, 41, 41, 0.32)',
    borderColor: 'rgba(225, 132, 132, 0.45)',
  },
  actionButtonText: {
    color: theme.colors.textPrimary,
    fontSize: 13,
    fontWeight: '700',
  },
  actionButtonTextDanger: {
    color: theme.colors.danger,
  },
});
