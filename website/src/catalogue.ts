import {existsSync, readFileSync} from 'node:fs';
export type Extension = {
  id: string;
  version: string;
  type: string;
  entry: string;
  description: string;
  plugin?: {
    kind: string;
    mode: 'mock' | 'adapter';
    transport: string;
    contract: string;
  };
  platforms: string[];
  permissions: string[];
  capabilities: Record<
    string,
    {description: string; input: unknown; output: unknown}
  >;
};
type Metadata = {
  id: string;
  versions: string[];
  yanked_versions: Record<string, string>;
};
const metadata = import.meta.glob('../../extensions/*/metadata.json', {
  eager: true,
  import: 'default',
}) as Record<string, Metadata>;
const manifests = import.meta.glob('../../extensions/*/*/manifest.json', {
  eager: true,
  import: 'default',
}) as Record<string, Extension>;
export const versionHistory = Object.fromEntries(
  Object.values(metadata).map(m => [
    m.id,
    m.versions.map(version => ({version, reason: m.yanked_versions[version]})),
  ]),
);
const compareVersions = (a: string, b: string) => {
  const aa = a.split('.').map(Number),
    bb = b.split('.').map(Number);
  return aa[0] - bb[0] || aa[1] - bb[1] || aa[2] - bb[2];
};
export const extensions = Object.values(metadata).flatMap(m => {
  const active = m.versions
    .filter(v => !m.yanked_versions[v])
    .sort(compareVersions);
  const latest = active.at(-1);
  return latest
    ? [manifests[`../../extensions/${m.id}/${latest}/manifest.json`]]
    : [];
});
export const descriptions: Record<string, string> = {
  'id-card-reader':
    '固定结构的模拟身份证信息：姓名、证件号、签发机关、有效期与照片字段。',
  camera: '枚举模拟摄像头并采集一帧 PNG，提供统一的图像数据结构。',
  ocr: '接收图像，返回固定结构的模拟文字、置信度和位置框。',
  'serial-port': '模拟串口设备的 UTF-8 请求响应，演示硬件通信的统一接口。',
  'text-utils':
    '统一换行符、清理首尾空白。一个无需原生依赖的纯 JavaScript 扩展。',
  'file-digest':
    '通过独立命令行程序计算文件 SHA-256，让原生能力保持清晰的接口。',
  'native-math':
    '通过 libffi 调用动态库。用显式 C ABI 声明连接 JavaScript 与原生代码。',
};
export const icons: Record<string, string> = {
  'id-card-reader': 'ID',
  camera: '◎',
  ocr: 'Aa',
  'serial-port': '⇄',
  'text-utils': '{ }',
  'file-digest': '>_',
  'native-math': 'λ',
};

const indexPath = `${process.cwd()}/public/registry/index.json`;
const index: {packages: {id: string; version: string}[]} | undefined =
  existsSync(indexPath)
    ? JSON.parse(readFileSync(indexPath, 'utf8'))
    : undefined;
export const isPublished = (id: string, version: string) =>
  index?.packages.some(p => p.id === id && p.version === version) ?? false;
export const hasRegistry = !!index;

export const typeLabels: Record<string, string> = {
  javascript: 'JavaScript',
  executable: '命令行',
  'native-library': '动态库',
};
export const platformLabels: Record<string, string> = {
  any: '全部受支持平台',
  'windows-x64': 'Windows x64',
  'macos-arm64': 'macOS arm64',
  'linux-x64': 'Linux x64',
  'linux-arm64': 'Linux arm64',
};

export const pluginKindLabels: Record<string, string> = {
  'id-card-reader': '身份证读卡器',
  camera: '摄像头',
  ocr: '文字识别',
  serial: '串口',
  printer: '打印机',
  'barcode-reader': '扫码器',
  nfc: 'NFC',
  sensor: '传感器',
  gpio: 'GPIO',
};
export const sampleCalls: Record<string, {capability: string; input: string}> =
  {
    'text-utils': {capability: 'normalize', input: '{"text":"  hello  "}'},
    'file-digest': {
      capability: 'digest',
      input: '{"path":"/absolute/path/to/file"}',
    },
    'native-math': {capability: 'add', input: '{"a":2,"b":3}'},
    'id-card-reader': {capability: 'read-card', input: '{}'},
    camera: {capability: 'capture', input: '{}'},
    ocr: {
      capability: 'recognize',
      input:
        '{"image":{"mimeType":"image/png","base64":"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP4DwQACfsD/Wj6HMwAAAAASUVORK5CYII="}}',
    },
    'serial-port': {capability: 'exchange', input: '{"message":"PING"}'},
  };
