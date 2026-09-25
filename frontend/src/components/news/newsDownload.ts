import * as FileSystem from "expo-file-system";
import { newsUrl } from "@/services/newsService";
import { NewsMedia } from "@/types/news";

const CACHE_RETENTION_SECONDS = 7 * 24 * 60 * 60;
let cleanup: Promise<void> | null = null;

const prepareDownloadDirectory = async (): Promise<string> => {
  if (!FileSystem.cacheDirectory)
    throw new Error("Хранилище устройства недоступно");
  const directory = `${FileSystem.cacheDirectory}savoya-news-downloads-v1/`;
  await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
  if (!cleanup) {
    cleanup = (async () => {
      const names = await FileSystem.readDirectoryAsync(directory);
      const cutoff = Date.now() / 1000 - CACHE_RETENTION_SECONDS;
      // Only this feature's cache files are eligible. Sharing targets may open
      // content URIs after shareAsync resolves, so retain recent files.
      for (let offset = 0; offset < names.length; offset += 20) {
        await Promise.allSettled(
          names.slice(offset, offset + 20).map(async (name) => {
            if (
              !name.startsWith("news-") ||
              name.includes("/") ||
              name.includes("\\")
            )
              return;
            const path = directory + name;
            const info = await FileSystem.getInfoAsync(path);
            if (
              info.exists &&
              !info.isDirectory &&
              info.modificationTime < cutoff
            ) {
              await FileSystem.deleteAsync(path, { idempotent: true });
            }
          }),
        );
      }
    })().finally(() => {
      cleanup = null;
    });
  }
  // Cache maintenance failure must not block a fresh file download.
  await cleanup.catch(() => {});
  return directory;
};

export const downloadNewsAttachment = async (
  media: NewsMedia,
): Promise<string> => {
  const directory = await prepareDownloadDirectory();
  const safeName =
    media.name.replace(/[^a-zA-Zа-яА-ЯёЁ0-9._-]/g, "_").slice(-80) ||
    "attachment";
  const path = `${directory}news-${media.id}-${Date.now()}-${safeName}`;
  const temporaryPath = `${path}.part`;
  try {
    const result = await FileSystem.downloadAsync(
      newsUrl(media.url),
      temporaryPath,
    );
    if (result.status !== 200)
      throw new Error(
        "Не удалось скачать файл. Обновите ленту и попробуйте ещё раз.",
      );
    await FileSystem.moveAsync({ from: temporaryPath, to: path });
    return path;
  } catch (error) {
    await FileSystem.deleteAsync(temporaryPath, { idempotent: true }).catch(
      () => {},
    );
    throw error;
  }
};
