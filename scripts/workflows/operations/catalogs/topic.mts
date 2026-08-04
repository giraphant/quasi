import { TOPIC_OPERATION_IDENTITIES } from "../../artifact-contracts/generated.mjs";
import { operationPreparer } from "../prepare.mts";
import { topicOperationRows } from "../rows/topic.mts";

const topicOperations = operationPreparer(
  "topic",
  TOPIC_OPERATION_IDENTITIES,
  topicOperationRows,
);

export const prepareOperation = topicOperations.prepareOperation;
export const resolveCatalogOperation = topicOperations.resolveCatalogOperation;
