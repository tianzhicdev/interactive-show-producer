/**
 * Chinese-aware text chunking for large story files.
 * Smart chunking with:
 * - 30K char target per chunk (good for Gemini Flash)
 * - 10% overlap (~3K chars) for context preservation at boundaries
 * - Chapter detection for Chinese novels
 * - Split priority: chapter markers → paragraph breaks → sentence endings → hard cut
 */

const TARGET_CHUNK_SIZE = 30_000;
const OVERLAP_SIZE = 3_000;

/**
 * Chapter marker regex for Chinese novels.
 * Matches: 第X章/节/回/卷/篇, 序章, 楔子, 番外, etc.
 */
const CHAPTER_REGEX = /^(?:第[零一二三四五六七八九十百千万\d]+[章节回卷篇部集]|序章|序幕|楔子|番外|尾声|终章|后记|前言|引子|引言)/m;

export interface ChunkResult {
  content: string;
  chapterTitle: string | null;
}

/**
 * Split a full story text into chunks with overlap and chapter awareness.
 */
export function chunkStoryText(text: string): ChunkResult[] {
  // Phase 1: Split at chapter markers
  const chapters = splitAtChapters(text);

  // Phase 2: Merge small consecutive chapters up to target size
  const merged = mergeSmallChapters(chapters);

  // Phase 3: Split oversized chapters at paragraph/sentence boundaries
  const chunks: ChunkResult[] = [];
  for (const chapter of merged) {
    if (chapter.content.length <= TARGET_CHUNK_SIZE) {
      chunks.push(chapter);
    } else {
      const subChunks = splitWithOverlap(chapter.content, chapter.chapterTitle);
      chunks.push(...subChunks);
    }
  }

  // Phase 4: Apply overlap between chunks (from different chapters too)
  return applyOverlapBetweenChunks(chunks);
}

function splitAtChapters(text: string): ChunkResult[] {
  const lines = text.split("\n");
  const chapters: ChunkResult[] = [];
  let currentContent = "";
  let currentTitle: string | null = null;

  for (const line of lines) {
    if (CHAPTER_REGEX.test(line.trim())) {
      if (currentContent.trim()) {
        chapters.push({ content: currentContent.trim(), chapterTitle: currentTitle });
      }
      currentTitle = line.trim();
      currentContent = line + "\n";
    } else {
      currentContent += line + "\n";
    }
  }

  if (currentContent.trim()) {
    chapters.push({ content: currentContent.trim(), chapterTitle: currentTitle });
  }

  if (chapters.length === 0) {
    chapters.push({ content: text.trim(), chapterTitle: null });
  }

  return chapters;
}

/**
 * Merge consecutive small chapters into chunks up to TARGET_CHUNK_SIZE.
 * Preserves the first chapter title in each merged group.
 */
function mergeSmallChapters(chapters: ChunkResult[]): ChunkResult[] {
  const result: ChunkResult[] = [];
  let currentContent = "";
  let currentTitle: string | null = null;

  for (const chapter of chapters) {
    // If adding this chapter would exceed target, flush current buffer first
    if (currentContent.length > 0 && currentContent.length + chapter.content.length + 2 > TARGET_CHUNK_SIZE) {
      result.push({ content: currentContent.trim(), chapterTitle: currentTitle });
      currentContent = "";
      currentTitle = null;
    }

    // If a single chapter already exceeds target, push it as-is (will be split later)
    if (currentContent.length === 0 && chapter.content.length > TARGET_CHUNK_SIZE) {
      result.push(chapter);
      continue;
    }

    if (currentContent.length === 0) {
      currentTitle = chapter.chapterTitle;
    }
    currentContent += (currentContent ? "\n\n" : "") + chapter.content;
  }

  if (currentContent.trim()) {
    result.push({ content: currentContent.trim(), chapterTitle: currentTitle });
  }

  return result;
}

function splitWithOverlap(text: string, chapterTitle: string | null): ChunkResult[] {
  const paragraphs = text.split(/\n\s*\n/);
  const results: ChunkResult[] = [];
  let currentChunk = "";

  for (const paragraph of paragraphs) {
    const trimmed = paragraph.trim();
    if (!trimmed) continue;

    if (currentChunk.length + trimmed.length + 2 > TARGET_CHUNK_SIZE && currentChunk.length > 0) {
      results.push({ content: currentChunk.trim(), chapterTitle });
      currentChunk = "";
    }

    if (trimmed.length > TARGET_CHUNK_SIZE) {
      if (currentChunk.trim()) {
        results.push({ content: currentChunk.trim(), chapterTitle });
        currentChunk = "";
      }
      const sentenceChunks = splitAtSentences(trimmed, chapterTitle);
      results.push(...sentenceChunks);
      continue;
    }

    currentChunk += (currentChunk ? "\n\n" : "") + trimmed;
  }

  if (currentChunk.trim()) {
    results.push({ content: currentChunk.trim(), chapterTitle });
  }

  return results;
}

function splitAtSentences(text: string, chapterTitle: string | null): ChunkResult[] {
  const results: ChunkResult[] = [];
  let remaining = text;

  while (remaining.length > TARGET_CHUNK_SIZE) {
    let cutPoint = TARGET_CHUNK_SIZE;
    const searchRegion = remaining.slice(Math.floor(TARGET_CHUNK_SIZE * 0.7), TARGET_CHUNK_SIZE);
    const lastSentenceEnd = searchRegion.search(/[。！？；…][^。！？；…]*$/);

    if (lastSentenceEnd >= 0) {
      cutPoint = Math.floor(TARGET_CHUNK_SIZE * 0.7) + lastSentenceEnd + 1;
    }

    results.push({ content: remaining.slice(0, cutPoint).trim(), chapterTitle });
    remaining = remaining.slice(cutPoint).trim();
  }

  if (remaining.trim()) {
    results.push({ content: remaining.trim(), chapterTitle });
  }

  return results;
}

function applyOverlapBetweenChunks(chunks: ChunkResult[]): ChunkResult[] {
  if (chunks.length <= 1) return chunks;

  const result: ChunkResult[] = [chunks[0]];
  for (let i = 1; i < chunks.length; i++) {
    const prevContent = chunks[i - 1].content;
    const overlapText = extractOverlapSuffix(prevContent, OVERLAP_SIZE);
    result.push({
      content: overlapText + "\n\n---\n\n" + chunks[i].content,
      chapterTitle: chunks[i].chapterTitle,
    });
  }

  return result;
}

function extractOverlapSuffix(text: string, targetSize: number): string {
  if (text.length <= targetSize) return text;

  const tail = text.slice(-targetSize);
  const paraBreak = tail.indexOf("\n\n");
  if (paraBreak >= 0 && paraBreak < targetSize * 0.5) {
    return tail.slice(paraBreak + 2);
  }

  const match = tail.match(/[。！？；…]+/);
  if (match && match.index !== undefined && match.index < targetSize * 0.3) {
    return tail.slice(match.index + match[0].length).trim();
  }

  return tail;
}
