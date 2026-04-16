import { computed, ref } from "vue";

import { getStorageOperationRunStatus, type HistoryReference, type StorageOperationRunResponse } from "@/api/histories";
import { useResourceWatcher } from "@/composables/resourceWatcher";

const STORAGE_RUN_TERMINAL_STATES = new Set(["completed", "failed"]);
const STORAGE_RUN_POLLING_INTERVAL = 10000; // 10 seconds

/**
 * Poll storage-operation run status until it reaches a terminal state.
 */
export function useStorageRunWatcher(history: HistoryReference, runId: string) {
    const runStatus = ref<StorageOperationRunResponse | null>(null);
    const isTerminal = computed(() => {
        const state = runStatus.value?.run.state;
        return state !== undefined && STORAGE_RUN_TERMINAL_STATES.has(state);
    });

    async function fetchStatus() {
        const data = await getStorageOperationRunStatus(history, runId);
        runStatus.value = data ?? null;
        if (isTerminal.value) {
            stopPolling();
        }
    }

    const { startWatchingResource: startPolling, stopWatchingResource: stopPolling } = useResourceWatcher(fetchStatus, {
        shortPollingInterval: STORAGE_RUN_POLLING_INTERVAL,
        enableBackgroundPolling: false,
    });

    return { runStatus, isTerminal, startPolling, stopPolling };
}
