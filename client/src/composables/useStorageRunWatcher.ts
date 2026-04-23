import { computed, readonly, ref } from "vue";

import { getStorageOperationRunStatus, type HistoryReference, type StorageOperationRunResponse } from "@/api/histories";
import { useResourceWatcher } from "@/composables/resourceWatcher";
import { useStorageOperationsStore } from "@/stores/storageOperationsStore";
import { isTerminalRunState } from "@/utils/storageOperations";

const STORAGE_RUN_POLLING_INTERVAL = 10000; // 10 seconds

export interface StorageRunWatcherOptions {
    pollInterval?: number;
    enableBackgroundPolling?: boolean;
}

const DEFAULT_RUN_WATCHER_OPTIONS: Required<StorageRunWatcherOptions> = {
    pollInterval: STORAGE_RUN_POLLING_INTERVAL,
    enableBackgroundPolling: false,
};

function resolveWatcherOptions(options?: StorageRunWatcherOptions): Required<StorageRunWatcherOptions> {
    return {
        ...DEFAULT_RUN_WATCHER_OPTIONS,
        ...options,
    };
}

/**
 * Poll storage-operation run status until it reaches a terminal state.
 */
export function useStorageRunWatcher(history: HistoryReference, runId: string, options?: StorageRunWatcherOptions) {
    const { pollInterval, enableBackgroundPolling } = resolveWatcherOptions(options);
    const runStatus = ref<StorageOperationRunResponse | null>(null);
    const isTerminal = computed(() => {
        const state = runStatus.value?.run.state;
        return state !== undefined && isTerminalRunState(state);
    });

    async function fetchStatus() {
        const data = await getStorageOperationRunStatus(history, runId);
        runStatus.value = data ?? null;
        if (isTerminal.value) {
            stopPolling();
        }
    }

    const { startWatchingResource: startPolling, stopWatchingResource: stopPolling } = useResourceWatcher(fetchStatus, {
        shortPollingInterval: pollInterval,
        enableBackgroundPolling,
    });

    return { runStatus, isTerminal, startPolling, stopPolling };
}

/**
 * Poll status for all tracked storage-operation runs in a history.
 */
export function useStorageHistoryRunsWatcher(historyId: string, options?: StorageRunWatcherOptions) {
    const { pollInterval, enableBackgroundPolling } = resolveWatcherOptions(options);
    const storageOperationsStore = useStorageOperationsStore();
    const runSummariesByRunId = ref<Record<string, StorageOperationRunResponse["run"]>>({});

    const historyReference: HistoryReference = {
        id: historyId,
        model_class: "History",
    };

    async function watchStorageOperationRuns() {
        const runs = storageOperationsStore.getRuns(historyId);
        if (!runs.length) {
            runSummariesByRunId.value = {};
            return;
        }

        const previous = runSummariesByRunId.value;

        const runsToFetch = runs.filter((run) => !isTerminalRunState(run.state));

        if (!runsToFetch.length) {
            const nextFromPrevious: Record<string, StorageOperationRunResponse["run"]> = {};
            runs.forEach((run) => {
                const summary = previous[run.run_id];
                if (summary) {
                    nextFromPrevious[run.run_id] = summary;
                }
            });
            runSummariesByRunId.value = nextFromPrevious;
            return;
        }

        const settled = await Promise.allSettled(
            runsToFetch.map(async (run) => {
                const status = await getStorageOperationRunStatus(historyReference, run.run_id);
                return { run_id: run.run_id, summary: status?.run };
            }),
        );

        const next: Record<string, StorageOperationRunResponse["run"]> = {};

        runs.forEach((run) => {
            const existingSummary = previous[run.run_id];
            if (existingSummary) {
                next[run.run_id] = existingSummary;
            }
        });

        settled.forEach((result, index) => {
            const runId = runsToFetch[index]?.run_id;
            if (!runId) {
                return;
            }

            if (result.status === "fulfilled" && result.value.summary) {
                const summary = result.value.summary;
                next[runId] = summary;
                storageOperationsStore.updateRunStatus(runId, {
                    state: summary.state,
                    total_count: summary.total_count,
                    succeeded_count: summary.succeeded_count,
                    failed_count: summary.failed_count,
                    skipped_count: summary.skipped_count,
                    update_time: summary.update_time,
                });
            }
        });

        runSummariesByRunId.value = next;
    }

    const { startWatchingResource, stopWatchingResource, isWatchingResource } = useResourceWatcher(
        watchStorageOperationRuns,
        {
            shortPollingInterval: pollInterval,
            enableBackgroundPolling,
        },
    );

    return {
        isPolling: readonly(isWatchingResource),
        startPolling: startWatchingResource,
        stopPolling: stopWatchingResource,
        runSummariesByRunId: readonly(runSummariesByRunId),
    };
}
