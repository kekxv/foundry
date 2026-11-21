import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

const out =
  process.argv[2] ?? fileURLToPath(new URL('../dist/', import.meta.url));
const repository = process.env.FOUNDRY_REPOSITORY ?? '';
if (repository && !/^[a-zA-Z0-9_-]+\/[a-zA-Z0-9_.-]+$/.test(repository)) {
  throw new Error('Invalid FOUNDRY_REPOSITORY');
}
await mkdir(out, {recursive: true});
for (const name of ['install.sh', 'install.ps1']) {
  const source = new URL(`../../installers/${name}`, import.meta.url);
  const script = (await readFile(source, 'utf8'))
    .replaceAll('\r\n', '\n')
    .replace('__FOUNDRY_REPOSITORY__', repository);
  await writeFile(join(out, name), script, {mode: 0o755});
}
