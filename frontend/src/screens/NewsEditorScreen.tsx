import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { NavigationAction } from "@react-navigation/native";
import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { SafeAreaView } from "react-native-safe-area-context";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import { AppBackground } from "@/components/AppBackground";
import { ScreenHeader } from "@/components/ScreenHeader";
import { NewsState, newsStyles } from "@/components/news/NewsState";
import { RootStackParamList } from "@/navigation/types";
import {
  clearNewsDraft,
  createNewsRequestId,
  deleteUnusedMedia,
  formatFileSize,
  getNewsMedia,
  getNewsPost,
  loadNewsDraft,
  NEWS_ATTACHMENT_LIMIT,
  NEWS_FILE_LIMIT,
  NEWS_TEXT_LIMIT,
  NewsDraft,
  newsError,
  newsDraftContentKey,
  newsUrl,
  pickNewsWebFiles,
  PublicationError,
  publishNews,
  saveNewsDraft,
  updateNews,
  uploadNewsFile,
} from "@/services/newsService";
import { useAuthStore } from "@/store/authStore";
import { theme } from "@/theme";
import { NewsFile, NewsMedia, NewsPayload } from "@/types/news";

type Attachment = {
  key: string;
  file?: NewsFile;
  media?: NewsMedia;
  status: "queued" | "uploading" | "done" | "error";
  progress: number;
  error?: string;
};
const existingAttachment = (media: NewsMedia): Attachment => ({
  key: `media-${media.id}`,
  media,
  status: "done",
  progress: 100,
});

export const NewsEditorScreen = ({
  navigation,
  route,
}: NativeStackScreenProps<RootStackParamList, "NewsEditor">) => {
  const user = useAuthStore((state) => state.user);
  const postId = route.params?.postId;
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [version, setVersion] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [storageError, setStorageError] = useState(false);
  const [requestId, setRequestId] = useState(createNewsRequestId);
  const [pendingPayload, setPendingPayload] = useState<
    NewsPayload | undefined
  >();
  const [leaveAction, setLeaveAction] = useState<NavigationAction | null>(null);
  const [restored, setRestored] = useState(false);
  const mounted = useRef(true);
  const saved = useRef(false);
  const uploadBusy = useRef(false);
  const cancels = useRef(new Map<string, () => void>());
  const writeQueue = useRef<Promise<void>>(Promise.resolve());
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialSignature = useRef("");
  const uploadedHere = useRef(new Set<string>());
  const blobUrls = useRef(new Set<string>());
  const draftSnapshot = useRef<NewsDraft>({ text: "", media: [], requestId });
  const hasPending = attachments.some((item) => item.status !== "done");
  const frozen = saving || !!pendingPayload;
  const signature = JSON.stringify({
    text,
    ids: attachments.map((item) => item.media?.id || item.key),
  });
  draftSnapshot.current = {
    text,
    media: attachments.flatMap((item) => (item.media ? [item.media] : [])),
    requestId,
    pendingPayload,
  };
  const draftContentKey = newsDraftContentKey(draftSnapshot.current);

  const persist = useCallback(
    (draft: NewsDraft) => {
      if (!user || postId) return Promise.resolve();
      writeQueue.current = writeQueue.current
        .catch(() => {})
        .then(() => saveNewsDraft(user.id, draft));
      return writeQueue.current;
    },
    [user?.id, postId],
  );

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      cancels.current.forEach((cancel) => cancel());
      blobUrls.current.forEach((uri) => URL.revokeObjectURL(uri));
    };
  }, []);

  const restore = useCallback(async () => {
    if (!user?.isAdmin) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (postId) {
        const post = await getNewsPost(postId);
        if (!mounted.current) return;
        setText(post.text);
        setAttachments(post.media.map(existingAttachment));
        setVersion(post.version);
        initialSignature.current = JSON.stringify({
          text: post.text,
          ids: post.media.map((media) => media.id),
        });
      } else {
        const draft = await loadNewsDraft(user.id);
        if (!mounted.current) return;
        if (draft) {
          let restoredAttachments = draft.media.map(existingAttachment);
          if (!draft.pendingPayload && draft.media.length) {
            const lookups = await Promise.allSettled(
              draft.media.map((media) => getNewsMedia(media.id)),
            );
            if (!mounted.current) return;
            restoredAttachments = lookups.map((result, index) =>
              result.status === "fulfilled"
                ? existingAttachment(result.value)
                : {
                    ...existingAttachment(draft.media[index]),
                    status: "error" as const,
                    error: `${newsError(result.reason)}. Если вложение больше не доступно, уберите его и выберите файл заново.`,
                  },
            );
          }
          setText(draft.text);
          setAttachments(restoredAttachments);
          setRequestId(draft.requestId);
          setPendingPayload(draft.pendingPayload);
          setRestored(
            !!draft.text || draft.media.length > 0 || !!draft.pendingPayload,
          );
        }
      }
      setLoaded(true);
    } catch (reason) {
      if (mounted.current) setError(newsError(reason));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [postId, user?.id, user?.isAdmin]);
  useEffect(() => {
    void restore();
  }, [restore]);

  useEffect(() => {
    if (!loaded || postId || saved.current) return;
    const timer = setTimeout(() => {
      if (saved.current) return;
      void persist(draftSnapshot.current)
        .then(() => {
          if (mounted.current) setStorageError(false);
        })
        .catch(() => {
          if (mounted.current) setStorageError(true);
        });
    }, 400);
    autosaveTimer.current = timer;
    return () => clearTimeout(timer);
  }, [draftContentKey, loaded, postId, persist]);

  useEffect(
    () =>
      navigation.addListener("beforeRemove", (event) => {
        if (saved.current) return;
        if (
          saving ||
          hasPending ||
          (postId && loaded && signature !== initialSignature.current)
        ) {
          event.preventDefault();
          if (!saving) setLeaveAction(event.data.action);
          return;
        }
        if (!postId && loaded)
          void persist(draftSnapshot.current).catch(() => {});
      }),
    [navigation, saving, hasPending, postId, loaded, signature, persist],
  );

  // Upload one file at a time. A failed item leaves successful attachments intact,
  // and subsequent files continue without loading their contents into JS memory.
  useEffect(() => {
    if (uploadBusy.current || frozen) return;
    const item = attachments.find(
      (entry) => entry.status === "queued" && entry.file,
    );
    if (!item?.file) return;
    uploadBusy.current = true;
    setAttachments((previous) =>
      previous.map((entry) =>
        entry.key === item.key ? { ...entry, status: "uploading" } : entry,
      ),
    );
    const job = uploadNewsFile(item.file, (progress) => {
      if (mounted.current)
        setAttachments((previous) =>
          previous.map((entry) =>
            entry.key === item.key ? { ...entry, progress } : entry,
          ),
        );
    });
    cancels.current.set(item.key, job.cancel);
    void job.promise
      .then((media) => {
        uploadedHere.current.add(media.id);
        if (mounted.current)
          setAttachments((previous) =>
            previous.map((entry) =>
              entry.key === item.key
                ? {
                    ...entry,
                    media,
                    status: "done",
                    progress: 100,
                    error: undefined,
                  }
                : entry,
            ),
          );
      })
      .catch((reason) => {
        if (mounted.current)
          setAttachments((previous) =>
            previous.map((entry) =>
              entry.key === item.key
                ? { ...entry, status: "error", error: newsError(reason) }
                : entry,
            ),
          );
      })
      .finally(() => {
        cancels.current.delete(item.key);
        uploadBusy.current = false;
        if (mounted.current) setAttachments((previous) => [...previous]);
      });
  }, [attachments, frozen]);

  const addFiles = (files: NewsFile[]) => {
    files.forEach((file) => {
      if (file.uri.startsWith("blob:")) blobUrls.current.add(file.uri);
    });
    const rejected: string[] = [];
    const valid = files.filter((file) => {
      if (file.size && file.size > NEWS_FILE_LIMIT) {
        rejected.push(file.name);
        return false;
      }
      return true;
    });
    const remaining = NEWS_ATTACHMENT_LIMIT - attachments.length;
    if (rejected.length)
      setError(
        `Файл «${rejected[0]}» больше 100 МБ. Выберите файл меньшего размера.`,
      );
    else if (valid.length > remaining)
      setError(
        "К новости можно прикрепить до 10 файлов. Добавлены первые выбранные файлы.",
      );
    else setError(null);
    setAttachments((previous) => [
      ...previous,
      ...valid
        .slice(0, Math.max(0, NEWS_ATTACHMENT_LIMIT - previous.length))
        .map(
          (file, index): Attachment => ({
            key: `local-${Date.now()}-${index}-${Math.random().toString(36).slice(2)}`,
            file,
            status: "queued",
            progress: 0,
          }),
        ),
    ]);
  };

  const pick = async (kind: "photo" | "file") => {
    if (picking || frozen || attachments.length >= NEWS_ATTACHMENT_LIMIT)
      return;
    setPicking(true);
    setError(null);
    try {
      if (Platform.OS === "web") {
        addFiles(await pickNewsWebFiles(kind === "photo"));
      } else if (kind === "photo") {
        const permission =
          await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!permission.granted)
          throw new Error(
            "Разрешите доступ к фото и видео в настройках приложения или выберите их через «Файлы».",
          );
        const result = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.All,
          allowsMultipleSelection: true,
          selectionLimit: NEWS_ATTACHMENT_LIMIT - attachments.length,
          quality: 1,
          base64: false,
          exif: false,
          videoExportPreset: ImagePicker.VideoExportPreset.Passthrough,
        });
        if (!result.canceled)
          addFiles(
            result.assets.map((asset) => ({
              uri: asset.uri,
              name:
                asset.fileName ||
                `media-${Date.now()}.${asset.type === "video" ? "mp4" : "jpg"}`,
              mimeType:
                asset.mimeType ||
                (asset.type === "video" ? "video/mp4" : "image/jpeg"),
              size: asset.fileSize,
            })),
          );
      } else {
        const result = await DocumentPicker.getDocumentAsync({
          type: "*/*",
          multiple: true,
          copyToCacheDirectory: true,
        });
        if (!result.canceled)
          addFiles(
            result.assets.map((asset) => ({
              uri: asset.uri,
              name: asset.name,
              mimeType: asset.mimeType || "application/octet-stream",
              size: asset.size,
              file: asset.file,
            })),
          );
      }
    } catch (reason) {
      setError(newsError(reason));
    } finally {
      setPicking(false);
    }
  };

  const removeAttachment = (item: Attachment) => {
    cancels.current.get(item.key)?.();
    setAttachments((previous) =>
      previous.filter((entry) => entry.key !== item.key),
    );
    if (item.file?.uri.startsWith("blob:")) {
      URL.revokeObjectURL(item.file.uri);
      blobUrls.current.delete(item.file.uri);
    }
    // The server refuses to delete published media. Clear abandoned draft files
    // immediately so reopening/removing a draft does not consume upload quota.
    if (item.media && (!postId || uploadedHere.current.has(item.media.id))) {
      void deleteUnusedMedia(item.media.id).catch(() => {});
      uploadedHere.current.delete(item.media.id);
    }
  };

  const retryAttachment = async (item: Attachment) => {
    if (item.file) {
      setAttachments((previous) =>
        previous.map((entry) =>
          entry.key === item.key
            ? { ...entry, status: "queued", progress: 0, error: undefined }
            : entry,
        ),
      );
    } else if (item.media) {
      try {
        const media = await getNewsMedia(item.media.id);
        if (mounted.current)
          setAttachments((previous) =>
            previous.map((entry) =>
              entry.key === item.key
                ? { ...entry, media, status: "done", error: undefined }
                : entry,
            ),
          );
      } catch (reason) {
        if (mounted.current)
          setAttachments((previous) =>
            previous.map((entry) =>
              entry.key === item.key
                ? {
                    ...entry,
                    error: `${newsError(reason)}. Если вложение больше не доступно, уберите его и выберите файл заново.`,
                  }
                : entry,
            ),
          );
      }
    }
  };

  const submit = async () => {
    if (!user?.isAdmin || saving || hasPending) return;
    const payload = pendingPayload || {
      text: text.trim(),
      media_ids: attachments.flatMap((item) =>
        item.media ? [item.media.id] : [],
      ),
    };
    if (!payload.text && !payload.media_ids.length) {
      setError("Добавьте текст или хотя бы одно вложение.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (!postId) {
        // Persist before sending, so a process restart can retry the same request.
        const snapshot = { ...draftSnapshot.current, pendingPayload: payload };
        draftSnapshot.current = snapshot;
        setPendingPayload(payload);
        await persist(snapshot);
      }
      await (postId
        ? updateNews(postId, payload, version)
        : publishNews(payload, requestId));
      saved.current = true;
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
      if (!postId) {
        await writeQueue.current.catch(() => {});
        await clearNewsDraft(user.id).catch(() => {});
      }
      if (navigation.canGoBack()) navigation.goBack();
      else
        navigation.navigate("Home", {
          screen: "News",
          params: { postId: undefined },
        });
    } catch (reason) {
      if (!(reason instanceof PublicationError && reason.uncertain)) {
        setPendingPayload(undefined);
        if (!postId)
          void persist({
            ...draftSnapshot.current,
            pendingPayload: undefined,
          }).catch(() => {});
      }
      setError(newsError(reason));
    } finally {
      if (mounted.current) setSaving(false);
    }
  };

  if (!user?.isAdmin)
    return (
      <AppBackground>
        <SafeAreaView style={newsStyles.safe}>
          <ScreenHeader title="Новости" onBack={() => navigation.goBack()} />
          <NewsState
            title="Публикации доступны председателю"
            description="Жители могут читать новости в общей ленте."
          />
        </SafeAreaView>
      </AppBackground>
    );
  return (
    <AppBackground>
      <SafeAreaView style={newsStyles.safe}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <ScrollView
            contentContainerStyle={newsStyles.page}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            <ScreenHeader
              title={postId ? "Редактирование" : "Новая публикация"}
              onBack={() => navigation.goBack()}
            />
            {loading || !loaded ? (
              <NewsState
                loading={loading}
                title={
                  loading ? "Открываем редактор" : "Не удалось открыть редактор"
                }
                description={error || undefined}
                onRetry={!loading ? () => void restore() : undefined}
              />
            ) : (
              <>
                <View style={styles.editorHeader}>
                  <View style={styles.avatar}>
                    <MaterialCommunityIcons
                      name="pine-tree"
                      size={28}
                      color={theme.colors.textPrimary}
                    />
                  </View>
                  <View style={{ flex: 1, gap: 5 }}>
                    <Text style={styles.author}>
                      {user.fullName || "Правление посёлка"}
                    </Text>
                    <Text style={styles.muted}>
                      Публикация для всех жителей
                    </Text>
                  </View>
                  <MaterialCommunityIcons
                    name="account-group-outline"
                    size={23}
                    color={theme.colors.textMuted}
                  />
                </View>
                {restored && !pendingPayload ? (
                  <Text style={styles.notice}>
                    Черновик восстановлен. Можно продолжить с того же места.
                  </Text>
                ) : null}
                {pendingPayload ? (
                  <View style={styles.noticeBox}>
                    <Text style={styles.notice}>
                      Не удалось подтвердить публикацию. Нажмите «Повторить
                      публикацию», чтобы проверить результат. Текст и вложения
                      сохранены; повторная новость не появится.
                    </Text>
                  </View>
                ) : null}
                <View style={styles.textPanel}>
                  <TextInput
                    accessibilityLabel="Текст новости"
                    placeholder="Что нового в посёлке?"
                    placeholderTextColor="rgba(242,228,184,0.46)"
                    multiline
                    textAlignVertical="top"
                    value={text}
                    onChangeText={setText}
                    editable={!frozen}
                    maxLength={NEWS_TEXT_LIMIT}
                    style={styles.input}
                  />
                  <Text style={styles.counter}>
                    {text.length.toLocaleString("ru-RU")} / 20 000
                  </Text>
                </View>
                <View style={styles.toolbar}>
                  <Pressable
                    accessibilityRole="button"
                    disabled={
                      frozen ||
                      picking ||
                      attachments.length >= NEWS_ATTACHMENT_LIMIT
                    }
                    onPress={() => void pick("photo")}
                    style={[styles.attachButton, frozen && styles.disabled]}
                  >
                    <MaterialCommunityIcons
                      name="image-multiple-outline"
                      size={22}
                      color={theme.colors.textPrimary}
                    />
                    <Text style={styles.attachText}>Фото и видео</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    disabled={
                      frozen ||
                      picking ||
                      attachments.length >= NEWS_ATTACHMENT_LIMIT
                    }
                    onPress={() => void pick("file")}
                    style={[styles.attachButton, frozen && styles.disabled]}
                  >
                    <MaterialCommunityIcons
                      name="paperclip"
                      size={23}
                      color={theme.colors.textPrimary}
                    />
                    <Text style={styles.attachText}>Файлы</Text>
                  </Pressable>
                </View>
                <Text style={styles.limit}>
                  До 10 вложений, каждое до 100 МБ. Фотографии, видео и любые
                  документы.
                </Text>
                {picking ? (
                  <ActivityIndicator
                    color={theme.colors.textPrimary}
                    style={{ padding: 12 }}
                  />
                ) : null}
                {attachments.length ? (
                  <View style={styles.attachments}>
                    <Text style={styles.sectionLabel}>
                      Вложения · {attachments.length} / 10
                    </Text>
                    {attachments.map((item) => {
                      const name =
                        item.media?.name || item.file?.name || "Вложение";
                      const size = item.media?.size_bytes || item.file?.size;
                      const isImage =
                        item.media?.kind === "image" ||
                        item.file?.mimeType.startsWith("image/");
                      const uri =
                        item.file?.uri ||
                        (item.media
                          ? newsUrl(item.media.thumbnail_url || item.media.url)
                          : undefined);
                      return (
                        <View key={item.key} style={styles.attachment}>
                          <View style={styles.attachmentRow}>
                            {isImage && uri ? (
                              <Image source={{ uri }} style={styles.preview} />
                            ) : (
                              <View
                                style={[styles.preview, styles.filePreview]}
                              >
                                <MaterialCommunityIcons
                                  name={
                                    item.media?.kind === "video" ||
                                    item.file?.mimeType.startsWith("video/")
                                      ? "video-outline"
                                      : "file-document-outline"
                                  }
                                  size={27}
                                  color={theme.colors.textPrimary}
                                />
                              </View>
                            )}
                            <View style={styles.attachmentInfo}>
                              <Text style={styles.fileName} numberOfLines={2}>
                                {name}
                              </Text>
                              <Text
                                style={[
                                  styles.muted,
                                  item.status === "done" && styles.success,
                                ]}
                              >
                                {item.status === "done"
                                  ? "Готово"
                                  : item.status === "queued"
                                    ? "В очереди"
                                    : item.status === "uploading"
                                      ? item.progress >= 99
                                        ? "Обработка на сервере…"
                                        : `Загрузка ${item.progress}%`
                                      : "Не загружено"}
                                {size ? ` · ${formatFileSize(size)}` : ""}
                              </Text>
                            </View>
                            {!frozen ? (
                              <Pressable
                                accessibilityRole="button"
                                accessibilityLabel={
                                  item.status === "uploading"
                                    ? `Отменить загрузку ${name}`
                                    : `Убрать ${name}`
                                }
                                onPress={() => removeAttachment(item)}
                                style={styles.remove}
                              >
                                <MaterialCommunityIcons
                                  name="close"
                                  size={22}
                                  color={theme.colors.textMuted}
                                />
                              </Pressable>
                            ) : null}
                          </View>
                          {item.status === "uploading" ? (
                            <View style={styles.progressTrack}>
                              <View
                                style={[
                                  styles.progress,
                                  { width: `${Math.max(2, item.progress)}%` },
                                ]}
                              />
                            </View>
                          ) : null}
                          {item.status === "error" ? (
                            <View style={styles.uploadError}>
                              <Text style={styles.fileError}>{item.error}</Text>
                              <Pressable
                                accessibilityRole="button"
                                onPress={() => void retryAttachment(item)}
                                style={styles.retry}
                              >
                                <MaterialCommunityIcons
                                  name="refresh"
                                  size={18}
                                  color={theme.colors.textPrimary}
                                />
                                <Text style={styles.attachText}>Повторить</Text>
                              </Pressable>
                            </View>
                          ) : null}
                        </View>
                      );
                    })}
                  </View>
                ) : null}
                {storageError ? (
                  <Text style={newsStyles.error}>
                    Не удалось сохранить черновик на устройстве. Не закрывайте
                    редактор до публикации.
                  </Text>
                ) : null}
                {error ? (
                  <Text
                    accessibilityLiveRegion="polite"
                    style={newsStyles.error}
                  >
                    {error}
                  </Text>
                ) : null}
                {hasPending ? (
                  <Text style={styles.limit}>
                    Дождитесь загрузки всех файлов. Неудачную загрузку можно
                    повторить или убрать вложение.
                  </Text>
                ) : null}
                <Pressable
                  accessibilityRole="button"
                  disabled={
                    saving ||
                    hasPending ||
                    (!text.trim() && !attachments.length)
                  }
                  onPress={() => void submit()}
                  style={[
                    newsStyles.create,
                    styles.publish,
                    (saving ||
                      hasPending ||
                      (!text.trim() && !attachments.length)) &&
                      styles.disabled,
                  ]}
                >
                  {saving ? (
                    <ActivityIndicator color="#1C3026" />
                  ) : (
                    <MaterialCommunityIcons
                      name={postId ? "check" : "send-outline"}
                      size={22}
                      color="#1C3026"
                    />
                  )}
                  <Text style={newsStyles.createText}>
                    {saving
                      ? "Сохраняем…"
                      : postId
                        ? "Сохранить изменения"
                        : pendingPayload
                          ? "Повторить публикацию"
                          : "Опубликовать"}
                  </Text>
                </Pressable>
                <Text style={styles.footerNote}>
                  {postId
                    ? "Изменения появятся в ленте жителей после сохранения."
                    : "После публикации новость появится в ленте жителей."}
                </Text>
              </>
            )}
          </ScrollView>
          <Modal
            visible={!!leaveAction}
            transparent
            animationType="fade"
            onRequestClose={() => setLeaveAction(null)}
          >
            <View style={styles.backdrop}>
              <View style={styles.dialog}>
                <Text style={styles.dialogTitle}>Выйти из редактора?</Text>
                <Text style={styles.notice}>
                  {postId
                    ? "Несохранённые изменения будут потеряны."
                    : "Текст и загруженные вложения останутся в черновике."}{" "}
                  {hasPending
                    ? "Незавершённые загрузки остановятся; эти файлы нужно будет выбрать заново."
                    : ""}
                </Text>
                <Pressable
                  accessibilityRole="button"
                  style={newsStyles.archive}
                  onPress={() => setLeaveAction(null)}
                >
                  <Text style={newsStyles.archiveText}>
                    Продолжить редактирование
                  </Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  style={styles.leave}
                  onPress={() => {
                    const action = leaveAction;
                    if (!action) return;
                    cancels.current.forEach((cancel) => cancel());
                    saved.current = true;
                    void (
                      postId
                        ? Promise.resolve()
                        : persist(draftSnapshot.current)
                    )
                      .catch(() => {})
                      .finally(() => navigation.dispatch(action));
                  }}
                >
                  <Text style={styles.fileError}>Выйти</Text>
                </Pressable>
              </View>
            </View>
          </Modal>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  editorHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginBottom: 20,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 17,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.colors.cardStrong,
  },
  author: { color: theme.colors.textPrimary, fontSize: 16, fontWeight: "600" },
  muted: { color: theme.colors.textMuted, fontSize: 12, lineHeight: 18 },
  textPanel: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 20,
    backgroundColor: "rgba(23,42,34,0.96)",
    overflow: "hidden",
  },
  input: {
    minHeight: 240,
    maxHeight: 540,
    padding: 18,
    fontSize: 16,
    lineHeight: 26,
    color: theme.colors.textPrimary,
  },
  counter: {
    color: theme.colors.textMuted,
    fontSize: 11,
    textAlign: "right",
    padding: 12,
  },
  toolbar: { flexDirection: "row", gap: 10, marginTop: 14 },
  attachButton: {
    minHeight: 50,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    flex: 1,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 8,
  },
  attachText: {
    color: theme.colors.textPrimary,
    fontSize: 14,
    fontWeight: "600",
  },
  limit: {
    color: theme.colors.textMuted,
    fontSize: 12,
    lineHeight: 19,
    marginVertical: 12,
  },
  attachments: { gap: 10, marginTop: 10 },
  sectionLabel: {
    color: theme.colors.textSecondary,
    fontSize: 13,
    fontWeight: "600",
    marginBottom: 3,
  },
  attachment: {
    backgroundColor: "rgba(23,42,34,0.96)",
    borderWidth: 1,
    borderColor: "rgba(219,193,134,0.20)",
    borderRadius: 15,
    padding: 12,
    gap: 10,
  },
  attachmentRow: { flexDirection: "row", gap: 10, alignItems: "center" },
  preview: {
    width: 48,
    height: 52,
    borderRadius: 9,
    backgroundColor: theme.colors.cardStrong,
  },
  filePreview: { alignItems: "center", justifyContent: "center" },
  attachmentInfo: { flex: 1, gap: 4 },
  fileName: { color: theme.colors.textPrimary, fontSize: 14, lineHeight: 20 },
  remove: {
    width: 42,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  progressTrack: {
    height: 4,
    backgroundColor: "#0C2118",
    borderRadius: 4,
    overflow: "hidden",
  },
  progress: { height: 4, backgroundColor: "#DCCA96", borderRadius: 4 },
  uploadError: { gap: 4 },
  fileError: { color: theme.colors.danger, fontSize: 13, lineHeight: 20 },
  retry: {
    minHeight: 42,
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  success: { color: theme.colors.success },
  publish: { marginTop: 22, marginBottom: 10, minHeight: 56 },
  disabled: { opacity: 0.45 },
  footerNote: {
    color: theme.colors.textMuted,
    fontSize: 12,
    lineHeight: 19,
    textAlign: "center",
    marginBottom: 14,
  },
  notice: {
    color: theme.colors.textSecondary,
    fontSize: 13,
    lineHeight: 21,
    marginBottom: 12,
  },
  noticeBox: {
    borderRadius: 15,
    padding: 14,
    backgroundColor: theme.colors.cardStrong,
    marginBottom: 16,
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.7)",
    padding: 24,
    alignItems: "center",
    justifyContent: "center",
  },
  dialog: {
    width: "100%",
    maxWidth: 430,
    backgroundColor: "#1D3328",
    borderRadius: 22,
    padding: 24,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  dialogTitle: {
    fontSize: 21,
    fontWeight: "600",
    color: theme.colors.textPrimary,
    marginBottom: 14,
  },
  leave: { alignItems: "center", padding: 16, minHeight: 48 },
});
