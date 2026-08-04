import { TRANSLATION_OPERATION_IDENTITIES } from "../../artifact-contracts/generated.mjs";
import { operationPreparer } from "../prepare.mts";
import { translationOperationRows } from "../rows/translation.mts";

const translationOperations = operationPreparer(
  "translation",
  TRANSLATION_OPERATION_IDENTITIES,
  translationOperationRows,
);

export const prepareOperation = translationOperations.prepareOperation;
export const resolveCatalogOperation =
  translationOperations.resolveCatalogOperation;
