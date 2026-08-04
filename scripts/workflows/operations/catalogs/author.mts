import { operationPreparer } from "../prepare.mts";
import { authorOperationRows } from "../rows/author.mts";

const authorOperations = operationPreparer(
  "author",
  authorOperationRows,
);

export const prepareOperation = authorOperations.prepareOperation;
