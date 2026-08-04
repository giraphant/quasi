import { operationPreparer } from "../prepare.mts";
import { bookOperationRows } from "../rows/book.mts";
import { materialSearchOperationRows } from "../rows/search.mts";

const bookOperations = operationPreparer(
  "book",
  [...materialSearchOperationRows, ...bookOperationRows],
);

export const prepareOperation = bookOperations.prepareOperation;
