import React, { useSyncExternalStore } from "react";
import { Linking, Platform, StyleSheet, Text, View } from "react-native";
import { AppButton } from "@/components/AppButton";
import {
  getNotificationStatus,
  registerNewsNotifications,
  subscribeNotifications,
} from "@/services/newsNotifications";
import { theme } from "@/theme";

export const NotificationSettings = () => {
  const status = useSyncExternalStore(
    subscribeNotifications,
    getNotificationStatus,
  );
  if (Platform.OS !== "android") return null;
  const message = {
    idle: "Узнавайте о новых публикациях председателя.",
    loading: "Подключаем уведомления…",
    enabled: "Уведомления о новых публикациях включены.",
    denied: "Разрешите уведомления в настройках приложения.",
    unavailable:
      "Уведомления станут доступны после настройки сервиса администрацией.",
    error:
      "Не удалось подключить уведомления. Проверьте соединение и попробуйте ещё раз.",
  }[status];
  return (
    <View style={styles.panel}>
      <Text style={styles.title}>Новости посёлка</Text>
      <Text style={styles.text}>{message}</Text>
      {status === "denied" ? (
        <AppButton
          title="Настройки уведомлений"
          onPress={() => {
            void Linking.openSettings();
          }}
        />
      ) : status !== "enabled" && status !== "unavailable" ? (
        <AppButton
          title="Включить уведомления"
          loading={status === "loading"}
          onPress={() => {
            void registerNewsNotifications(true);
          }}
        />
      ) : null}
    </View>
  );
};
const styles = StyleSheet.create({
  panel: { gap: 12 },
  title: { fontSize: 18, fontWeight: "600", color: theme.colors.textPrimary },
  text: { fontSize: 15, lineHeight: 22, color: theme.colors.textSecondary },
});
