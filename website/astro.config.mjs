import {defineConfig} from 'astro/config';
export default defineConfig({
  site: process.env.FOUNDRY_SITE || 'https://foundry.invalid',
  base: process.env.FOUNDRY_BASE || '/',
  trailingSlash: 'always',
});
