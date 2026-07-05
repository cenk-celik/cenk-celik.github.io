import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  site: 'https://cenk-celik.github.io',
  integrations: [sitemap()],
  trailingSlash: 'ignore',
  build: {
    format: 'directory',
  },
});
