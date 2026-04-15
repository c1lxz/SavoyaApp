import React, { useEffect, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type PasswordChangePromptModalProps = {
  visible: boolean;
  loading: boolean;
  error: string | null;
  onSubmit: (newPassword: string, repeatPassword: string) => Promise<void>;
  onDismiss: () => void;
};

export const PasswordChangePromptModal = ({
  visible,
  loading,
  error,
  onSubmit,
  onDismiss,
}: PasswordChangePromptModalProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const [newPassword, setNewPassword] = useState('');
  const [repeatPassword, setRepeatPassword] = useState('');
  const [secureNewPassword, setSecureNewPassword] = useState(true);
  const [secureRepeatPassword, setSecureRepeatPassword] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) {
      setNewPassword('');
      setRepeatPassword('');
      setSecureNewPassword(true);
      setSecureRepeatPassword(true);
      setFormError(null);
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!newPassword.trim() || !repeatPassword.trim()) {
      setFormError('Введите и подтвердите новый пароль');
      return;
    }

    if (newPassword !== repeatPassword) {
      setFormError('Пароли не совпадают');
      return;
    }

    setFormError(null);
    await onSubmit(newPassword, repeatPassword);
  };

  if (!visible) {
    return null;
  }

  return (
    <Modal transparent visible={visible} animationType="fade" onRequestClose={onDismiss}>
      <View
        style={[
          styles.overlay,
          {
            paddingHorizontal: metrics.horizontalPadding,
            paddingVertical: metrics.isHandset ? 16 : 24,
          },
        ]}
      >
        <Pressable style={StyleSheet.absoluteFill} onPress={onDismiss} />

        <View style={[styles.card, { maxWidth: metrics.isDesktop ? 520 : metrics.formMaxWidth }]}>
          <View style={styles.header}>
            <Text style={[styles.title, { fontSize: metrics.isDesktop ? 24 : 20 }]}>Вы можете сменить пароль</Text>
            <Pressable onPress={onDismiss} hitSlop={12}>
              <MaterialCommunityIcons name="close" size={24} color={theme.colors.textSecondary} />
            </Pressable>
          </View>

          <Text style={styles.description}>
            Смените пароль сейчас или продолжите работу с временным паролем и сделайте это позже.
          </Text>

          <View style={styles.form}>
            <AppInput
              label="Новый пароль"
              icon="lock-outline"
              value={newPassword}
              onChangeText={setNewPassword}
              secureTextEntry={secureNewPassword}
              placeholder="Введите новый пароль"
              rightSlot={
                <Pressable onPress={() => setSecureNewPassword((value) => !value)} hitSlop={8}>
                  <MaterialCommunityIcons
                    name={secureNewPassword ? 'eye-outline' : 'eye-off-outline'}
                    size={24}
                    color={theme.colors.textSecondary}
                  />
                </Pressable>
              }
            />

            <AppInput
              label="Повторите новый пароль"
              icon="lock-check-outline"
              value={repeatPassword}
              onChangeText={setRepeatPassword}
              secureTextEntry={secureRepeatPassword}
              placeholder="Повторите новый пароль"
              rightSlot={
                <Pressable onPress={() => setSecureRepeatPassword((value) => !value)} hitSlop={8}>
                  <MaterialCommunityIcons
                    name={secureRepeatPassword ? 'eye-outline' : 'eye-off-outline'}
                    size={24}
                    color={theme.colors.textSecondary}
                  />
                </Pressable>
              }
            />
          </View>

          {formError ? <Text style={styles.error}>{formError}</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}

          <View style={styles.actions}>
            <AppButton title="Поменять пароль" onPress={() => void handleSubmit()} loading={loading} />
            <AppButton title="Оставить" onPress={onDismiss} variant="card" disabled={loading} />
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'center',
    backgroundColor: theme.colors.overlay,
  },
  card: {
    alignSelf: 'center',
    width: '100%',
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: 'rgba(14, 28, 23, 0.98)',
    padding: theme.spacing.lg,
    gap: theme.spacing.md,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: theme.spacing.md,
  },
  title: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontWeight: '700',
  },
  description: {
    color: theme.colors.textSecondary,
    fontSize: 15,
    lineHeight: 22,
  },
  form: {
    gap: theme.spacing.md,
  },
  actions: {
    gap: theme.spacing.sm,
  },
  error: {
    color: theme.colors.danger,
    fontSize: 15,
  },
});
