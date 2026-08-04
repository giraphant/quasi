import {
  AUTHOR_OPERATION_IDENTITIES,
  BOOK_OPERATION_IDENTITIES,
  PAPER_OPERATION_IDENTITIES,
  TALK_OPERATION_IDENTITIES,
  TOPIC_OPERATION_IDENTITIES,
  TRANSLATION_OPERATION_IDENTITIES,
} from "../artifact-contracts/generated.mjs";
import { authorOperationRows } from "./rows/author.mts";
import { bookOperationRows } from "./rows/book.mts";
import { paperOperationRows } from "./rows/paper.mts";
import { materialSearchOperationRows } from "./rows/search.mts";
import { talkOperationRows } from "./rows/talk.mts";
import { topicOperationRows } from "./rows/topic.mts";
import { translationOperationRows } from "./rows/translation.mts";
import {
  operationPreparer,
  resolveOperationContext,
  unregisteredOperation,
  writeTargetsOverlap,
  type CatalogOperation,
  type OperationInvocation,
  type OperationPreparer,
  type PreparedOperation,
} from "./prepare.mts";
import type {
  KindName,
  OperationName,
  OperationRow,
} from "../artifact-contracts/generated.mjs";

export const OPERATION_ROWS: OperationRow[] = [
  ...materialSearchOperationRows,
  ...paperOperationRows,
  ...bookOperationRows,
  ...talkOperationRows,
  ...translationOperationRows,
  ...topicOperationRows,
  ...authorOperationRows,
];

const preparers: Record<KindName, OperationPreparer> = {
  paper: operationPreparer(
    "paper",
    PAPER_OPERATION_IDENTITIES,
    OPERATION_ROWS,
  ),
  book: operationPreparer(
    "book",
    BOOK_OPERATION_IDENTITIES,
    OPERATION_ROWS,
  ),
  talk: operationPreparer(
    "talk",
    TALK_OPERATION_IDENTITIES,
    OPERATION_ROWS,
  ),
  translation: operationPreparer(
    "translation",
    TRANSLATION_OPERATION_IDENTITIES,
    OPERATION_ROWS,
  ),
  topic: operationPreparer(
    "topic",
    TOPIC_OPERATION_IDENTITIES,
    OPERATION_ROWS,
  ),
  author: operationPreparer(
    "author",
    AUTHOR_OPERATION_IDENTITIES,
    OPERATION_ROWS,
  ),
};

export function resolveCatalogOperation(
  kind: KindName,
  operation: OperationName,
): CatalogOperation | null {
  return preparers[kind]?.resolveCatalogOperation(operation) || null;
}

export function prepareOperation(
  invocation: OperationInvocation,
): PreparedOperation {
  const preparer = preparers[invocation?.kind];
  if (!preparer) throw unregisteredOperation(invocation || {});
  return preparer.prepareOperation({
    operation: invocation.operation,
    slug: invocation.slug,
    context: invocation.context,
    label: invocation.label,
  });
}

export {
  resolveOperationContext,
  writeTargetsOverlap,
  type CatalogOperation,
  type OperationInvocation,
  type PreparedOperation,
} from "./prepare.mts";
