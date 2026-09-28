import React from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { NEWS_POLL_ANSWER_LIMIT, NEWS_POLL_OPTION_LIMIT, NEWS_POLL_QUESTION_LIMIT } from "@/services/newsService";
import { NewsPollDefinition } from "@/types/news";

export const NewsPollEditor = ({ value, onChange, disabled, locked }: {
  value: NewsPollDefinition | null;
  onChange: (value: NewsPollDefinition | null) => void;
  disabled: boolean;
  locked: boolean;
}) => {
  if (!value) return (
    <Pressable accessibilityRole="button" disabled={disabled} onPress={() => onChange({ question: "", options: ["", ""] })}
      style={[styles.addPoll, disabled && styles.disabled]}>
      <MaterialCommunityIcons name="poll" size={22} color="#EAD7A8" />
      <Text style={styles.buttonText}>Добавить голосование</Text>
    </Pressable>
  );
  const readOnly = disabled || locked;
  return (
    <View style={styles.panel}>
      <View style={styles.headingRow}>
        <Text accessibilityRole="header" style={styles.heading}>Голосование</Text>
        {!locked ? <Pressable accessibilityRole="button" accessibilityLabel="Убрать голосование"
          disabled={disabled} onPress={() => onChange(null)} style={styles.remove}>
          <MaterialCommunityIcons name="close" size={23} color="#EAD7A8" />
        </Pressable> : null}
      </View>
      <Text style={styles.hint}>{locked
        ? "У голосования уже есть ответы или оно завершено. Вопрос и варианты сохранены; текст и вложения новости можно менять."
        : "Один вариант на аккаунт. Выбор можно изменить до завершения. В результатах видны только количества голосов."}</Text>
      <Text style={styles.label}>Вопрос</Text>
      <TextInput accessibilityLabel="Вопрос голосования" placeholder="Что обсудим с жителями?" placeholderTextColor="#A9B6AC"
        multiline textAlignVertical="top" editable={!readOnly} maxLength={NEWS_POLL_QUESTION_LIMIT}
        value={value.question} onChangeText={(question) => onChange({ ...value, question })} style={[styles.input, styles.question]} />
      <Text style={styles.label}>Варианты ответа</Text>
      {value.options.map((option, index) => (
        <View key={index} style={styles.optionRow}>
          <Text style={styles.number}>{index + 1}</Text>
          <TextInput accessibilityLabel={`Вариант ответа ${index + 1}`} placeholder={`Вариант ${index + 1}`} placeholderTextColor="#A9B6AC"
            multiline textAlignVertical="top" editable={!readOnly} maxLength={NEWS_POLL_ANSWER_LIMIT} value={option}
            onChangeText={(text) => onChange({ ...value, options: value.options.map((item, i) => i === index ? text : item) })}
            style={[styles.input, styles.option]} />
          {!locked && value.options.length > 2 ? <Pressable accessibilityRole="button" accessibilityLabel={`Убрать вариант ${index + 1}`}
            disabled={disabled} style={styles.remove} onPress={() => onChange({ ...value, options: value.options.filter((_, i) => i !== index) })}>
            <MaterialCommunityIcons name="minus-circle-outline" size={22} color="#DCCA96" />
          </Pressable> : null}
        </View>
      ))}
      {!locked && value.options.length < NEWS_POLL_OPTION_LIMIT ? <Pressable accessibilityRole="button" disabled={disabled}
        style={styles.addOption} onPress={() => onChange({ ...value, options: [...value.options, ""] })}>
        <Text style={styles.buttonText}>+ Добавить вариант</Text>
        <Text style={styles.hint}>{value.options.length} / {NEWS_POLL_OPTION_LIMIT}</Text>
      </Pressable> : null}
    </View>
  );
};

const styles = StyleSheet.create({
  panel: { marginVertical: 18, padding: 16, borderRadius: 18, borderWidth: 1, borderColor: "#516345", backgroundColor: "#152B21", gap: 10 },
  headingRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  heading: { color: "#FFF5DB", fontSize: 18, fontWeight: "600", flex: 1 },
  hint: { color: "#BBC7BD", fontSize: 13, lineHeight: 20, flexShrink: 1 },
  label: { color: "#EAD7A8", fontSize: 13, fontWeight: "600", marginTop: 8 },
  input: { color: "#FFF5DB", backgroundColor: "#102218", borderWidth: 1, borderColor: "#586451", borderRadius: 12, fontSize: 16, lineHeight: 23, padding: 12 },
  question: { minHeight: 94, maxHeight: 190 },
  option: { flex: 1, minWidth: 0, minHeight: 50, maxHeight: 160 },
  optionRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  number: { color: "#BBC7BD", fontSize: 13, width: 16, textAlign: "center" },
  remove: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  addOption: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  buttonText: { color: "#EAD7A8", fontSize: 14, fontWeight: "600", flexShrink: 1 },
  addPoll: { minHeight: 52, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, borderWidth: 1, borderColor: "#516345", borderRadius: 14, padding: 12, marginVertical: 14, backgroundColor: "#152B21" },
  disabled: { opacity: 0.5 },
});
