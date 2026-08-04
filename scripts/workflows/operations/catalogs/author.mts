import { AUTHOR_OPERATION_IDENTITIES } from "../../artifact-contracts/generated.mjs";
import { operationPreparer } from "../prepare.mts";
import { authorOperationRows } from "../rows/author.mts";

const authorOperations = operationPreparer(
  "author",
  AUTHOR_OPERATION_IDENTITIES,
  authorOperationRows,
);

export const prepareOperation = authorOperations.prepareOperation;
export const resolveCatalogOperation =
  authorOperations.resolveCatalogOperation;
