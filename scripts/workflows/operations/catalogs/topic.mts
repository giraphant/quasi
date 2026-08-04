import { operationPreparer } from "../prepare.mts";
import { topicOperationRows } from "../rows/topic.mts";

const topicOperations = operationPreparer(
  "topic",
  topicOperationRows,
);

export const prepareOperation = topicOperations.prepareOperation;
