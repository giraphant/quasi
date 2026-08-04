import { BOOK_OPERATION_IDENTITIES } from "../../artifact-contracts/generated.mjs";
import { operationPreparer } from "../prepare.mts";
import { bookOperationRows } from "../rows/book.mts";
import { materialSearchOperationRows } from "../rows/search.mts";

const bookOperations = operationPreparer(
  "book",
  BOOK_OPERATION_IDENTITIES,
  [...materialSearchOperationRows, ...bookOperationRows],
);

export const prepareOperation = bookOperations.prepareOperation;
export const resolveCatalogOperation =
  bookOperations.resolveCatalogOperation;
