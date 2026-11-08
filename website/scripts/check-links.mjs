import {readFile, readdir, access} from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve('dist');
const base = (process.env.FOUNDRY_BASE || '/').replace(/\/$/, '');
async function check(dir) {
  for (const e of await readdir(dir, {withFileTypes: true})) {
    const file = path.join(dir, e.name);
    if (e.isDirectory()) {
      await check(file);
      continue;
    }
    if (!e.name.endsWith('.html')) continue;
    const html = await readFile(file, 'utf8');
    for (const [, url] of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
      if (!url.startsWith('/') || url.startsWith('//')) continue;
      if (base && !url.startsWith(base + '/'))
        throw new Error(`Incorrect project base: ${url}`);
      let relative = url.slice(base.length).split(/[?#]/)[0];
      if (relative.endsWith('/')) relative += 'index.html';
      await access(path.join(root, relative));
    }
  }
}
await check(root);
console.log('Internal links and project base verified.');
