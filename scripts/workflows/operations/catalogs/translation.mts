import { operationPreparer } from "../prepare.mts";
import { translationOperationRows } from "../rows/translation.mts";

const translationOperations = operationPreparer(
  "translation",
  translationOperationRows,
);

export const prepareOperation = translationOperations.prepareOperation;
