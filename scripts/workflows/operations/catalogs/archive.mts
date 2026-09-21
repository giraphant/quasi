import { operationPreparer } from "../prepare.mts";
import { archiveOperationRows } from "../rows/archive.mts";
export const prepareOperation = operationPreparer("archive", archiveOperationRows).prepareOperation;
