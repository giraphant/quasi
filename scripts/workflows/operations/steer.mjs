const CARD_SLUG_PATTERN = "^[a-z0-9][a-z0-9-]*$";
const CARD_SLUG_SCHEMA = {
  type: "string",
  minLength: 2,
  maxLength: 80,
  pattern: CARD_SLUG_PATTERN,
};

export const STEER_SCHEMA = {
  type: "object",
  required: ["subquestions"],
  properties: {
    outline_written: { type: "boolean" },
    saturated: { type: "boolean" },
    subquestions: {
      type: "array",
      items: {
        type: "object",
        required: ["id", "coverage", "items", "cards"],
        properties: {
          id: { type: "string" },
          question: { type: "string" },
          coverage: { type: "string" },
          dossier: { type: "boolean" },
          page: { type: "string" },
          items: {
            type: "array",
            items: {
              type: "object",
              required: ["slug"],
              properties: {
                kind: { type: "string" },
                slug: { type: "string" },
                role: { type: "string" },
              },
            },
          },
          cards: { type: "array", items: CARD_SLUG_SCHEMA },
        },
      },
    },
    dirty: { type: "array", items: { type: "string" } },
    candidates: {
      type: "array",
      items: {
        type: "object",
        required: ["slug", "subq", "role"],
        properties: {
          kind: { type: "string" },
          slug: { type: "string" },
          title: { type: "string" },
          authors: { type: "array" },
          year: {},
          isbn: { type: "string" },
          doi: { type: "string" },
          oa_url: { type: "string" },
          journal: { type: "string" },
          subq: { type: "string" },
          role: { type: "string" },
        },
      },
    },
    web_tasks: {
      type: "array",
      items: {
        type: "object",
        required: ["subq", "query", "card_slug"],
        properties: {
          subq: { type: "string" },
          query: { type: "string" },
          note: { type: "string" },
          card_slug: CARD_SLUG_SCHEMA,
        },
      },
    },
    suggested_queries: { type: "array", items: { type: "string" } },
  },
};

export const itemPath = (item) =>
  item.kind === "book"
    ? `vault/books/${item.slug}/00-overview.md`
    : item.kind === "author"
      ? `vault/authors/${item.slug}.md`
      : item.kind === "talk"
        ? `vault/talks/${item.slug}/talk.md`
        : `vault/papers/${item.slug}.md`;

export const cardPath = (topicSlug, cardSlug) =>
  `vault/topics/${topicSlug}/cards/${cardSlug}.md`;

const CARD_SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;
export const validCardSlug = (card) =>
  typeof card === "string" &&
  card.length >= 2 &&
  card.length <= 80 &&
  CARD_SLUG_RE.test(card);

export const registered = (state) =>
  ((state && state.subquestions) || [])
    .flatMap((subquestion) => (subquestion && subquestion.cards) || [])
    .filter(validCardSlug);

export const pendingCards = (state, doneSlugs, limit) => {
  const used = new Set(doneSlugs);
  const tasks = [];
  let dropped = 0;
  for (const task of (state && state.web_tasks) || []) {
    if (
      !task ||
      !task.query ||
      !task.subq ||
      !validCardSlug(task.card_slug)
    )
      continue;
    if (used.has(task.card_slug)) continue;
    if (tasks.length >= limit) {
      dropped++;
      continue;
    }
    used.add(task.card_slug);
    tasks.push({
      subq: task.subq,
      query: task.query,
      note: task.note || "",
      card_slug: task.card_slug,
    });
  }
  return { tasks, dropped };
};

export const mergeItems = (subquestions, items) =>
  subquestions.map((subquestion) => {
    const merged = new Map(
      (subquestion.items || []).map((item) => [
        `${item.kind}:${item.slug}`,
        item,
      ]),
    );
    (items || [])
      .filter(
        (item) =>
          item.subq === subquestion.id && item.kind !== "author",
      )
      .forEach((item) =>
        merged.set(`${item.kind}:${item.slug}`, {
          kind: item.kind,
          slug: item.slug,
          role: item.role,
        }),
      );
    return { ...subquestion, items: [...merged.values()] };
  });

export const mergeCards = (subquestions, cards) =>
  subquestions.map((subquestion) => ({
    ...subquestion,
    cards: [
      ...new Set([
        ...(subquestion.cards || []),
        ...(cards || [])
          .filter((card) => card.subq === subquestion.id)
          .map((card) => card.card_slug),
      ]),
    ],
  }));

export function steerPrompt(
  slug,
  desc,
  round,
  snowSrc,
  seenSlugs,
  want,
  seeds,
  newCards,
) {
  const books = snowSrc
    .filter((item) => item.kind === "book")
    .map((item) => item.slug);
  const rest = snowSrc
    .filter((item) => item.kind !== "book")
    .map(itemPath);
  const members = snowSrc
    .filter((item) => item.subq)
    .map((item) => ({
      kind: item.kind,
      slug: item.slug,
      subq: item.subq,
      role: item.role,
    }));
  const cards = (newCards || []).map((card) => ({
    subq: card.subq,
    card_slug: card.card_slug,
    title: card.title,
    path: cardPath(slug, card.card_slug),
  }));
  return `topic_slug: ${slug}
topic: ${desc}
outline_path: vault/topics/${slug}/02-outline.md
round: ${round}
want: ${want}
seen_slugs: ${JSON.stringify(seenSlugs)}
snowball_book_slugs: ${JSON.stringify(books)}
snowball_paths: ${JSON.stringify(rest)}
snowball_members: ${JSON.stringify(members)}   # 已定向候选的 subq/role 原样并入成员表${cards.length ? `
new_cards: ${JSON.stringify(cards)}   # 本轮落地的证据卡,并入对应子问题的 cards(不是 items)` : ""}${seeds && seeds.length ? `
extra_queries: ${JSON.stringify(seeds)}   # 用户补的种子检索词,优先照这些搜` : ""}`;
}
