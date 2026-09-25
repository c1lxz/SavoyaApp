const { withAndroidManifest, withDangerousMod, AndroidConfig } = require('@expo/config-plugins');
const fs = require('fs/promises');
const path = require('path');

module.exports = (config, { enabled = false } = {}) => {
  config = withAndroidManifest(config, (result) => {
    const application = AndroidConfig.Manifest.getMainApplicationOrThrow(result.modResults);
    if (enabled) {
      application.$['android:networkSecurityConfig'] = '@xml/savoya_preview_network_security';
      application.$['android:usesCleartextTraffic'] = 'false';
    } else if (application.$['android:networkSecurityConfig'] === '@xml/savoya_preview_network_security') {
      delete application.$['android:networkSecurityConfig'];
      application.$['android:usesCleartextTraffic'] = 'false';
    }
    return result;
  });
  return withDangerousMod(config, ['android', async (result) => {
    if (enabled) {
      const directory = path.join(result.modRequest.platformProjectRoot, 'app/src/main/res/xml');
      await fs.mkdir(directory, { recursive: true });
      await fs.writeFile(path.join(directory, 'savoya_preview_network_security.xml'), `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false" />
  <domain-config cleartextTrafficPermitted="true">
    <domain>127.0.0.1</domain>
    <domain>localhost</domain>
  </domain-config>
</network-security-config>
`);
    }
    return result;
  }]);
};
