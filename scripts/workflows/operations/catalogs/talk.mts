import { TALK_OPERATION_IDENTITIES } from "../../artifact-contracts/generated.mjs";
import { operationPreparer } from "../prepare.mts";
import { talkOperationRows } from "../rows/talk.mts";

const talkOperations = operationPreparer(
  "talk",
  TALK_OPERATION_IDENTITIES,
  talkOperationRows,
);

export const prepareOperation = talkOperations.prepareOperation;
export const resolveCatalogOperation =
  talkOperations.resolveCatalogOperation;
