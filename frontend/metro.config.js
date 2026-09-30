const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
// Native build output and previous web exports are not JS source. On Windows,
// crawling them can cause thousands of extra reads and antivirus scans.
const escape = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const root = __dirname.split(path.sep).map(escape).join('[\\\\/]');
const generated = new RegExp(
  `^${root}[\\\\/](?:android|dist|\\.savoya-web-[a-f0-9]+)(?:[\\\\/]|$)`,
);
const existing = config.resolver.blockList;
config.resolver.blockList = [
  ...(Array.isArray(existing) ? existing : existing ? [existing] : []),
  generated,
];
module.exports = config;
