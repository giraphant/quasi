import { operationPreparer } from "../prepare.mts";
import { webpageOperationRows } from "../rows/webpage.mts";

const webpageOperations = operationPreparer("webpage", webpageOperationRows);

export const prepareOperation = webpageOperations.prepareOperation;
