import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { API_BASE_URL } from "@/services/api/config";
import { apiRequest } from "@/services/api/httpClient";
import { getAccessToken } from "@/services/api/tokenStore";
import {
  NewsFile,
  NewsMedia,
  NewsPage,
  NewsPayload,
  NewsPost,
} from "@/types/news";

export const NEWS_FILE_LIMIT = 100 * 1024 * 1024;
export const NEWS_ATTACHMENT_LIMIT = 10;
export const NEWS_TEXT_LIMIT = 20000;

export const newsUrl = (path: string): string => {
  const base =
    Platform.OS === "web" && typeof window !== "undefined"
      ? new URL(API_BASE_URL || "/", window.location.origin).toString()
      : API_BASE_URL;
  const result = new URL(path, `${base.replace(/\/$/, "")}/`);
  const origin = new URL(base);
  if (
    result.origin !== origin.origin ||
    (result.protocol !== "https:" &&
      !["localhost", "127.0.0.1", "[::1]"].includes(result.hostname))
  ) {
    throw new Error("Небезопасная ссылка на вложение");
  }
  return result.toString();
};

export const getNews = (limit = 10, beforeId?: number) =>
  apiRequest<NewsPage>(
    `/api/news?limit=${limit}${beforeId ? `&before_id=${beforeId}` : ""}`,
  );
export const getNewsPost = (id: number) =>
  apiRequest<NewsPost>(`/api/news/${id}`);
export const getNewsMedia = (id: string) =>
  apiRequest<NewsMedia>(`/api/news/media/${id}`);
export const updateNews = (id: number, payload: NewsPayload, version: number) =>
  apiRequest<NewsPost>(`/api/news/${id}`, {
    method: "PUT",
    body: { ...payload, version },
  });
export const deleteNews = (post: NewsPost) =>
  apiRequest<void>(`/api/news/${post.id}?version=${post.version}`, {
    method: "DELETE",
  });
export const deleteUnusedMedia = (id: string) =>
  apiRequest<void>(`/api/news/media/${id}`, { method: "DELETE" });

export class PublicationError extends Error {
  constructor(
    message: string,
    public readonly uncertain: boolean,
  ) {
    super(message);
  }
}

const responseMessage = (raw: string, fallback: string): string => {
  try {
    const data = JSON.parse(raw) as { detail?: unknown; message?: string };
    if (typeof data.detail === "string") return data.detail;
    if (
      data.detail &&
      typeof data.detail === "object" &&
      "message" in data.detail
    )
      return String(data.detail.message);
    return data.message || fallback;
  } catch {
    return fallback;
  }
};

// A lost response does not imply a failed publication. Retry the exact payload
// with this persisted request ID so the server returns the original post.
export const publishNews = async (
  payload: NewsPayload,
  requestId: string,
): Promise<NewsPost> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(newsUrl("/api/news"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getAccessToken() || ""}`,
      },
      body: JSON.stringify({ ...payload, request_id: requestId }),
      signal: controller.signal,
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    const raw = await response.text();
    if (!response.ok)
      throw new PublicationError(
        responseMessage(raw, "Не удалось опубликовать новость"),
        response.status >= 500,
      );
    return JSON.parse(raw) as NewsPost;
  } catch (error) {
    if (error instanceof PublicationError) throw error;
    throw new PublicationError(
      "Не удалось получить ответ сервера. Проверьте соединение и повторите публикацию — дубликат не появится.",
      true,
    );
  } finally {
    clearTimeout(timer);
  }
};

export const uploadNewsFile = (
  file: NewsFile,
  onProgress: (value: number) => void,
) => {
  const xhr = new XMLHttpRequest();
  let reportedProgress = -1;
  const reportProgress = (value: number) => {
    if (value <= reportedProgress) return;
    reportedProgress = value;
    onProgress(value);
  };
  const promise = new Promise<NewsMedia>((resolve, reject) => {
    if (file.size && file.size > NEWS_FILE_LIMIT) {
      reject(new Error("Файл больше 100 МБ"));
      return;
    }
    const form = new FormData();
    if (Platform.OS === "web") {
      if (!file.file) {
        reject(new Error("Выберите файл заново"));
        return;
      }
      form.append("file", file.file, file.name);
    } else {
      form.append("file", {
        uri: file.uri,
        name: file.name,
        type: file.mimeType,
      } as unknown as Blob);
    }
    xhr.open("POST", newsUrl("/api/news/media"));
    xhr.setRequestHeader("Authorization", `Bearer ${getAccessToken() || ""}`);
    xhr.timeout = 10 * 60 * 1000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0)
        reportProgress(
          Math.max(
            0,
            Math.min(99, Math.round((event.loaded / event.total) * 100)),
          ),
        );
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(
          new Error(
            responseMessage(
              xhr.responseText,
              xhr.status === 413
                ? "Файл слишком большой"
                : "Не удалось загрузить файл",
            ),
          ),
        );
        return;
      }
      try {
        const media = JSON.parse(xhr.responseText) as NewsMedia;
        reportProgress(100);
        resolve(media);
      } catch {
        reject(
          new Error("Сервер вернул некорректный ответ. Повторите загрузку."),
        );
      }
    };
    xhr.onerror = () =>
      reject(new Error("Соединение прервалось. Повторите загрузку."));
    xhr.ontimeout = () =>
      reject(
        new Error("Загрузка заняла слишком много времени. Повторите попытку."),
      );
    xhr.onabort = () => reject(new Error("Загрузка отменена"));
    xhr.send(form);
  });
  return { promise, cancel: () => xhr.abort() };
};

export type NewsDraft = {
  text: string;
  media: NewsMedia[];
  requestId: string;
  pendingPayload?: NewsPayload;
};
// Transport progress and renewed signed URLs do not change an author's draft.
export const newsDraftContentKey = (draft: NewsDraft) =>
  JSON.stringify({
    text: draft.text,
    media_ids: draft.media.map((media) => media.id),
    requestId: draft.requestId,
    pendingPayload: draft.pendingPayload,
  });

// Adjacent gallery pages must never eagerly download the original attachment.
export const newsViewerSource = (
  media: NewsMedia,
  active: boolean,
): string | null => (active ? media.url : media.thumbnail_url);
const draftKey = (userId: string | number) => `savoya:news-draft:v1:${userId}`;
export const loadNewsDraft = async (
  userId: string | number,
): Promise<NewsDraft | null> => {
  try {
    const raw = await AsyncStorage.getItem(draftKey(userId));
    return raw ? (JSON.parse(raw) as NewsDraft) : null;
  } catch {
    return null;
  }
};
export const saveNewsDraft = (userId: string | number, draft: NewsDraft) =>
  AsyncStorage.setItem(draftKey(userId), JSON.stringify(draft));
export const clearNewsDraft = (userId: string | number) =>
  AsyncStorage.removeItem(draftKey(userId));
export const createNewsRequestId = () =>
  `news-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
export const newsError = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Не удалось выполнить действие. Попробуйте ещё раз.";
export const formatFileSize = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} МБ`
    : `${Math.max(1, Math.round(bytes / 1024))} КБ`;

// SDK 51's web pickers read every selected file as a data URL, including videos.
// Keep browser File objects and blob URLs instead to avoid that memory spike.
export const pickNewsWebFiles = (mediaOnly: boolean): Promise<NewsFile[]> =>
  new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = mediaOnly ? "image/*,video/*" : "*/*";
    input.style.display = "none";
    let settled = false;
    let focusTimer: ReturnType<typeof setTimeout> | undefined;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (focusTimer) clearTimeout(focusTimer);
      window.removeEventListener("focus", onFocus);
      const files = Array.from(input.files || []).map((file) => ({
        uri: URL.createObjectURL(file),
        file,
        name: file.name,
        mimeType: file.type || "application/octet-stream",
        size: file.size,
      }));
      input.remove();
      resolve(files);
    };
    const onFocus = () => {
      focusTimer = setTimeout(finish, 1000);
    };
    input.addEventListener("change", finish);
    input.addEventListener("cancel", finish);
    window.addEventListener("focus", onFocus);
    document.body.appendChild(input);
    input.click();
  });
