/**
 * Markdown-lite renderer for assistant answers (Phase 10, spec U).
 *
 * A small, dependency-free renderer that turns the model's structured output
 * into real React elements — never `dangerouslySetInnerHTML`, so nothing the
 * model returns can inject markup into the page (spec W).
 *
 * Supported
 *   - headings (`#` … `#####`)
 *   - bullet lists (`-`, `*`, `+`, nested by indentation)
 *   - ordered lists (`1.`)
 *   - GitHub-style tables (`| a | b |` + separator row)
 *   - fenced code blocks and inline `code`
 *   - blockquotes (`>`), horizontal rules (`---`)
 *   - **bold**, *italic*, [links](https://…) — http/https only
 *   - `[FACT]`, `[CALCULATION]`, `[INTERPRETATION]`, `[ESTIMATE]`,
 *     `[USER-SUPPLIED]` markers become labeled chips so a reading can never be
 *     mistaken for a measurement (spec I)
 *   - signed percentages and PKR amounts get tabular figures and
 *     direction colour
 */

import { Fragment, ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Inline parsing
// ---------------------------------------------------------------------------

const INLINE_PATTERN = new RegExp(
  [
    '(`[^`]+`)', // 1 code span
    '(\\*\\*[^*]+\\*\\*)', // 2 bold
    '(__[^_]+__)', // 3 bold
    '(\\*[^*\\n]+\\*)', // 4 italic
    '(\\[[^\\]]+\\]\\((?:https?:\\/\\/)[^)\\s]+\\))', // 5 link
    '(\\[(?:FACT|CALCULATION|INTERPRETATION|ESTIMATE|USER-SUPPLIED|OPINION)\\])', // 6 labels
    '(PKR\\s?-?\\d[\\d,]*(?:\\.\\d+)?)', // 7 currency
    '([+-]\\d[\\d,]*(?:\\.\\d+)?%)' // 8 signed percent
  ].join('|'),
  'i'
);

/** Only http(s) links survive; anything else stays plain text. */
function safeHref(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}

function labelChip(label: string): ReactNode {
  const kind = label.replace(/[[\]]/g, '').toUpperCase();
  const cls = kind === 'FACT' || kind === 'CALCULATION' ? 'ai-tag-fact' : 'ai-tag-est';
  return (
    <span className={cls} key={`${kind}`}>
      {kind === 'USER-SUPPLIED' ? 'USER INPUT' : kind}
    </span>
  );
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let index = 0;

  while (rest.length > 0) {
    const match = INLINE_PATTERN.exec(rest);
    if (!match || match.index === undefined) {
      out.push(rest);
      break;
    }

    if (match.index > 0) {
      out.push(rest.slice(0, match.index));
    }

    const token = match[0];
    const key = `${keyPrefix}-${index++}`;
    const [, code, boldStar, boldUnderscore, italicStar, link, label, currency, percent] = match;

    if (code) {
      out.push(<code key={key}>{code.slice(1, -1)}</code>);
    } else if (boldStar) {
      out.push(<strong key={key}>{boldStar.slice(2, -2)}</strong>);
    } else if (boldUnderscore) {
      out.push(<strong key={key}>{boldUnderscore.slice(2, -2)}</strong>);
    } else if (italicStar) {
      out.push(<em key={key}>{italicStar.slice(1, -1)}</em>);
    } else if (link) {
      const split = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(link);
      const href = split ? safeHref(split[2]) : null;
      if (split && href) {
        out.push(
          <a key={key} href={href} target="_blank" rel="noopener noreferrer nofollow">
            {split[1]}
          </a>
        );
      } else {
        out.push(link);
      }
    } else if (label) {
      out.push(<Fragment key={key}>{labelChip(label)}</Fragment>);
    } else if (currency) {
      out.push(
        <span className="ai-num" key={key}>
          {currency}
        </span>
      );
    } else if (percent) {
      out.push(
        <span className={percent.startsWith('-') ? 'ai-dn ai-num' : 'ai-up ai-num'} key={key}>
          {percent}
        </span>
      );
    } else {
      out.push(token);
    }

    rest = rest.slice(match.index + token.length);
  }

  return out;
}

const inlineText = (text: string, key: string): ReactNode =>
  text.length === 0 ? null : <Fragment key={key}>{renderInline(text, key)}</Fragment>;

// ---------------------------------------------------------------------------
// Block parsing
// ---------------------------------------------------------------------------

type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'quote'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'table'; head: string[]; rows: string[][] }
  | { kind: 'rule' };

const HEADING = /^(#{1,5})\s+(.*)$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const ORDERED = /^(\s*)\d+[.)]\s+(.*)$/;
const RULE = /^(-{3,}|\*{3,}|_{3,})$/;

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((cell) => cell.trim());
}

function isTableSeparator(line: string): boolean {
  return /^\s*\|?[\s:-]*-[\s|:-]*\|?\s*$/.test(line) && line.includes('-');
}

/** Split a markdown-ish answer into block tokens (no nesting beyond lists). */
export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ kind: 'paragraph', text: paragraph.join(' ').trim() });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push({ kind: 'list', ordered: list.ordered, items: list.items });
      list = null;
    }
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    // fenced code
    if (/^\s*```/.test(line)) {
      flushParagraph();
      flushList();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      blocks.push({ kind: 'code', text: body.join('\n') });
      continue;
    }

    if (line.trim() === '') {
      flushParagraph();
      flushList();
      continue;
    }

    // table: header row followed by a separator row
    if (line.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      flushParagraph();
      flushList();
      const head = splitRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      i -= 1;
      blocks.push({ kind: 'table', head, rows });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() });
      continue;
    }

    if (RULE.test(line.trim())) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'rule' });
      continue;
    }

    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'quote', text: quote[1].trim() });
      continue;
    }

    const bullet = BULLET.exec(line);
    const ordered = ORDERED.exec(line);
    if (bullet || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      const text = (bullet ? bullet[2] : ordered ? ordered[2] : '').trim();
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { ordered: isOrdered, items: [] };
      }
      list.items.push(text);
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();
  return blocks;
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

/**
 * Render an assistant answer. Always safe: the output is React elements built
 * from parsed text, never raw HTML.
 */
export function MarkdownContent({ text }: { text: string }): ReactNode {
  const blocks = parseBlocks(text ?? '');

  return (
    <div className="ai-md">
      {blocks.map((block, blockIndex) => {
        const key = `b${blockIndex}`;

        switch (block.kind) {
          case 'heading': {
            const Tag = (block.level <= 2 ? 'h3' : block.level === 3 ? 'h4' : 'h5') as 'h3';
            return <Tag key={key}>{renderInline(block.text, key)}</Tag>;
          }
          case 'paragraph':
            return <p key={key}>{renderInline(block.text, key)}</p>;
          case 'list': {
            const items = block.items.map((item, itemIndex) => (
              <li key={`${key}-${itemIndex}`}>{renderInline(item, `${key}-${itemIndex}`)}</li>
            ));
            return block.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>;
          }
          case 'quote':
            return (
              <blockquote key={key}>
                {renderInline(block.text, key)}
              </blockquote>
            );
          case 'code':
            return (
              <pre key={key}>
                <code>{block.text}</code>
              </pre>
            );
          case 'table':
            return (
              <div className="ai-md-table-wrap" key={key}>
                <table>
                  <thead>
                    <tr>
                      {block.head.map((cell, cellIndex) => (
                        <th key={`${key}-h${cellIndex}`}>{renderInline(cell, `${key}-h${cellIndex}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr key={`${key}-r${rowIndex}`}>
                        {row.map((cell, cellIndex) => (
                          <td key={`${key}-r${rowIndex}c${cellIndex}`}>
                            {renderInline(cell, `${key}-r${rowIndex}c${cellIndex}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case 'rule':
            return <hr key={key} />;
          default:
            return inlineText('', key);
        }
      })}
    </div>
  );
}

export default MarkdownContent;
