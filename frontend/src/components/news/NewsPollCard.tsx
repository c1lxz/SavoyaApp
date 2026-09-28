import React, { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { closeNewsPoll, getNewsPost, newsError, voteNewsPoll } from "@/services/newsService";
import { NewsPoll } from "@/types/news";

export const NewsPollCard = ({ postId, poll, admin, onChange }: {
  postId: number;
  poll: NewsPoll;
  admin?: boolean;
  onChange: (poll: NewsPoll | null) => void;
}) => {
  const [selected, setSelected] = useState<number | null>(poll.my_option_id);
  const [results, setResults] = useState(poll.my_option_id !== null || poll.is_closed);
  const [working, setWorking] = useState<"vote" | "close" | "refresh" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const busy = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const latestPoll = useRef(poll);
  latestPoll.current = poll;
  const optionIds = poll.options.map((option) => option.id).join(",");
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; generation.current += 1; };
  }, []);
  useEffect(() => {
    generation.current += 1;
    busy.current = false;
    setWorking(null);
    setSelected(poll.my_option_id);
    setResults(poll.my_option_id !== null || poll.is_closed);
    setConfirmClose(false);
  }, [postId, poll.id]);
  useEffect(() => {
    if (!busy.current) {
      setSelected(poll.my_option_id);
      setResults(poll.my_option_id !== null || poll.is_closed);
    }
  }, [poll.my_option_id, poll.is_closed]);
  useEffect(() => {
    setSelected((current) => current !== null && poll.options.some((option) => option.id === current)
      ? current : poll.my_option_id);
  }, [optionIds, poll.my_option_id]);

  const run = async (action: "vote" | "close" | "refresh") => {
    if (busy.current || (action === "vote" && (selected === null || !poll.options.some((option) => option.id === selected) || selected === poll.my_option_id || poll.is_closed)) || (action === "close" && (!admin || poll.is_closed))) return;
    busy.current = true;
    const request = ++generation.current;
    const snapshot = latestPoll.current;
    setWorking(action);
    setError(null);
    setConfirmClose(false);
    try {
      let next = action === "vote"
        ? await voteNewsPoll(postId, selected!)
        : action === "close" ? await closeNewsPoll(postId) : (await getNewsPost(postId)).poll || null;
      if (!mounted.current || request !== generation.current) return;
      // A refresh can replace option IDs or close the poll while a mutation is
      // in flight. Reconcile against the server instead of replaying that older snapshot.
      if (latestPoll.current !== snapshot) {
        const refreshedSnapshot = latestPoll.current;
        next = (await getNewsPost(postId)).poll || null;
        if (!mounted.current || request !== generation.current) return;
        if (latestPoll.current !== refreshedSnapshot) {
          setError("Голосование обновилось. Обновите результаты, чтобы увидеть ваш ответ.");
          return;
        }
      }
      onChange(next);
      setSelected(next?.my_option_id ?? null);
      setResults(true);
    } catch (reason) {
      if (mounted.current && request === generation.current) setError(newsError(reason));
    } finally {
      if (mounted.current && request === generation.current) {
        busy.current = false;
        setWorking(null);
      }
    }
  };
  const showResults = results || poll.is_closed;
  const changed = selected !== null && poll.options.some((option) => option.id === selected) && selected !== poll.my_option_id;
  return (
    <View style={styles.panel}>
      <View style={styles.top}>
        <MaterialCommunityIcons name="poll" size={21} color="#EAD7A8" />
        <Text style={styles.label}>{poll.is_closed ? "ГОЛОСОВАНИЕ ЗАВЕРШЕНО" : "ГОЛОСОВАНИЕ"}</Text>
      </View>
      <Text accessibilityRole="header" style={styles.question}>{poll.question}</Text>
      <Text style={styles.hint}>{poll.is_closed ? "Итоговые результаты" : "Выберите один вариант. До завершения голос можно изменить."}</Text>
      <View accessibilityRole="radiogroup" style={styles.options}>
        {poll.options.map((option) => {
          const percent = poll.total_votes > 0 ? Math.round(option.votes / poll.total_votes * 100) : 0;
          const checked = option.id === selected;
          return (
            <Pressable key={option.id} accessibilityRole="radio" accessibilityState={{ checked, disabled: !!working || poll.is_closed }}
              accessibilityLabel={`${option.text}${showResults ? `, ${option.votes} голосов, ${percent}%` : ""}${option.id === poll.my_option_id ? ", ваш голос" : ""}`}
              disabled={!!working || poll.is_closed} onPress={() => { setSelected(option.id); setError(null); }}
              style={[styles.option, checked && styles.selected]}>
              {showResults ? <View pointerEvents="none" style={[styles.bar, { width: `${percent}%` }]} /> : null}
              <View style={styles.optionBody}>
                <MaterialCommunityIcons name={checked ? "radiobox-marked" : "radiobox-blank"} size={21} color={checked ? "#EAD7A8" : "#B1BEB2"} />
                <View style={styles.optionLabel}>
                  <Text style={styles.optionText}>{option.text}</Text>
                  {option.id === poll.my_option_id ? <Text style={styles.myVote}>Ваш голос</Text> : null}
                </View>
                {showResults ? <Text style={styles.percent}>{percent}%</Text> : null}
              </View>
              {showResults ? <Text style={styles.optionCount}>Голосов: {option.votes}</Text> : null}
            </Pressable>
          );
        })}
      </View>
      {!poll.is_closed && (poll.my_option_id === null || changed) ? (
        <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!working || !changed, busy: working === "vote" }}
          disabled={!!working || !changed} onPress={() => void run("vote")} style={[styles.vote, (!changed || !!working) && styles.disabled]}>
          {working === "vote" ? <ActivityIndicator color="#173023" /> : null}
          <Text style={styles.voteText}>{working === "vote" ? "Сохраняем голос…" : poll.my_option_id === null ? "Проголосовать" : "Изменить голос"}</Text>
        </Pressable>
      ) : null}
      <View style={styles.footer}>
        <Text accessibilityLiveRegion="polite" style={styles.hint}>Всего голосов: {poll.total_votes}</Text>
        {!poll.is_closed && poll.my_option_id === null ? <Pressable accessibilityRole="button" disabled={!!working}
          onPress={() => setResults(!results)} style={styles.link}>
          <Text style={styles.linkText}>{showResults ? "Скрыть результаты" : "Посмотреть результаты"}</Text>
        </Pressable> : null}
      </View>
      {error ? <View style={styles.errorBox}>
        <Text accessibilityLiveRegion="polite" style={styles.error}>{error}</Text>
        <Text style={styles.hint}>Обновите результаты, чтобы проверить, сохранился ли ваш голос.</Text>
        <Pressable accessibilityRole="button" disabled={!!working} onPress={() => void run("refresh")} style={styles.link}>
          <Text style={styles.linkText}>{working === "refresh" ? "Обновляем…" : "Обновить голосование"}</Text>
        </Pressable>
      </View> : null}
      {admin && !poll.is_closed ? <Pressable accessibilityRole="button" disabled={!!working} onPress={() => setConfirmClose(true)} style={styles.closeAction}>
        <Text style={styles.linkText}>{working === "close" ? "Завершаем…" : "Завершить голосование"}</Text>
      </Pressable> : null}
      <Modal visible={confirmClose} transparent animationType="fade" onRequestClose={() => setConfirmClose(false)}>
        <View style={styles.backdrop}><View style={styles.dialog} accessibilityViewIsModal>
          <Text style={styles.question}>Завершить голосование?</Text>
          <Text style={styles.hint}>Жители увидят результаты, но больше не смогут выбирать или менять ответ. Возобновить голосование нельзя.</Text>
          <Pressable accessibilityRole="button" onPress={() => void run("close")} style={styles.vote}><Text style={styles.voteText}>Завершить</Text></Pressable>
          <Pressable accessibilityRole="button" onPress={() => setConfirmClose(false)} style={styles.link}><Text style={styles.linkText}>Продолжить голосование</Text></Pressable>
        </View></View>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  panel: { borderWidth: 1, borderColor: "#596744", backgroundColor: "#14291F", borderRadius: 18, padding: 16, gap: 13 },
  top: { flexDirection: "row", alignItems: "center", gap: 8 },
  label: { color: "#DCCA96", fontSize: 10, fontWeight: "700", letterSpacing: 1, flex: 1 },
  question: { color: "#FFF5DB", fontSize: 18, fontWeight: "600", lineHeight: 27, flexShrink: 1 },
  hint: { color: "#BBC7BD", fontSize: 12, lineHeight: 19 },
  options: { gap: 9 },
  option: { borderRadius: 12, borderWidth: 1, borderColor: "#435542", overflow: "hidden", minHeight: 52, padding: 12, gap: 4 },
  selected: { borderColor: "#EAD7A8" },
  bar: { position: "absolute", top: 0, bottom: 0, left: 0, backgroundColor: "rgba(152,211,122,0.14)" },
  optionBody: { flexDirection: "row", alignItems: "center", gap: 9 },
  optionLabel: { flex: 1, minWidth: 0 },
  optionText: { color: "#FFF5DB", fontSize: 15, lineHeight: 23 },
  myVote: { color: "#DCCA96", fontSize: 11, lineHeight: 18 },
  percent: { color: "#EAD7A8", fontSize: 14, fontWeight: "600" },
  optionCount: { color: "#BBC7BD", fontSize: 11, marginLeft: 30 },
  vote: { backgroundColor: "#DCCA96", minHeight: 48, padding: 12, borderRadius: 13, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 8 },
  voteText: { color: "#173023", fontSize: 15, fontWeight: "700" },
  footer: { flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between", alignItems: "center" },
  link: { minHeight: 44, justifyContent: "center", alignItems: "flex-start", paddingVertical: 8 },
  linkText: { color: "#EAD7A8", fontSize: 13, lineHeight: 20, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  closeAction: { borderTopWidth: 1, borderTopColor: "#435542", minHeight: 48, paddingTop: 12, justifyContent: "center" },
  errorBox: { gap: 6 },
  error: { color: "#FFA99D", fontSize: 13, lineHeight: 20 },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", padding: 22, alignItems: "center", justifyContent: "center" },
  dialog: { width: "100%", maxWidth: 440, padding: 24, backgroundColor: "#173023", borderRadius: 22, gap: 18 },
});
