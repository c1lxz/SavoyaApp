import React, { memo, useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useGateStore } from '@/store/gateStore';
import { theme } from '@/theme';

type Props = NativeStackScreenProps<RootStackParamList, 'Wickets'>;

type WicketButtonProps = {
  title: string;
  onPress: () => void;
  disabled: boolean;
  icon: React.ReactNode;
};

const WicketActionButton = memo(({ title, onPress, disabled, icon }: WicketButtonProps) => (
  <Pressable onPress={onPress} disabled={disabled} style={[styles.wicketButton, disabled && styles.wicketButtonDisabled]}>
    <View style={styles.wicketRow}>
      <View style={styles.wicketIconWrap}>{icon}</View>
      <Text style={styles.wicketLabel} numberOfLines={2}>
        {title}
      </Text>
    </View>
  </Pressable>
));
WicketActionButton.displayName = 'WicketActionButton';

export const WicketsScreen = ({ navigation }: Props) => {
  const gateState = useGateStore((state) => state.gateState);
  const result = useGateStore((state) => state.result);
  const error = useGateStore((state) => state.error);
  const openWicketNorth = useGateStore((state) => state.openWicketNorth);
  const openWicketLake = useGateStore((state) => state.openWicketLake);
  const openWicketAdmin = useGateStore((state) => state.openWicketAdmin);
  const openWicketForest = useGateStore((state) => state.openWicketForest);
  const resetGateState = useGateStore((state) => state.resetGateState);

  useEffect(() => {
    resetGateState();
  }, [resetGateState]);

  const isLoading = gateState === 'loading';

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScreenHeader title="Калитки" onBack={() => navigation.goBack()} />

        <View style={styles.actions}>
          <WicketActionButton
            title="Калитка Северная (СНТ Пальмира)"
            onPress={openWicketNorth}
            disabled={isLoading}
            icon={<MaterialCommunityIcons name="compass-outline" size={26} color={theme.colors.textPrimary} />}
          />
          <WicketActionButton
            title="Калитка Озеро (СНТ Вартемяки)"
            onPress={openWicketLake}
            disabled={isLoading}
            icon={<MaterialCommunityIcons name="waves" size={26} color={theme.colors.textPrimary} />}
          />
          <WicketActionButton
            title="Калитка у администрации"
            onPress={openWicketAdmin}
            disabled={isLoading}
            icon={<MaterialCommunityIcons name="office-building-marker-outline" size={26} color={theme.colors.textPrimary} />}
          />
          <WicketActionButton
            title="Калитка Лес"
            onPress={openWicketForest}
            disabled={isLoading}
            icon={<MaterialCommunityIcons name="tree-outline" size={26} color={theme.colors.textPrimary} />}
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
    marginTop: 16,
    gap: 10,
  },
  wicketButton: {
    minHeight: 90,
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    justifyContent: 'center',
    paddingHorizontal: 18,
    paddingVertical: 10,
  },
  wicketButtonDisabled: {
    opacity: 0.8,
  },
  wicketRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  wicketIconWrap: {
    width: 30,
    alignItems: 'center',
  },
  wicketLabel: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontSize: 19,
    fontWeight: '600',
    lineHeight: 24,
  },
  feedback: {
    marginTop: 14,
    minHeight: 70,
  },
  feedbackCard: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    minHeight: 86,
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 6,
  },
  feedbackRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  feedbackText: {
    color: theme.colors.textPrimary,
    fontSize: 18,
    flex: 1,
  },
  feedbackError: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});
