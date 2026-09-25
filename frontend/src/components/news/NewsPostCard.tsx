import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  FlatList,
  Image,
  Linking,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useIsFocused } from "@react-navigation/native";
import { ResizeMode, Video } from "expo-av";
import * as FileSystem from "expo-file-system";
import * as Sharing from "expo-sharing";
import { downloadNewsAttachment } from "@/components/news/newsDownload";
import {
  formatFileSize,
  newsError,
  newsUrl,
  newsViewerSource,
} from "@/services/newsService";
import { theme } from "@/theme";
import { NewsMedia, NewsPost } from "@/types/news";

const dateLabel = (raw: string) => {
  const date = new Date(raw);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString("ru-RU", {
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
      });
};

const MediaPhoto = ({
  media,
  onPress,
  large,
}: {
  media: NewsMedia;
  onPress: () => void;
  large: boolean;
}) => {
  const [failed, setFailed] = useState(false);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Открыть фотографию ${media.name}`}
      style={[styles.photoTile, large && styles.photoLarge]}
    >
      {failed ? (
        <View style={styles.photoError}>
          <MaterialCommunityIcons
            name="image-off-outline"
            size={28}
            color={theme.colors.textMuted}
          />
          <Text style={styles.caption}>
            Обновите ленту, чтобы загрузить фото
          </Text>
        </View>
      ) : (
        <Image
          source={{ uri: newsUrl(media.thumbnail_url || media.url) }}
          style={styles.photo}
          resizeMode="cover"
          onError={() => setFailed(true)}
        />
      )}
      <View style={styles.expandIcon}>
        <MaterialCommunityIcons name="arrow-expand" size={17} color="#FFF8E6" />
      </View>
    </Pressable>
  );
};

const PhotoViewer = ({
  photos,
  initialIndex,
  onClose,
}: {
  photos: NewsMedia[];
  initialIndex: number;
  onClose: () => void;
}) => {
  const { width, height } = useWindowDimensions();
  const list = useRef<FlatList<NewsMedia>>(null);
  const [index, setIndex] = useState(initialIndex);
  const move = (next: number) => {
    if (next >= 0 && next < photos.length) {
      list.current?.scrollToIndex({ index: next, animated: true });
      setIndex(next);
    }
  };
  return (
    <Modal
      visible
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <SafeAreaView style={styles.viewer}>
        <View style={styles.viewerHeader}>
          <Text style={styles.viewerCount}>
            {index + 1} / {photos.length}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Закрыть фотографию"
            onPress={onClose}
            style={styles.iconButton}
          >
            <MaterialCommunityIcons name="close" size={28} color="#FFF8E6" />
          </Pressable>
        </View>
        <FlatList
          ref={list}
          data={photos}
          horizontal
          pagingEnabled
          initialNumToRender={1}
          maxToRenderPerBatch={1}
          windowSize={3}
          extraData={index}
          showsHorizontalScrollIndicator={false}
          initialScrollIndex={initialIndex}
          keyExtractor={(item) => String(item.id)}
          getItemLayout={(_, i) => ({
            length: width,
            offset: width * i,
            index: i,
          })}
          onMomentumScrollEnd={(event) =>
            setIndex(Math.round(event.nativeEvent.contentOffset.x / width))
          }
          renderItem={({ item, index: photoIndex }) => {
            const source = newsViewerSource(item, photoIndex === index);
            return (
              <ScrollView
                maximumZoomScale={3}
                minimumZoomScale={1}
                centerContent
                contentContainerStyle={{
                  width,
                  height: Math.max(160, height - 190),
                  justifyContent: "center",
                }}
              >
                {source ? (
                  <Image
                    accessibilityLabel={item.name}
                    source={{ uri: newsUrl(source) }}
                    resizeMode="contain"
                    resizeMethod={Platform.OS === "web" ? "auto" : "resize"}
                    style={{ width, height: Math.max(160, height - 190) }}
                  />
                ) : (
                  <View
                    style={{
                      width,
                      height: Math.max(160, height - 190),
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <ActivityIndicator color={theme.colors.textPrimary} />
                  </View>
                )}
              </ScrollView>
            );
          }}
        />
        <View style={styles.viewerFooter}>
          <Pressable
            disabled={index === 0}
            accessibilityRole="button"
            accessibilityLabel="Предыдущая фотография"
            onPress={() => move(index - 1)}
            style={[styles.iconButton, index === 0 && styles.disabled]}
          >
            <MaterialCommunityIcons
              name="chevron-left"
              size={30}
              color="#FFF8E6"
            />
          </Pressable>
          <Text numberOfLines={2} style={styles.viewerName}>
            {photos[index]?.name}
          </Text>
          <Pressable
            disabled={index === photos.length - 1}
            accessibilityRole="button"
            accessibilityLabel="Следующая фотография"
            onPress={() => move(index + 1)}
            style={[
              styles.iconButton,
              index === photos.length - 1 && styles.disabled,
            ]}
          >
            <MaterialCommunityIcons
              name="chevron-right"
              size={30}
              color="#FFF8E6"
            />
          </Pressable>
        </View>
      </SafeAreaView>
    </Modal>
  );
};

const DocumentAttachment = ({ media }: { media: NewsMedia }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const url = newsUrl(media.url);
      if (Platform.OS === "web") {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = media.name;
        anchor.rel = "noreferrer noopener";
        anchor.target = "_blank";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } else if (
        FileSystem.cacheDirectory &&
        (await Sharing.isAvailableAsync())
      ) {
        const uri = await downloadNewsAttachment(media);
        await Sharing.shareAsync(uri, {
          mimeType: media.mime_type,
          dialogTitle: media.name,
        });
      } else {
        await Linking.openURL(url);
      }
    } catch (reason) {
      setError(newsError(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Скачать ${media.name}, ${formatFileSize(media.size_bytes)}`}
        disabled={busy}
        onPress={() => void open()}
        style={styles.document}
      >
        <View style={styles.fileIcon}>
          <MaterialCommunityIcons
            name="file-document-outline"
            size={25}
            color={theme.colors.textPrimary}
          />
        </View>
        <View style={styles.documentBody}>
          <Text style={styles.documentName} numberOfLines={2}>
            {media.name}
          </Text>
          <Text style={styles.caption}>
            {busy
              ? "Загрузка…"
              : `${formatFileSize(media.size_bytes)} · Скачать файл`}
          </Text>
        </View>
        {busy ? (
          <ActivityIndicator color={theme.colors.textPrimary} />
        ) : (
          <MaterialCommunityIcons
            name="download"
            size={22}
            color={theme.colors.textSecondary}
          />
        )}
      </Pressable>
      {error ? (
        <Text accessibilityLiveRegion="polite" style={styles.error}>
          {error}
        </Text>
      ) : null}
    </View>
  );
};

type Props = {
  post: NewsPost;
  admin?: boolean;
  onEdit?: () => void;
  onDelete?: () => void;
  deleting?: boolean;
  compact?: boolean;
};
export const NewsPostCard = React.memo(
  ({ post, admin, onEdit, onDelete, deleting, compact }: Props) => {
    const focused = useIsFocused();
    const [photoIndex, setPhotoIndex] = useState<number | null>(null);
    const [activeVideo, setActiveVideo] = useState<string | null>(null);
    const [videoError, setVideoError] = useState<string | null>(null);
    const [expanded, setExpanded] = useState(!compact);
    const photos = post.media.filter((media) => media.kind === "image");
    const videos = post.media.filter((media) => media.kind === "video");
    const documents = post.media.filter((media) => media.kind === "document");
    useEffect(() => {
      if (!focused) {
        setActiveVideo(null);
        setPhotoIndex(null);
      }
    }, [focused]);
    useEffect(() => {
      const subscription = AppState.addEventListener("change", (state) => {
        if (state !== "active") setActiveVideo(null);
      });
      return () => subscription.remove();
    }, []);
    return (
      <View style={styles.card}>
        <View style={styles.postHeader}>
          <View style={styles.avatar}>
            <MaterialCommunityIcons
              name="pine-tree"
              size={27}
              color={theme.colors.textPrimary}
            />
          </View>
          <View style={styles.identity}>
            <Text style={styles.author}>
              {post.author_name || "Правление посёлка"}
            </Text>
            <Text style={styles.date}>
              {dateLabel(post.created_at)}
              {post.version > 1 ? " · изменено" : ""}
            </Text>
          </View>
          <View style={styles.badge}>
            <MaterialCommunityIcons
              name="check-decagram"
              size={18}
              color="#DCCA96"
            />
          </View>
        </View>
        {post.text ? (
          <View style={styles.textBlock}>
            <Text
              selectable
              numberOfLines={expanded ? undefined : 7}
              style={styles.postText}
            >
              {post.text}
            </Text>
            {compact ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => setExpanded(!expanded)}
                style={styles.readMore}
              >
                <Text style={styles.readMoreText}>
                  {expanded ? "Свернуть" : "Читать полностью"}
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {photos.length ? (
          <View style={styles.gallery}>
            {photos.map((media, index) => (
              <MediaPhoto
                key={`${media.id}-${media.url}`}
                media={media}
                large={
                  photos.length === 1 ||
                  (photos.length % 2 === 1 && index === 0)
                }
                onPress={() => setPhotoIndex(index)}
              />
            ))}
          </View>
        ) : null}
        {videos.map((media) => (
          <View key={media.id} style={styles.videoWrap}>
            {activeVideo === media.id && focused ? (
              <Video
                source={{ uri: newsUrl(media.url) }}
                style={styles.video}
                useNativeControls
                shouldPlay
                resizeMode={ResizeMode.CONTAIN}
                onError={() => {
                  setActiveVideo(null);
                  setVideoError(
                    "Не удалось воспроизвести видео. Обновите ленту или скачайте файл.",
                  );
                }}
              />
            ) : (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Воспроизвести видео ${media.name}`}
                onPress={() => {
                  setVideoError(null);
                  setActiveVideo(media.id);
                }}
                style={styles.videoPlaceholder}
              >
                {media.thumbnail_url ? (
                  <Image
                    source={{ uri: newsUrl(media.thumbnail_url) }}
                    style={StyleSheet.absoluteFillObject}
                  />
                ) : null}
                <View style={styles.playButton}>
                  <MaterialCommunityIcons
                    name="play"
                    size={34}
                    color="#1C3026"
                  />
                </View>
                <Text numberOfLines={1} style={styles.videoName}>
                  {media.name}
                </Text>
                <Text style={styles.caption}>
                  {formatFileSize(media.size_bytes)} · Нажмите для просмотра
                </Text>
              </Pressable>
            )}
            <DocumentAttachment media={media} />
          </View>
        ))}
        {videoError ? <Text style={styles.error}>{videoError}</Text> : null}
        {documents.length ? (
          <View style={styles.documents}>
            {documents.map((media) => (
              <DocumentAttachment key={media.id} media={media} />
            ))}
          </View>
        ) : null}
        {admin ? (
          <View style={styles.adminBar}>
            <Pressable
              accessibilityRole="button"
              onPress={onEdit}
              disabled={deleting}
              style={styles.adminAction}
            >
              <MaterialCommunityIcons
                name="pencil-outline"
                size={19}
                color={theme.colors.textSecondary}
              />
              <Text style={styles.adminText}>Изменить</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Удалить новость"
              onPress={onDelete}
              disabled={deleting}
              style={styles.adminAction}
            >
              {deleting ? (
                <ActivityIndicator color={theme.colors.danger} />
              ) : (
                <MaterialCommunityIcons
                  name="trash-can-outline"
                  size={20}
                  color={theme.colors.danger}
                />
              )}
              <Text style={[styles.adminText, { color: theme.colors.danger }]}>
                Удалить
              </Text>
            </Pressable>
          </View>
        ) : null}
        {photoIndex !== null ? (
          <PhotoViewer
            photos={photos}
            initialIndex={photoIndex}
            onClose={() => setPhotoIndex(null)}
          />
        ) : null}
      </View>
    );
  },
);
NewsPostCard.displayName = "NewsPostCard";

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: "rgba(219,193,134,0.25)",
    borderRadius: 24,
    padding: 18,
    backgroundColor: "rgba(23,42,34,0.96)",
    gap: 18,
    overflow: "hidden",
  },
  postHeader: { flexDirection: "row", gap: 12, alignItems: "center" },
  avatar: {
    width: 46,
    height: 46,
    borderRadius: 16,
    backgroundColor: "#304D3E",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "rgba(219,193,134,0.2)",
  },
  identity: { flex: 1, gap: 5 },
  author: { color: theme.colors.textPrimary, fontSize: 16, fontWeight: "600" },
  date: { color: theme.colors.textMuted, fontSize: 12, lineHeight: 17 },
  badge: { padding: 3 },
  textBlock: { gap: 4 },
  postText: { color: "#F4EAD0", fontSize: 16, lineHeight: 26 },
  readMore: { paddingVertical: 8, alignSelf: "flex-start" },
  readMoreText: { color: "#DCCA96", fontSize: 14, fontWeight: "600" },
  gallery: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  photoTile: {
    width: "49%",
    flexGrow: 1,
    aspectRatio: 1.15,
    overflow: "hidden",
    borderRadius: 12,
    backgroundColor: "#0E2018",
  },
  photoLarge: { width: "100%", aspectRatio: 1.55 },
  photo: { width: "100%", height: "100%" },
  photoError: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    padding: 12,
  },
  expandIcon: {
    position: "absolute",
    right: 10,
    bottom: 10,
    backgroundColor: "rgba(0,0,0,0.45)",
    padding: 6,
    borderRadius: 8,
  },
  documents: { gap: 8 },
  document: {
    minHeight: 68,
    padding: 12,
    gap: 12,
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "rgba(219,193,134,0.06)",
    borderRadius: 14,
  },
  fileIcon: {
    width: 40,
    height: 44,
    backgroundColor: "rgba(219,193,134,0.10)",
    borderRadius: 10,
    justifyContent: "center",
    alignItems: "center",
  },
  documentBody: { flex: 1, gap: 5 },
  documentName: {
    color: theme.colors.textPrimary,
    fontSize: 14,
    lineHeight: 20,
  },
  caption: { color: theme.colors.textMuted, fontSize: 12, lineHeight: 18 },
  videoWrap: { gap: 6 },
  video: {
    width: "100%",
    aspectRatio: 16 / 9,
    backgroundColor: "#06110C",
    borderRadius: 14,
  },
  videoPlaceholder: {
    width: "100%",
    aspectRatio: 16 / 9,
    backgroundColor: "#0E2018",
    borderRadius: 14,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    padding: 16,
  },
  playButton: {
    width: 62,
    height: 62,
    borderRadius: 31,
    backgroundColor: "#DCCA96",
    alignItems: "center",
    justifyContent: "center",
  },
  videoName: { color: theme.colors.textPrimary, fontSize: 14, marginTop: 6 },
  adminBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    borderTopWidth: 1,
    borderTopColor: "rgba(219,193,134,0.15)",
    paddingTop: 6,
  },
  adminAction: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    minHeight: 44,
    paddingHorizontal: 3,
  },
  adminText: { fontSize: 13, color: theme.colors.textSecondary },
  error: {
    color: theme.colors.danger,
    fontSize: 13,
    lineHeight: 20,
    marginTop: 5,
  },
  viewer: { flex: 1, backgroundColor: "#020705" },
  viewerHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 18,
    minHeight: 56,
  },
  viewerCount: { color: "#FFF8E6", fontSize: 15 },
  iconButton: {
    width: 48,
    height: 48,
    alignItems: "center",
    justifyContent: "center",
  },
  viewerFooter: {
    flexDirection: "row",
    alignItems: "center",
    padding: 12,
    gap: 12,
    minHeight: 70,
  },
  viewerName: { flex: 1, color: "#FFF8E6", textAlign: "center", fontSize: 13 },
  disabled: { opacity: 0.25 },
});
