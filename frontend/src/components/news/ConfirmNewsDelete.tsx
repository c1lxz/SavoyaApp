import React from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { theme } from "@/theme";

export const ConfirmNewsDelete = ({
  visible,
  onCancel,
  onConfirm,
}: {
  visible: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) => (
  <Modal
    visible={visible}
    transparent
    animationType="fade"
    onRequestClose={onCancel}
  >
    <View style={styles.backdrop}>
      <View accessibilityViewIsModal style={styles.dialog}>
        <Text style={styles.title}>Удалить новость?</Text>
        <Text style={styles.text}>
          Публикация и её вложения исчезнут из ленты жителей. Отменить удаление
          не получится.
        </Text>
        <View style={styles.actions}>
          <Pressable
            accessibilityRole="button"
            onPress={onCancel}
            style={styles.button}
          >
            <Text style={styles.cancel}>Оставить</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            onPress={onConfirm}
            style={[styles.button, styles.destructive]}
          >
            <Text style={styles.delete}>Удалить</Text>
          </Pressable>
        </View>
      </View>
    </View>
  </Modal>
);
const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    padding: 24,
    backgroundColor: "rgba(0,0,0,0.7)",
    alignItems: "center",
    justifyContent: "center",
  },
  dialog: {
    width: "100%",
    maxWidth: 420,
    backgroundColor: "#1D3328",
    borderRadius: 24,
    borderWidth: 1,
    borderColor: theme.colors.border,
    padding: 24,
    gap: 16,
  },
  title: { color: theme.colors.textPrimary, fontSize: 22, fontWeight: "600" },
  text: { color: theme.colors.textSecondary, lineHeight: 23, fontSize: 15 },
  actions: { flexDirection: "row", gap: 12, marginTop: 8 },
  button: {
    flex: 1,
    minHeight: 48,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  destructive: { backgroundColor: "#753D3D", borderColor: "#A65F5F" },
  cancel: { color: theme.colors.textPrimary, fontSize: 15, fontWeight: "600" },
  delete: { color: "#FFF4EF", fontSize: 15, fontWeight: "600" },
});
