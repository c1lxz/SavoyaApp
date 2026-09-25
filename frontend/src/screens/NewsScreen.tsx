import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect } from "@react-navigation/native";
import { SafeAreaView } from "react-native-safe-area-context";
import { AppBackground } from "@/components/AppBackground";
import { NewsPostCard } from "@/components/news/NewsPostCard";
import { NewsState, newsStyles as styles } from "@/components/news/NewsState";
import { ConfirmNewsDelete } from "@/components/news/ConfirmNewsDelete";
import { MainTabScreenProps } from "@/navigation/types";
import {
  deleteNews,
  getNews,
  getNewsPost,
  newsError,
} from "@/services/newsService";
import { useAuthStore } from "@/store/authStore";
import { theme } from "@/theme";
import { NewsPost } from "@/types/news";

export const NewsScreen = ({
  navigation,
  route,
}: MainTabScreenProps<"News">) => {
  const admin = useAuthStore((state) => state.user?.isAdmin);
  const [post, setPost] = useState<NewsPost | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const generation = useRef(0);
  const targetId = route.params?.postId;
  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const result = targetId
        ? await getNewsPost(targetId)
        : (await getNews(1)).items[0] || null;
      if (current === generation.current) setPost(result);
    } catch (reason) {
      if (current === generation.current) setError(newsError(reason));
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, [targetId]);
  useFocusEffect(
    useCallback(() => {
      void load();
      return () => {
        generation.current += 1;
      };
    }, [load]),
  );
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active" && navigation.isFocused()) void load();
    });
    return () => subscription.remove();
  }, [load, navigation]);
  const remove = async () => {
    setConfirm(false);
    if (!post || deleting) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteNews(post);
      setPost(null);
      if (targetId) navigation.setParams({ postId: undefined });
      else await load();
    } catch (reason) {
      setError(newsError(reason));
    } finally {
      setDeleting(false);
    }
  };
  return (
    <AppBackground>
      <SafeAreaView edges={["left", "right"]} style={styles.safe}>
        <ScrollView
          contentContainerStyle={styles.page}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={loading && !!post}
              onRefresh={() => void load()}
              tintColor={theme.colors.textPrimary}
              colors={[theme.colors.textPrimary]}
            />
          }
        >
          <View style={styles.intro}>
            <Text style={styles.eyebrow}>ЖИЗНЬ ПОСЁЛКА</Text>
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <Text style={styles.heading}>
                {targetId ? "Публикация" : "Новости"}
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Обновить новости"
                disabled={loading}
                onPress={() => void load()}
                style={{
                  width: 44,
                  height: 44,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {loading ? (
                  <ActivityIndicator color={theme.colors.textMuted} />
                ) : (
                  <MaterialCommunityIcons
                    name="refresh"
                    size={24}
                    color={theme.colors.textMuted}
                  />
                )}
              </Pressable>
            </View>
            <Text style={styles.subtitle}>
              Всё важное о жизни посёлка — в одном месте.
            </Text>
          </View>
          {admin ? (
            <Pressable
              accessibilityRole="button"
              onPress={() => navigation.navigate("NewsEditor", {})}
              style={styles.create}
            >
              <MaterialCommunityIcons name="plus" size={23} color="#1C3026" />
              <Text style={styles.createText}>Опубликовать новость</Text>
            </Pressable>
          ) : null}
          {loading && !post ? (
            <NewsState loading title="Загружаем новости" />
          ) : !post ? (
            <NewsState
              title={
                error
                  ? "Новости пока недоступны"
                  : "Здесь будут новости посёлка"
              }
              description={
                error ||
                (admin
                  ? "Опубликуйте первую новость: добавьте текст, фотографии или файлы."
                  : "Новые объявления и события появятся здесь.")
              }
              onRetry={error ? () => void load() : undefined}
            />
          ) : (
            <>
              <NewsPostCard
                post={post}
                admin={admin}
                onEdit={() =>
                  navigation.navigate("NewsEditor", { postId: post.id })
                }
                onDelete={() => setConfirm(true)}
                deleting={deleting}
              />
              {error ? (
                <Text accessibilityLiveRegion="polite" style={styles.error}>
                  {error}
                </Text>
              ) : null}
            </>
          )}
          {targetId ? (
            <Pressable
              accessibilityRole="button"
              onPress={() => {
                setPost(null);
                navigation.setParams({ postId: undefined });
              }}
              style={styles.archive}
            >
              <MaterialCommunityIcons
                name="newspaper-variant-outline"
                size={21}
                color={theme.colors.textPrimary}
              />
              <Text style={styles.archiveText}>К последней новости</Text>
            </Pressable>
          ) : null}
          <Pressable
            accessibilityRole="button"
            onPress={() => navigation.navigate("NewsArchive")}
            style={styles.archive}
          >
            <MaterialCommunityIcons
              name="history"
              size={21}
              color={theme.colors.textPrimary}
            />
            <Text style={styles.archiveText}>Посмотреть прошлые новости</Text>
            <MaterialCommunityIcons
              name="chevron-right"
              size={20}
              color={theme.colors.textPrimary}
            />
          </Pressable>
        </ScrollView>
        <ConfirmNewsDelete
          visible={confirm}
          onCancel={() => setConfirm(false)}
          onConfirm={() => void remove()}
        />
      </SafeAreaView>
    </AppBackground>
  );
};
