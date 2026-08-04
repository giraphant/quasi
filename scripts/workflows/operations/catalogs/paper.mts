import { PAPER_OPERATION_IDENTITIES } from "../../artifact-contracts/generated.mjs";
import { operationPreparer } from "../prepare.mts";
import { paperOperationRows } from "../rows/paper.mts";
import { materialSearchOperationRows } from "../rows/search.mts";

const paperOperations = operationPreparer(
  "paper",
  PAPER_OPERATION_IDENTITIES,
  [...materialSearchOperationRows, ...paperOperationRows],
);

export const prepareOperation = paperOperations.prepareOperation;
export const resolveCatalogOperation =
  paperOperations.resolveCatalogOperation;
