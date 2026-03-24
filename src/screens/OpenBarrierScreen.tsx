import React, { useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useGateStore } from '@/store/gateStore';
import { theme } from '@/theme';
import { formatDateTime } from '@/utils/date';

type Props = NativeStackScreenProps<RootStackParamList, 'OpenBarrier'>;

export const OpenBarrierScreen = ({ navigation }: Props) => {
  const { gateState, result, error, openEntry, openExit, resetGateState } = useGateStore();

  useEffect(() => {
    resetGateState();
  }, [resetGateState]);

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScreenHeader title="Открыть шлагбаум" onBack={() => navigation.goBack()} />

        <View style={styles.actions}>
          <AppButton
            title="Въезд"
            onPress={openEntry}
            loading={gateState === 'loading'}
            variant="card"
            leftIcon={<MaterialCommunityIcons name="gate-open" size={22} color={theme.colors.textPrimary} />}
          />
          <AppButton
            title="Выезд"
            onPress={openExit}
            loading={gateState === 'loading'}
            variant="card"
            leftIcon={<MaterialCommunityIcons name="gate-arrow-right" size={22} color={theme.colors.textPrimary} />}
          />
        </View>

        <View style={styles.feedback}>
          {result ? (
            <View style={styles.feedbackCard}>
              <View style={styles.feedbackRow}>
                <MaterialCommunityIcons
                  name={result.success ? 'check-circle-outline' : 'alert-circle-outline'}
                  size={22}
                  color={result.success ? theme.colors.success : theme.colors.danger}
                />
                <Text style={[styles.feedbackText, !result.success && styles.feedbackError]}>{result.message}</Text>
              </View>
              <Text style={styles.feedbackMeta}>{`Время: ${formatDateTime(result.timestamp)}`}</Text>
            </View>
          ) : null}

          {error ? <Text style={styles.feedbackError}>{error}</Text> : null}
        </View>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  actions: {
    marginTop: 32,
    gap: theme.spacing.lg,
  },
  feedback: {
    marginTop: theme.spacing.xl,
    minHeight: 80,
  },
  feedbackCard: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    padding: theme.spacing.md,
    gap: 8,
  },
  feedbackRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  feedbackText: {
    color: theme.colors.textPrimary,
    fontSize: 18,
  },
  feedbackMeta: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  feedbackError: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});

