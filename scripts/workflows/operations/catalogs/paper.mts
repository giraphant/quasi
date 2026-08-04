import { operationPreparer } from "../prepare.mts";
import { paperOperationRows } from "../rows/paper.mts";
import { materialSearchOperationRows } from "../rows/search.mts";

const paperOperations = operationPreparer(
  "paper",
  [...materialSearchOperationRows, ...paperOperationRows],
);

export const prepareOperation = paperOperations.prepareOperation;
