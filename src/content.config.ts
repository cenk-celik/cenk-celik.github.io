import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// ---------------------------------------------------------------------------
// Human-edited Markdown collections.
// To add an entry: copy an existing file in that folder, change the
// front matter and text, commit. No other file needs to change.
// ---------------------------------------------------------------------------

const research = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/research' }),
  schema: z.object({
    title: z.string(),
    order: z.number().default(99),
  }),
});

const teaching = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/teaching' }),
  schema: z.object({
    title: z.string(),
    year: z.number(),
    organisation: z.string(),
    location: z.string().optional(),
    status: z.enum(['upcoming', 'past']),
    link: z.string().url().optional(),
    linkLabel: z.string().optional(),
  }),
});

const news = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/news' }),
  schema: z.object({
    date: z.coerce.date(),
  }),
});

const bio = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/bio' }),
  schema: z.object({
    role: z.string(),
    institution: z.string(),
    lab: z.string().optional(),
    labUrl: z.string().url().optional(),
  }),
});

export const collections = {
  research,
  teaching,
  news,
  bio,
};
