import React, { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AdminRequestCard } from '@/components/AdminRequestCard';
import { AppInput } from '@/components/AppInput';
import { EmptyState } from '@/components/EmptyState';
import { LoadingOverlay } from '@/components/LoadingOverlay';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { apiAdminService } from '@/services/api/apiAdminService';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { AdminRequestItem, AdminRequestStatus, RequestState } from '@/types';
import { formatRequestForCopy } from '@/utils/adminRequests';
import { goBackOrHome } from '@/utils/backNavigation';
import { copyToClipboard } from '@/utils/clipboard';
import { formatDateTime } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'AdminRequests'>;
type StatusFilter = AdminRequestStatus | 'all';
type KeyTypeFilter = 'VehicleNumber' | 'Phone' | 'all';

const STATUS_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: 'Все' },
  { value: 'active', label: 'Активные' },
  { value: 'permanent', label: 'Постоянные' },
  { value: 'expired', label: 'Истекшие' },
  { value: 'completed', label: 'Завершённые' },
  { value: 'cancelled', label: 'Отменённые' },
];

const KEY_TYPE_OPTIONS: Array<{ value: KeyTypeFilter; label: string }> = [
  { value: 'all', label: 'Все типы' },
  { value: 'VehicleNumber', label: 'Номер ТС' },
  { value: 'Phone', label: 'Телефон' },
];

const REQUESTS_REFRESH_MS = 30000;

const FilterChip = ({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) => (
  <Pressable style={[styles.filterChip, active && styles.filterChipActive]} onPress={onPress}>
    <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>{label}</Text>
  </Pressable>
);

export const AdminRequestsScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const logout = useAuthStore((state) => state.logout);

  const [search, setSearch] = useState('');
  const [residentLogin, setResidentLogin] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [keyTypeFilter, setKeyTypeFilter] = useState<KeyTypeFilter>('all');
  const [requests, setRequests] = useState<AdminRequestItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loadState, setLoadState] = useState<RequestState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(search.trim());
  const deferredResidentLogin = useDeferredValue(residentLogin.trim());

  const loadRequests = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoadState('loading');
    }
    setError(null);

    try {
      const result = await apiAdminService.getRequests({
        search: deferredSearch || undefined,
        residentLogin: deferredResidentLogin || undefined,
        status: statusFilter,
        keyType: keyTypeFilter,
        limit: 100,
      });

      setRequests(result.items);
      setTotal(result.total);
      setLastUpdated(new Date().toISOString());
      setLoadState('success');
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : 'Не удалось загрузить заявки';
      setError(message);
      setLoadState('error');
    }
  }, [deferredResidentLogin, deferredSearch, keyTypeFilter, statusFilter]);

  useEffect(() => {
    void loadRequests(true);
    const intervalId = setInterval(() => {
      void loadRequests(false);
    }, REQUESTS_REFRESH_MS);
    const unsubscribe = navigation.addListener('focus', () => {
      void loadRequests(false);
    });

    return () => {
      clearInterval(intervalId);
      unsubscribe();
    };
  }, [loadRequests, navigation]);

  useEffect(() => {
    if (!copyFeedback) {
      return undefined;
    }

    const timeoutId = setTimeout(() => {
      setCopyFeedback(null);
    }, 2200);

    return () => clearTimeout(timeoutId);
  }, [copyFeedback]);

  const handleCopyText = useCallback(async (value: string) => {
    try {
      await copyToClipboard(value);
      setCopyFeedback('Скопировано в буфер обмена');
    } catch {
      setCopyFeedback('Не удалось скопировать данные');
    }
  }, []);

  const handleCopyRequest = useCallback(
    async (item: AdminRequestItem) => {
      try {
        await copyToClipboard(formatRequestForCopy(item));
        setCopyFeedback(`Заявка #${item.id} скопирована`);
      } catch {
        setCopyFeedback('Не удалось скопировать заявку');
      }
    },
    [],
  );

  const keyExtractor = useCallback((item: AdminRequestItem) => item.id, []);

  const renderItem = useCallback(
    ({ item }: { item: AdminRequestItem }) => (
      <View style={[styles.cardWrap, metrics.isDesktop && styles.cardWrapDesktop]}>
        <AdminRequestCard item={item} onCopyRequest={handleCopyRequest} onCopyText={handleCopyText} />
      </View>
    ),
    [handleCopyRequest, handleCopyText, metrics.isDesktop],
  );

  const headerRightSlot = useMemo(
    () => (
      <Pressable style={styles.headerAction} onPress={() => void logout()}>
        <Text style={styles.headerActionText}>Выйти</Text>
      </Pressable>
    ),
    [logout],
  );

  const listHeader = useMemo(
    () => (
      <View style={[styles.headerBlock, { gap: metrics.panelGap }]}>
        <View style={styles.summaryCard}>
          <Text style={[styles.summaryTitle, { fontSize: metrics.isDesktop ? 22 : 19 }]}>Мониторинг заявок</Text>
          <Text style={styles.summaryText}>
            Видны последние {requests.length} из {total} заявок. Поиск работает по номеру, телефону, имени, логину и участку.
          </Text>
          {lastUpdated ? <Text style={styles.summaryMeta}>Обновлено: {formatDateTime(lastUpdated)}</Text> : null}
          {copyFeedback ? <Text style={styles.copyFeedback}>{copyFeedback}</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>

        <View style={styles.filtersCard}>
          <AppInput
            label="Поиск"
            icon="magnify"
            value={search}
            onChangeText={setSearch}
            autoCapitalize="characters"
            placeholder="Номер, телефон, имя, участок"
          />
          <AppInput
            label="Логин жителя"
            icon="account-search-outline"
            value={residentLogin}
            onChangeText={setResidentLogin}
            autoCapitalize="none"
            placeholder="Например user01"
          />

          <View style={styles.filterGroup}>
            <Text style={styles.filterGroupLabel}>Статус</Text>
            <View style={styles.filterRow}>
              {STATUS_OPTIONS.map((option) => (
                <FilterChip
                  key={option.value}
                  label={option.label}
                  active={statusFilter === option.value}
                  onPress={() => setStatusFilter(option.value)}
                />
              ))}
            </View>
          </View>

          <View style={styles.filterGroup}>
            <Text style={styles.filterGroupLabel}>Тип</Text>
            <View style={styles.filterRow}>
              {KEY_TYPE_OPTIONS.map((option) => (
                <FilterChip
                  key={option.value}
                  label={option.label}
                  active={keyTypeFilter === option.value}
                  onPress={() => setKeyTypeFilter(option.value)}
                />
              ))}
            </View>
          </View>

          <Pressable style={styles.refreshButton} onPress={() => void loadRequests(true)}>
            <Text style={styles.refreshButtonText}>Обновить</Text>
          </Pressable>
        </View>
      </View>
    ),
    [copyFeedback, error, keyTypeFilter, lastUpdated, loadRequests, metrics.isDesktop, metrics.panelGap, residentLogin, requests.length, search, statusFilter, total],
  );

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View style={[styles.content, { maxWidth: metrics.isDesktop ? 1200 : metrics.contentMaxWidth }]}>
          <ScreenHeader title="Пропуски" onBack={() => goBackOrHome(navigation, 'Admin')} rightSlot={headerRightSlot} />

          <FlatList
            data={requests}
            key={`admin-${metrics.isDesktop ? 'desktop' : 'mobile'}`}
            numColumns={metrics.isDesktop ? 2 : 1}
            keyExtractor={keyExtractor}
            renderItem={renderItem}
            ListHeaderComponent={listHeader}
            ListEmptyComponent={loadState === 'loading' ? null : <EmptyState text="Заявки не найдены" />}
            contentContainerStyle={styles.listContent}
            columnWrapperStyle={metrics.isDesktop ? styles.desktopColumns : undefined}
            showsVerticalScrollIndicator={false}
          />

          <LoadingOverlay visible={loadState === 'loading'} />
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
  listContent: {
    paddingBottom: theme.spacing.xl,
    gap: theme.spacing.md,
  },
  headerBlock: {
    marginBottom: theme.spacing.lg,
  },
  summaryCard: {
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
    padding: theme.spacing.lg,
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
  summaryMeta: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  copyFeedback: {
    color: theme.colors.success,
    fontSize: 15,
    fontWeight: '600',
  },
  error: {
    color: theme.colors.danger,
    fontSize: 15,
  },
  filtersCard: {
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    padding: theme.spacing.lg,
    gap: theme.spacing.md,
  },
  filterGroup: {
    gap: 10,
  },
  filterGroupLabel: {
    color: theme.colors.textSecondary,
    fontSize: 15,
    fontWeight: '600',
  },
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  filterChip: {
    minHeight: 38,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'transparent',
  },
  filterChipActive: {
    backgroundColor: theme.colors.cardStrong,
  },
  filterChipText: {
    color: theme.colors.textSecondary,
    fontSize: 14,
    fontWeight: '600',
  },
  filterChipTextActive: {
    color: theme.colors.textPrimary,
  },
  refreshButton: {
    alignSelf: 'flex-start',
    minHeight: 42,
    justifyContent: 'center',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 18,
    backgroundColor: theme.colors.cardStrong,
  },
  refreshButtonText: {
    color: theme.colors.textPrimary,
    fontSize: 15,
    fontWeight: '700',
  },
  cardWrap: {
    width: '100%',
    marginBottom: theme.spacing.md,
  },
  cardWrapDesktop: {
    flex: 1,
  },
  desktopColumns: {
    gap: theme.spacing.md,
  },
  headerAction: {
    minHeight: 36,
    justifyContent: 'center',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 14,
    backgroundColor: theme.colors.cardStrong,
  },
  headerActionText: {
    color: theme.colors.textPrimary,
    fontSize: 14,
    fontWeight: '700',
  },
});
