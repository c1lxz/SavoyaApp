const { withAppBuildGradle } = require("@expo/config-plugins");

// Read secrets at Gradle execution time; never interpolate passwords into source files.
module.exports = (config) =>
  withAppBuildGradle(config, (result) => {
    if (result.modResults.language !== "groovy")
      throw new Error("Savoya signing requires Groovy build.gradle");
    const marker = "// SAVOYA_RELEASE_SIGNING";
    const architectureMarker = "// SAVOYA_NATIVE_ARCHITECTURES";
    if (!result.modResults.contents.includes(architectureMarker)) {
      result.modResults.contents += `
${architectureMarker}
// The React Native AAR includes extra ABIs even when Expo only builds the
// requested native modules. Package the same ABI set as those modules.
def savoyaArchitectures = (findProperty("reactNativeArchitectures") ?: "armeabi-v7a,arm64-v8a").split(",").collect { it.trim() }.findAll { it }
android.defaultConfig.ndk.abiFilters.clear()
android.defaultConfig.ndk.abiFilters.addAll(savoyaArchitectures)
`;
    }
    if (!result.modResults.contents.includes(marker)) {
      result.modResults.contents += `
${marker}
def savoyaStore = System.getenv("SAVOYA_RELEASE_STORE_FILE")
if (savoyaStore) {
    android.signingConfigs.create("savoyaRelease") {
        storeFile file(savoyaStore)
        storePassword System.getenv("SAVOYA_RELEASE_STORE_PASSWORD")
        keyAlias System.getenv("SAVOYA_RELEASE_KEY_ALIAS")
        keyPassword System.getenv("SAVOYA_RELEASE_KEY_PASSWORD")
    }
    android.buildTypes.release.signingConfig = android.signingConfigs.savoyaRelease
} else {
    // Expo's template otherwise silently signs release builds with its debug key.
    android.buildTypes.release.signingConfig = null
}
`;
    }
    return result;
  });
