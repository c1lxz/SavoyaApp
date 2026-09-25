import React, { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  Text,
  View,
} from "react-native";
import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useFocusEffect } from "@react-navigation/native";
import { SafeAreaView } from "react-native-safe-area-context";
import { AppBackground } from "@/components/AppBackground";
import { ScreenHeader } from "@/components/ScreenHeader";
import { ConfirmNewsDelete } from "@/components/news/ConfirmNewsDelete";
import { NewsPostCard } from "@/components/news/NewsPostCard";
import { NewsState, newsStyles as styles } from "@/components/news/NewsState";
import { RootStackParamList } from "@/navigation/types";
import { deleteNews, getNews, newsError } from "@/services/newsService";
import { useAuthStore } from "@/store/authStore";
import { theme } from "@/theme";
import { NewsPost } from "@/types/news";

export const NewsArchiveScreen = ({
  navigation,
}: NativeStackScreenProps<RootStackParamList, "NewsArchive">) => {
  const admin = useAuthStore((state) => state.user?.isAdmin);
  const [items, setItems] = useState<NewsPost[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<NewsPost | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const generation = useRef(0);
  const busy = useRef(false);
  const load = useCallback(async (before?: number) => {
    if (before && busy.current) return;
    busy.current = true;
    const current = before ? generation.current : ++generation.current;
    before ? setMore(true) : setLoading(true);
    setError(null);
    try {
      const result = await getNews(10, before);
      if (current !== generation.current) return;
      setItems((previous) =>
        before
          ? [
              ...previous,
              ...result.items.filter(
                (post) => !previous.some((item) => item.id === post.id),
              ),
            ]
          : result.items,
      );
      setCursor(result.next_cursor);
    } catch (reason) {
      if (current === generation.current) setError(newsError(reason));
    } finally {
      if (current === generation.current) {
        setLoading(false);
        setMore(false);
        busy.current = false;
      }
    }
  }, []);
  useFocusEffect(
    useCallback(() => {
      void load();
      return () => {
        generation.current += 1;
        busy.current = false;
      };
    }, [load]),
  );
  const remove = async () => {
    const post = selected;
    setSelected(null);
    if (!post || deleting) return;
    setDeleting(post.id);
    try {
      await deleteNews(post);
      setItems((previous) => previous.filter((item) => item.id !== post.id));
    } catch (reason) {
      setError(newsError(reason));
    } finally {
      setDeleting(null);
    }
  };
  return (
    <AppBackground>
      <SafeAreaView style={styles.safe}>
        <FlatList
          data={items}
          keyExtractor={(item) => String(item.id)}
          style={{ flex: 1 }}
          contentContainerStyle={styles.page}
          initialNumToRender={3}
          maxToRenderPerBatch={3}
          windowSize={5}
          refreshing={loading && items.length > 0}
          onRefresh={() => void load()}
          showsVerticalScrollIndicator={false}
          ItemSeparatorComponent={() => <View style={{ height: 18 }} />}
          ListHeaderComponent={
            <>
              <ScreenHeader
                title="Прошлые новости"
                onBack={() => navigation.goBack()}
              />
              <Text style={[styles.subtitle, { marginBottom: 20 }]}>
                Объявления, события и полезные материалы посёлка.
              </Text>
            </>
          }
          ListEmptyComponent={
            <NewsState
              loading={loading}
              title={
                loading
                  ? "Загружаем публикации"
                  : error
                    ? "Не удалось загрузить новости"
                    : "Публикаций пока нет"
              }
              description={error || undefined}
              onRetry={error ? () => void load() : undefined}
            />
          }
          renderItem={({ item }) => (
            <NewsPostCard
              post={item}
              compact
              admin={admin}
              deleting={deleting === item.id}
              onEdit={() =>
                navigation.navigate("NewsEditor", { postId: item.id })
              }
              onDelete={() => setSelected(item)}
            />
          )}
          ListFooterComponent={
            items.length ? (
              <View style={{ paddingTop: 18 }}>
                {error ? <Text style={styles.error}>{error}</Text> : null}
                {more ? (
                  <ActivityIndicator
                    color={theme.colors.textPrimary}
                    style={{ padding: 18 }}
                  />
                ) : cursor ? (
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => void load(cursor)}
                    style={styles.archive}
                  >
                    <Text style={styles.archiveText}>
                      {error ? "Повторить загрузку" : "Загрузить ещё новости"}
                    </Text>
                  </Pressable>
                ) : (
                  <Text
                    style={[
                      styles.subtitle,
                      { textAlign: "center", padding: 12 },
                    ]}
                  >
                    Вы прочитали все новости
                  </Text>
                )}
              </View>
            ) : null
          }
        />
        <ConfirmNewsDelete
          visible={!!selected}
          onCancel={() => setSelected(null)}
          onConfirm={() => void remove()}
        />
      </SafeAreaView>
    </AppBackground>
  );
};
