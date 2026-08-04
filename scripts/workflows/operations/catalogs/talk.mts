import { operationPreparer } from "../prepare.mts";
import { talkOperationRows } from "../rows/talk.mts";

const talkOperations = operationPreparer(
  "talk",
  talkOperationRows,
);

export const prepareOperation = talkOperations.prepareOperation;
