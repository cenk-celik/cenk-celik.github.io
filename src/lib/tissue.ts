/**
 * Tissue animation: a Voronoi "tissue section" whose cells occupy one of four
 * generic tumour cell states and switch between them over time (plasticity).
 *
 *  - hero   : a tissue blob on the right of the viewport, with wandering immune cells
 *  - banner : a wide strip of cells fading in from the right, used behind page titles
 *
 * The cursor perturbs nearby cells: they hop to a different state for a few
 * seconds, then relax back to whatever the drifting state field says.
 * State colours come from the --state-1..4 CSS tokens, so light/dark just works.
 */
import { Delaunay } from 'd3-delaunay';

export type TissueMode = 'hero' | 'banner';
type RGB = [number, number, number];

interface Cell {
  hx: number; hy: number; x: number; y: number;
  ph: number; sp: number;
  st: number; ov: number; ovT: number; ring: number;
  c: RGB;
}
interface Immune { x: number; y: number; a: number; v: number }

const NSTATES = 4;

// ---- smooth value noise -------------------------------------------------
const PERM = new Uint8Array(512);
{
  const a = [...Array(256).keys()];
  let s = 7;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  for (let i = 0; i < 512; i++) PERM[i] = a[i & 255];
}
const fade = (t: number) => t * t * (3 - 2 * t);
function vnoise(x: number, y: number) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const h = (i: number, j: number) => PERM[(PERM[i & 255] + j) & 255] / 255;
  const u = fade(xf), v = fade(yf);
  return (h(xi, yi) * (1 - u) + h(xi + 1, yi) * u) * (1 - v) +
         (h(xi, yi + 1) * (1 - u) + h(xi + 1, yi + 1) * u) * v;
}
function stateField(x: number, y: number, t: number) {
  const f = vnoise(x * 0.006 + 10 + t * 0.014, y * 0.006 + 10 - t * 0.011) * 0.7 + vnoise(x * 0.02, y * 0.02) * 0.3;
  return Math.min(0.999, Math.max(0, (f - 0.2) * 2.2));
}
const stateAt = (x: number, y: number, t: number) => Math.floor(stateField(x, y, t) * NSTATES);

// ---- colour -------------------------------------------------------------
function parseColour(v: string, fallback: RGB): RGB {
  const m = v.trim().match(/^#([0-9a-f]{6})$/i);
  if (!m) return fallback;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const mix = (a: RGB, b: RGB, t: number): RGB => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

function readPalette() {
  const cs = getComputedStyle(document.documentElement);
  const fallback: RGB[] = [[78, 112, 140], [112, 150, 122], [226, 176, 90], [217, 120, 92]];
  return {
    states: fallback.map((f, i) => parseColour(cs.getPropertyValue(`--state-${i + 1}`), f)),
    text: cs.getPropertyValue('--color-text').trim() || '#ece7e2',
    accent: cs.getPropertyValue('--color-accent').trim() || '#d98a6c',
  };
}

// ---- main ---------------------------------------------------------------
export function mountTissue(canvas: HTMLCanvasElement, mode: TissueMode = 'hero'): () => void {
  const host = canvas.parentElement as HTMLElement;
  const ctx = canvas.getContext('2d');
  if (!ctx) return () => {};
  const g = ctx; // non-null alias for closures

  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let pal = readPalette();

  let W = 0, H = 0, cx = 0, cy = 0, R = 0;
  let cells: Cell[] = [];
  let immune: Immune[] = [];
  let outline: (a: number) => number = () => 1;
  let alphaAt: (x: number, y: number) => number = () => 1;
  const mouse = { x: -1e4, y: -1e4, on: false };

  let raf = 0, last = 0, t0 = 0, running = false, onscreen = true;

  function build() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = host.clientWidth; H = host.clientHeight;
    if (!W || !H) return;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);

    const narrow = W < 700;
    let inside: (x: number, y: number) => boolean;
    let cellSize: number;
    let region: [number, number, number, number]; // sampling box
    let densAt: (x: number, y: number) => number = () => 1;

    if (mode === 'hero') {
      // Narrow screens: text on top, tissue anchored in its own area at the bottom
      R = narrow ? Math.min(W * 0.4, 150) : Math.min(W * 0.27, H * 0.4);
      cx = narrow ? W * 0.5 : W * 0.68;
      cy = narrow ? H - R * 1.15 - 56 : H * 0.5;
      outline = (a) => R * (0.86 + 0.28 * vnoise(Math.cos(a) * 1.3 + 5, Math.sin(a) * 1.3 + 5));
      inside = (x, y) => Math.hypot(x - cx, y - cy) < outline(Math.atan2(y - cy, x - cx)) * 1.05;
      alphaAt = (x, y) => {
        const rim = Math.hypot(x - cx, y - cy) / outline(Math.atan2(y - cy, x - cx));
        return Math.min(1, Math.max(0, (1.12 - rim) * 5));
      };
      const target = narrow ? 520 : 1100;
      cellSize = Math.sqrt((Math.PI * R * R) / target);
      region = [cx - R * 1.3, cy - R * 1.3, cx + R * 1.3, cy + R * 1.3];
      densAt = (x, y) => 0.55 + 0.45 * Math.min(1, Math.hypot(x - cx, y - cy) / R);
    } else {
      cx = W / 2; cy = H / 2; R = Math.max(W, H);
      outline = () => R;
      inside = (x, y) => x > -20 && x < W + 20 && y > -20 && y < H + 20;
      alphaAt = (x) => {
        const f = Math.min(1, Math.max(0, (x / W - (narrow ? 0.05 : 0.38)) * (narrow ? 1.6 : 2.0)));
        return f * f * (3 - 2 * f) * 0.9;
      };
      cellSize = narrow ? 20 : 24;
      region = [-20, -20, W + 20, H + 20];
    }

    // Poisson-disc-ish sampling via rejection on a spatial hash
    const minD = cellSize * 0.62;
    const bucket = minD;
    const grid = new Map<string, number[]>();
    const key = (i: number, j: number) => `${i},${j}`;
    const pts: { hx: number; hy: number }[] = [];
    const maxTries = 40000;
    const area = (region[2] - region[0]) * (region[3] - region[1]);
    const wanted = mode === 'hero' ? (narrow ? 520 : 1100) : Math.ceil(area / (cellSize * cellSize));
    for (let n = 0; n < maxTries && pts.length < wanted; n++) {
      const x = region[0] + Math.random() * (region[2] - region[0]);
      const y = region[1] + Math.random() * (region[3] - region[1]);
      if (!inside(x, y)) continue;
      const d = minD / densAt(x, y);
      const gi = Math.floor(x / bucket), gj = Math.floor(y / bucket);
      const reach = Math.ceil(d / bucket) + 1;
      let ok = true;
      for (let i = gi - reach; i <= gi + reach && ok; i++)
        for (let j = gj - reach; j <= gj + reach && ok; j++) {
          const lst = grid.get(key(i, j));
          if (!lst) continue;
          for (const idx of lst) {
            const p = pts[idx];
            if ((p.hx - x) ** 2 + (p.hy - y) ** 2 < d * d) { ok = false; break; }
          }
        }
      if (!ok) continue;
      pts.push({ hx: x, hy: y });
      const k = key(gi, gj);
      (grid.get(k) ?? grid.set(k, []).get(k)!).push(pts.length - 1);
    }

    cells = pts.map((p) => {
      const st = stateAt(p.hx, p.hy, 0);
      return { hx: p.hx, hy: p.hy, x: p.hx, y: p.hy, ph: Math.random() * 6.283, sp: 0.15 + Math.random() * 0.25,
               st, ov: -1, ovT: 0, ring: 0, c: pal.states[st].slice() as RGB };
    });
    immune = mode === 'hero'
      ? Array.from({ length: narrow ? 6 : 14 }, () => {
          const p = cells[Math.floor(Math.random() * cells.length)];
          return { x: p.hx, y: p.hy, a: Math.random() * 6.283, v: 6 + Math.random() * 8 };
        })
      : [];
  }

  function frame(now: number) {
    if (!running) return;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    draw(dt, (now - t0) / 1000);
    if (!reduce && onscreen && !document.hidden) raf = requestAnimationFrame(frame);
    else running = false;
  }

  function draw(dt: number, t: number) {
    if (!cells.length) return;
    const mr = Math.max(90, (mode === 'hero' ? R : H) * 0.28);

    for (const p of cells) {
      p.x = p.hx + Math.sin(t * p.sp + p.ph) * 2.4;
      p.y = p.hy + Math.cos(t * p.sp * 0.8 + p.ph) * 2.4;
      if (mouse.on && p.ovT <= 0 && Math.hypot(p.x - mouse.x, p.y - mouse.y) < mr && Math.random() < dt * 3) {
        p.ov = (p.st + 1 + Math.floor(Math.random() * (NSTATES - 1))) % NSTATES;
        p.ovT = 4 + Math.random() * 4;
      }
      if (p.ovT > 0) { p.ovT -= dt; if (p.ovT <= 0) p.ov = -1; }
      const next = p.ov >= 0 ? p.ov : stateAt(p.hx, p.hy, t);
      if (next !== p.st) { p.st = next; p.ring = 1; }
      if (p.ring > 0) p.ring = Math.max(0, p.ring - dt * 0.9);
      p.c = mix(p.c, pal.states[p.st], Math.min(1, dt * 3));
    }
    for (const m of immune) {
      m.a += (Math.random() - 0.5) * dt * 3;
      m.x += Math.cos(m.a) * m.v * dt; m.y += Math.sin(m.a) * m.v * dt;
      const ang = Math.atan2(m.y - cy, m.x - cx);
      if (Math.hypot(m.x - cx, m.y - cy) > outline(ang) * 0.98) m.a = ang + Math.PI;
    }

    g.clearRect(0, 0, W, H);
    const delaunay = Delaunay.from(cells, (p) => p.x, (p) => p.y);
    const bounds: [number, number, number, number] = mode === 'hero'
      ? [cx - R * 1.4, cy - R * 1.4, cx + R * 1.4, cy + R * 1.4]
      : [0, 0, W, H];
    const vor = delaunay.voronoi(bounds);

    g.save();
    g.lineJoin = 'round';
    if (mode === 'hero') {          // clip hull cells to the tissue outline
      g.beginPath();
      for (let a = 0; a <= 6.2832; a += 0.05) {
        const r = outline(a) * 1.02;
        const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
        a ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.closePath(); g.clip();
    }
    for (let i = 0; i < cells.length; i++) {
      const p = cells[i];
      const poly = vor.cellPolygon(i);
      if (!poly) continue;
      const alpha = alphaAt(p.hx, p.hy) * 0.9;
      if (alpha < 0.02) continue;
      g.beginPath();
      for (let k = 0; k < poly.length; k++) {
        const x = p.x + (poly[k][0] - p.x) * 0.88, y = p.y + (poly[k][1] - p.y) * 0.88;
        k ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.closePath();
      g.fillStyle = `rgba(${p.c[0] | 0},${p.c[1] | 0},${p.c[2] | 0},${alpha})`;
      g.fill();
      if (p.ring > 0) {
        g.strokeStyle = `rgba(255,240,225,${p.ring * 0.85 * alpha})`;
        g.lineWidth = 1.5;
        g.stroke();
      }
    }
    g.restore();

    g.fillStyle = pal.text;
    g.globalAlpha = 0.85;
    for (const m of immune) { g.beginPath(); g.arc(m.x, m.y, 2.6, 0, 6.283); g.fill(); }
    g.globalAlpha = 1;
  }

  function start() {
    if (running || reduce) return;
    running = true; last = performance.now();
    raf = requestAnimationFrame(frame);
  }

  // ---- wiring ----
  const onMove = (e: PointerEvent) => {
    const r = canvas.getBoundingClientRect();
    mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top; mouse.on = true;
  };
  const onLeave = () => { mouse.on = false; };
  const ro = new ResizeObserver(() => { build(); if (reduce) draw(0, 0); });
  const io = new IntersectionObserver(([e]) => { onscreen = e.isIntersecting; if (onscreen) start(); });
  const mo = new MutationObserver(() => { pal = readPalette(); if (reduce) draw(0, 0); });
  const onVis = () => { if (!document.hidden) start(); };

  host.addEventListener('pointermove', onMove);
  host.addEventListener('pointerleave', onLeave);
  document.addEventListener('visibilitychange', onVis);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  ro.observe(host);
  io.observe(host);

  t0 = performance.now();
  build();
  if (reduce) draw(0, 0); else start();

  return () => {
    running = false; cancelAnimationFrame(raf);
    ro.disconnect(); io.disconnect(); mo.disconnect();
    host.removeEventListener('pointermove', onMove);
    host.removeEventListener('pointerleave', onLeave);
    document.removeEventListener('visibilitychange', onVis);
  };
}
