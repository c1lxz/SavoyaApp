const fs = require("fs");
const path = require("path");

module.exports = ({ config }) => {
  const preview = process.env.SAVOYA_BUILD_VARIANT === "preview";
  const candidate =
    process.env.SAVOYA_GOOGLE_SERVICES_FILE ||
    path.join(__dirname, "google-services.json");
  const googleServicesFile =
    !preview && fs.existsSync(candidate) ? path.resolve(candidate) : undefined;
  if (process.env.SAVOYA_REQUIRE_PUSH === "true" && !googleServicesFile) {
    throw new Error(
      "SAVOYA_GOOGLE_SERVICES_FILE must point to the Firebase Android configuration for com.savoya.app.",
    );
  }
  return {
    ...config,
    name: preview ? "Савоя · Тест" : config.name,
    android: {
      ...config.android,
      ...(preview ? { package: "com.savoya.app.preview" } : {}),
      ...(googleServicesFile ? { googleServicesFile } : {}),
    },
    extra: { ...config.extra, newsPushConfigured: Boolean(googleServicesFile) },
    plugins: [
      ...(config.plugins || []),
      ["expo-notifications", { color: "#98D37A", defaultChannel: "news" }],
      [
        "expo-image-picker",
        {
          photosPermission: "Выберите фото или видео для новости посёлка.",
          cameraPermission: false,
          microphonePermission: false,
        },
      ],
      "expo-document-picker",
      "./plugins/withReleaseSigning",
      ["./plugins/withPreviewNetwork", { enabled: preview }],
    ],
  };
};
