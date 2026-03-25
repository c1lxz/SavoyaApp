import React, { memo, useEffect } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useGateStore } from '@/store/gateStore';
import { theme } from '@/theme';

type Props = NativeStackScreenProps<RootStackParamList, 'OpenBarrier'>;

type BarrierButtonProps = {
  title: string;
  onPress: () => void;
  disabled: boolean;
  iconSource: number;
};

const ENTRY_ICON = require('../../assets/barrier-entry.png');
const EXIT_ICON = require('../../assets/barrier-exit.png');

const BarrierActionButton = memo(({ title, onPress, disabled, iconSource }: BarrierButtonProps) => (
  <Pressable
    onPress={onPress}
    disabled={disabled}
    style={[styles.barrierButton, disabled && styles.barrierButtonDisabled]}
  >
    <View style={styles.barrierRow}>
      <Image source={iconSource} style={styles.barrierIcon} resizeMode="contain" />
      <Text style={styles.barrierLabel}>{title}</Text>
    </View>
  </Pressable>
));
BarrierActionButton.displayName = 'BarrierActionButton';

export const OpenBarrierScreen = ({ navigation }: Props) => {
  const gateState = useGateStore((state) => state.gateState);
  const result = useGateStore((state) => state.result);
  const error = useGateStore((state) => state.error);
  const openEntry = useGateStore((state) => state.openEntry);
  const openExit = useGateStore((state) => state.openExit);
  const resetGateState = useGateStore((state) => state.resetGateState);

  useEffect(() => {
    resetGateState();
  }, [resetGateState]);

  const isLoading = gateState === 'loading';

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScreenHeader title="Открыть шлагбаум" onBack={() => navigation.goBack()} />

        <View style={styles.actions}>
          <BarrierActionButton title="Въезд" onPress={openEntry} disabled={isLoading} iconSource={ENTRY_ICON} />
          <BarrierActionButton title="Выезд" onPress={openExit} disabled={isLoading} iconSource={EXIT_ICON} />
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
    marginTop: 24,
    gap: 16,
  },
  barrierButton: {
    minHeight: 90,
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    justifyContent: 'center',
    paddingHorizontal: 22,
  },
  barrierButtonDisabled: {
    opacity: 0.8,
  },
  barrierRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 18,
  },
  barrierIcon: {
    width: 58,
    height: 40,
  },
  barrierLabel: {
    color: theme.colors.textPrimary,
    fontSize: 19,
    fontWeight: '600',
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
  feedbackError: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});
