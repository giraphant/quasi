export const cardPath = (topicSlug, cardSlug) =>
  `vault/topics/${topicSlug}/cards/${cardSlug}.md`;

const CARD_SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

export const validCardSlug = (card) =>
  typeof card === "string" &&
  card.length >= 2 &&
  card.length <= 80 &&
  CARD_SLUG_RE.test(card);
