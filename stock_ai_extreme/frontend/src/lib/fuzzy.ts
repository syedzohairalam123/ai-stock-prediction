/**
 * Phase 13 — fuzzy matching for typo-tolerant search.
 *
 * The exact path (`searchGlobal`) stays as it is; this module layers a fuzzy,
 * typo-tolerant matcher on top of the same universe. Two real algorithms:
 *
 *   * **Levenshtein distance** — the standard edit distance (insertions,
 *     deletions, substitutions), computed with the two-row dynamic-programming
 *     optimisation so it is O(min(a,b)) in memory.
 *   * **BK-tree** — a metric tree over the vocabulary. Because Levenshtein is a
 *     metric, a BK-tree prunes whole subtrees whose distance from the query
 *     node already exceeds the budget, so a typo query does not scan every term.
 *
 * The distance budget scales with query length: a 3-letter query gets 1 edit
 * (otherwise "hbl" would start matching unrelated tickers), while anything from
 * 8 characters gets 3.
 */

/** Levenshtein edit distance between two strings (case-insensitive callers). */
export function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;

  // Keep the shorter string as the row so the two-row buffer stays small.
  let short = a;
  let long = b;
  if (short.length > long.length) {
    short = b;
    long = a;
  }

  let previous = new Array<number>(short.length + 1);
  let current = new Array<number>(short.length + 1);
  for (let i = 0; i <= short.length; i++) previous[i] = i;

  for (let j = 1; j <= long.length; j++) {
    current[0] = j;
    const longChar = long.charCodeAt(j - 1);
    for (let i = 1; i <= short.length; i++) {
      const cost = short.charCodeAt(i - 1) === longChar ? 0 : 1;
      const deletion = previous[i] + 1;
      const insertion = current[i - 1] + 1;
      const substitution = previous[i - 1] + cost;
      current[i] = Math.min(deletion, insertion, substitution);
    }
    const swap = previous;
    previous = current;
    current = swap;
  }
  return previous[short.length];
}

/** Normalized similarity in [0, 1] — 1 means identical. */
export function similarity(a: string, b: string): number {
  const longest = Math.max(a.length, b.length);
  if (longest === 0) return 1;
  return 1 - levenshtein(a, b) / longest;
}

/**
 * Split a searchable string into lowercase word tokens.
 *
 * Multi-word company names must be indexed word by word, otherwise a typo in
 * one word (`Habbib Bank`) is compared against the whole string and the edit
 * distance explodes. Also splits on `.`/`&`/`-` so `Oil & Gas` and `Meezan Bank`
 * both index their meaningful words.
 */
export function tokenizeTerms(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9]+/g)
    .filter((token) => token.length > 0);
}

/** Distance budget for a query, by length. */
export function distanceBudget(query: string): number {
  if (query.length <= 2) return 0;
  if (query.length <= 4) return 1;
  if (query.length <= 7) return 2;
  return 3;
}

interface BKNode {
  term: string;
  children: Map<number, BKNode>;
}

/**
 * BK-tree over a fixed vocabulary.
 *
 * `search` returns every stored term within `maxDistance` edits of the query,
 * with its distance, visiting only the subtrees the triangle inequality allows.
 */
export class BKTree {
  private root: BKNode | null = null;
  private size = 0;

  insert(term: string): void {
    const key = term.trim().toLowerCase();
    if (!key) return;
    if (this.root === null) {
      this.root = { term: key, children: new Map() };
      this.size += 1;
      return;
    }
    let node = this.root;
    for (;;) {
      const distance = levenshtein(key, node.term);
      if (distance === 0) return; // already indexed
      const child = node.children.get(distance);
      if (child === undefined) {
        node.children.set(distance, { term: key, children: new Map() });
        this.size += 1;
        return;
      }
      node = child;
    }
  }

  get length(): number {
    return this.size;
  }

  search(query: string, maxDistance: number): Array<{ term: string; distance: number }> {
    const key = query.trim().toLowerCase();
    if (!key || this.root === null || maxDistance < 0) return [];
    const out: Array<{ term: string; distance: number }> = [];
    const stack: BKNode[] = [this.root];
    while (stack.length > 0) {
      const node = stack.pop() as BKNode;
      const distance = levenshtein(key, node.term);
      if (distance <= maxDistance) out.push({ term: node.term, distance });
      const low = distance - maxDistance;
      const high = distance + maxDistance;
      for (const [edge, child] of node.children) {
        if (edge >= low && edge <= high) stack.push(child);
      }
    }
    out.sort((a, b) => a.distance - b.distance || a.term.localeCompare(b.term));
    return out;
  }
}

export interface FuzzyMatch<T> {
  item: T;
  /** Lowest edit distance across the item's indexed tokens. */
  distance: number;
  /** The token that matched (for the UI to explain the hit). */
  matchedTerm: string;
  /** Lower is better: exact 0, typo hits carry their distance minus length. */
  score: number;
}

/**
 * Rank `items` by fuzzy closeness of `query` against each item's tokens.
 *
 * Exact/substring hits are handled by the caller's fast path; this returns only
 * approximate matches, sorted by distance then token length (a nearer, longer
 * token wins over a short one at the same distance).
 */
export function fuzzyRank<T>(
  items: readonly T[],
  tokensFor: (item: T) => string[],
  query: string,
  options: { limit?: number; maxDistance?: number } = {}
): FuzzyMatch<T>[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const budget = options.maxDistance ?? distanceBudget(needle);
  const limit = options.limit ?? 20;

  // Every token is expanded into words so a multi-word name matches word by
  // word; the raw token is kept too so an exact symbol/name still indexes.
  const tokensOf = (item: T): string[] => {
    const out: string[] = [];
    for (const token of tokensFor(item)) {
      const trimmed = token.trim().toLowerCase();
      if (!trimmed) continue;
      if (!out.includes(trimmed)) out.push(trimmed);
      for (const word of tokenizeTerms(trimmed)) {
        if (!out.includes(word)) out.push(word);
      }
    }
    return out;
  };

  const vocabulary = new Set<string>();
  for (const item of items) {
    for (const token of tokensOf(item)) vocabulary.add(token);
  }

  const tree = new BKTree();
  for (const term of vocabulary) tree.insert(term);
  const candidates = tree.search(needle, budget);
  if (candidates.length === 0) return [];

  const byTerm = new Map(candidates.map((candidate) => [candidate.term, candidate.distance]));
  const matches: FuzzyMatch<T>[] = [];
  for (const item of items) {
    let best: { distance: number; term: string } | null = null;
    for (const key of tokensOf(item)) {
      const distance = byTerm.get(key);
      if (distance === undefined) continue;
      if (best === null || distance < best.distance || (distance === best.distance && key.length > best.term.length)) {
        best = { distance, term: key };
      }
    }
    if (best === null) continue;
    matches.push({ item, distance: best.distance, matchedTerm: best.term, score: best.distance - best.term.length / 100 });
  }

  matches.sort((a, b) => a.score - b.score);
  return matches.slice(0, limit);
}
