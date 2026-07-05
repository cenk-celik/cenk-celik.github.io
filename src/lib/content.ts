import { getCollection, type CollectionEntry } from 'astro:content';
import publicationsData from '../content/publications/publications.json';
import publicationMetrics from '../content/publications/metrics.json';
import repoCache from '../content/repos/cache.json';
import repoFeatured from '../content/repos/featured.json';
import blueskyCache from '../content/bluesky/cache.json';

export type Publication = {
  id: string;
  title: string;
  authors: string[];
  year: number;
  venue: string;
  venueAbbr?: string;
  type: 'journal' | 'review' | 'preprint' | 'book-chapter' | 'protocol' | 'abstract';
  doi?: string | null;
  url: string;
  pubmedUrl?: string | null;
  preprintUrl?: string | null;
  citations?: number;
  selected: boolean;
};

export async function getSortedNews(): Promise<CollectionEntry<'news'>[]> {
  const items = await getCollection('news');
  return items.sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());
}

export async function getSortedResearch(): Promise<CollectionEntry<'research'>[]> {
  const items = await getCollection('research');
  return items.sort((a, b) => a.data.order - b.data.order);
}

export async function getSortedTeaching(): Promise<CollectionEntry<'teaching'>[]> {
  const items = await getCollection('teaching');
  return items.sort((a, b) => b.data.year - a.data.year);
}

export function getPublications(): Publication[] {
  return [...(publicationsData as Publication[])].sort((a, b) => {
    if (b.year !== a.year) return b.year - a.year;
    return (b.citations ?? 0) - (a.citations ?? 0);
  });
}

export function getFeaturedPublications(): Publication[] {
  return getPublications().filter((p) => p.selected);
}

export function getPublicationMetrics() {
  return publicationMetrics as { citations: number; hIndex: number; i10Index: number; updated: string };
}

export type RepoEntry = {
  slug: string;
  name: string;
  fullName: string;
  description: string | null;
  url: string;
  stars: number;
  language: string | null;
  updatedAt: string;
  topics: string[];
  highlight?: string;
};

export function getRepos(): RepoEntry[] {
  const featured = repoFeatured as { repo: string; highlight?: string }[];
  const cache = repoCache as Record<string, Omit<RepoEntry, 'slug' | 'highlight'>>;

  const entries: RepoEntry[] = [];
  for (const { repo, highlight } of featured) {
    const entry = cache[repo];
    if (!entry) continue;
    entries.push({ slug: repo, highlight, ...entry });
  }

  return entries.sort((a, b) => new Date(b.updatedAt).valueOf() - new Date(a.updatedAt).valueOf());
}

export type BlueskyPostData = {
  uri: string;
  url: string;
  text: string;
  createdAt: string;
  likeCount: number;
  repostCount: number;
  images: { url: string; alt: string }[];
  repostOf?: string;
};

export function getBlueskyPosts(limit = 3): { posts: BlueskyPostData[]; fetchedAt: string | null; ok: boolean } {
  const cache = blueskyCache as { posts: BlueskyPostData[]; fetchedAt: string | null };
  if (!cache?.posts?.length) {
    return { posts: [], fetchedAt: null, ok: false };
  }
  return { posts: cache.posts.slice(0, limit), fetchedAt: cache.fetchedAt, ok: true };
}

export function formatDate(date: Date): string {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
}

export function formatMonthYear(date: Date): string {
  return new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric' }).format(date);
}

export function relativeTime(dateInput: string | Date): string {
  const date = typeof dateInput === 'string' ? new Date(dateInput) : dateInput;
  const seconds = Math.round((date.valueOf() - Date.now()) / 1000);
  const divisions: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 60 * 60 * 24 * 365],
    ['month', 60 * 60 * 24 * 30],
    ['week', 60 * 60 * 24 * 7],
    ['day', 60 * 60 * 24],
    ['hour', 60 * 60],
    ['minute', 60],
  ];
  const rtf = new Intl.RelativeTimeFormat('en-GB', { numeric: 'auto' });
  for (const [unit, secondsInUnit] of divisions) {
    if (Math.abs(seconds) >= secondsInUnit) {
      return rtf.format(Math.round(seconds / secondsInUnit), unit);
    }
  }
  return rtf.format(Math.round(seconds), 'second');
}
