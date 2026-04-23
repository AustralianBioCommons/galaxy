import { defineStore } from "pinia";

import { useUserLocalStorage } from "@/composables/userLocalStorage";
import { isTerminalRunState, type StorageOperationRunSummary, type TrackedStorageRun } from "@/utils/storageOperations";

const ACTIVE_RUN_TTL_MS = 24 * 60 * 60 * 1000;

export type StorageRun = TrackedStorageRun;

export type RunStatusUpdate = {
    state: StorageOperationRunSummary["state"];
    succeeded_count?: StorageOperationRunSummary["succeeded_count"];
    failed_count?: StorageOperationRunSummary["failed_count"];
    skipped_count?: StorageOperationRunSummary["skipped_count"];
    total_count?: StorageOperationRunSummary["total_count"];
    update_time?: StorageOperationRunSummary["update_time"];
};

export const useStorageOperationsStore = defineStore("storageOperationsStore", () => {
    const runs = useUserLocalStorage<StorageRun[]>("storage-operations-active-runs", []);

    function pruneExpiredRuns() {
        const now = Date.now();
        runs.value = runs.value.filter((run) => {
            const startedAtRaw = run.create_time || run.update_time;
            if (!startedAtRaw) {
                return true;
            }

            const startedAt = Date.parse(startedAtRaw);
            if (!Number.isFinite(startedAt)) {
                return true;
            }

            return now - startedAt <= ACTIVE_RUN_TTL_MS;
        });
    }

    function startRun(run: StorageRun): void {
        pruneExpiredRuns();
        // Remove any existing run with the same ID
        runs.value = runs.value.filter((r) => r.run_id !== run.run_id);
        runs.value.push(run);
    }

    function updateRunStatus(runId: string, update: RunStatusUpdate): void {
        pruneExpiredRuns();
        runs.value = runs.value.map((run) => {
            if (run.run_id !== runId) {
                return run;
            }

            return {
                ...run,
                ...update,
            };
        });
    }

    function clearRun(runId: string): void {
        runs.value = runs.value.filter((run) => run.run_id !== runId);
    }

    function getRuns(historyId: string): StorageRun[] {
        pruneExpiredRuns();
        return runs.value.filter((run) => run.historyId === historyId);
    }

    function getActiveRuns(historyId: string): StorageRun[] {
        pruneExpiredRuns();
        return runs.value.filter((run) => run.historyId === historyId && !isTerminalRunState(run.state));
    }

    function getCompletedRuns(historyId: string): StorageRun[] {
        pruneExpiredRuns();
        return runs.value.filter((run) => run.historyId === historyId && isTerminalRunState(run.state));
    }

    function getActiveRunCount(historyId: string): number {
        return getActiveRuns(historyId).length;
    }

    function getCompletedRunCount(historyId: string): number {
        return getCompletedRuns(historyId).length;
    }

    pruneExpiredRuns();

    return {
        runs,
        startRun,
        updateRunStatus,
        getRuns,
        getActiveRuns,
        getCompletedRuns,
        getActiveRunCount,
        getCompletedRunCount,
        clearRun,
    };
});
