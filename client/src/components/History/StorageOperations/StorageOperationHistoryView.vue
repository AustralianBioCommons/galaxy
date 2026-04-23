<script setup lang="ts">
import { faExternalLinkAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BAlert, BBadge, BButton, BFormInput, BPagination } from "bootstrap-vue";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import type { TableField } from "@/components/Common/GTable.types";
import { useStorageHistoryRunsWatcher } from "@/composables/useStorageRunWatcher";
import { useObjectStoreStore } from "@/stores/objectStoreStore";
import { type StorageRun, useStorageOperationsStore } from "@/stores/storageOperationsStore";
import localize from "@/utils/localization";

import GTable from "@/components/Common/GTable.vue";
import Heading from "@/components/Common/Heading.vue";

type EnrichedStorageRun = ReturnType<typeof enrichRunWithSummary>;

const props = defineProps<{
    historyId: string;
}>();

const storageOperationsStore = useStorageOperationsStore();
const objectStoreStore = useObjectStoreStore();

const sortBy = ref("create_time");
const sortDesc = ref(true);
const filterText = ref("");
const inProgressPage = ref(1);
const finishedPage = ref(1);
const perPage = 20;

const { startPolling, stopPolling, runSummariesByRunId } = useStorageHistoryRunsWatcher(props.historyId);

const fields: TableField[] = [
    { key: "state", label: localize("Status"), sortable: true, width: "130px" },
    { key: "mode", label: localize("Mode"), sortable: true, width: "120px" },
    { key: "target_object_store_id", label: localize("Target store"), sortable: true },
    { key: "total_count", label: localize("Datasets"), sortable: true, align: "center", width: "120px" },
    { key: "progressPercent", label: localize("Progress"), sortable: true, width: "220px" },
    { key: "create_time", label: localize("Started"), sortable: true, width: "220px" },
    { key: "actions", label: localize("Actions"), sortable: false, width: "180px" },
];

const trackedRuns = computed(() => {
    return storageOperationsStore.runs.filter((run) => run.historyId === props.historyId);
});

/**
 * Enrich tracked runs with computed fields from API summaries
 */
function enrichRunWithSummary(run: StorageRun) {
    const summary = runSummariesByRunId.value[run.run_id];
    const succeededCount = summary?.succeeded_count ?? run.succeeded_count;
    const failedCount = summary?.failed_count ?? run.failed_count;
    const skippedCount = summary?.skipped_count ?? run.skipped_count;
    const totalCount = summary?.total_count ?? run.total_count;
    const processed = succeededCount + failedCount + skippedCount;
    const progressPercent = totalCount > 0 ? Math.min(100, Math.round((processed / totalCount) * 100)) : 0;

    return {
        ...run,
        total_count: totalCount,
        succeeded_count: succeededCount,
        failed_count: failedCount,
        skipped_count: skippedCount,
        progressPercent,
    };
}

const tableRows = computed(() => {
    return trackedRuns.value.map(enrichRunWithSummary);
});

const filteredRows = computed(() => {
    const filter = filterText.value.trim().toLowerCase();
    if (!filter) {
        return tableRows.value;
    }

    return tableRows.value.filter((row) => {
        const haystack = [row.state, row.mode, row.target_object_store_id, row.total_count, row.create_time, row.run_id]
            .join(" ")
            .toLowerCase();
        return haystack.includes(filter);
    });
});

const displayRows = computed(() => {
    return [...filteredRows.value].sort((a, b) => {
        const aValue = getSortableValue(a);
        const bValue = getSortableValue(b);

        let comparison = 0;
        if (typeof aValue === "number" && typeof bValue === "number") {
            comparison = aValue - bValue;
        } else {
            comparison = String(aValue).localeCompare(String(bValue));
        }

        return sortDesc.value ? -comparison : comparison;
    });
});

const hasRuns = computed(() => tableRows.value.length > 0);

const inProgressRows = computed(() => {
    return displayRows.value.filter((row) => row.state === "pending" || row.state === "running");
});

const finishedRows = computed(() => {
    return displayRows.value.filter((row) => row.state === "completed" || row.state === "failed");
});

const inProgressMaxPage = computed(() => {
    return Math.max(1, Math.ceil(inProgressRows.value.length / perPage));
});

const finishedMaxPage = computed(() => {
    return Math.max(1, Math.ceil(finishedRows.value.length / perPage));
});

function dismissStorageRun(runId: string) {
    storageOperationsStore.clearRun(runId);
}

function onSortChanged(newSortBy: string, newSortDesc: boolean) {
    sortBy.value = newSortBy;
    sortDesc.value = newSortDesc;
}

function getStateVariant(state: string) {
    if (state === "failed") {
        return "danger";
    }
    if (state === "completed") {
        return "warning";
    }
    if (state === "running") {
        return "info";
    }
    return "secondary";
}

function getProgressBarClass(row: EnrichedStorageRun) {
    if (row.state === "failed") {
        return "bg-danger";
    }
    if (row.state === "completed" && (row.failed_count > 0 || row.skipped_count > 0)) {
        return "bg-warning";
    }
    if (row.state === "completed") {
        return "bg-success";
    }
    return "bg-info";
}

function getSortableValue(row: EnrichedStorageRun) {
    const key = sortBy.value;
    if (key === "create_time") {
        const timestamp = Date.parse(row.create_time);
        return Number.isNaN(timestamp) ? 0 : timestamp;
    }
    return row[key as keyof EnrichedStorageRun] ?? "";
}

onMounted(() => {
    startPolling();
});

onUnmounted(() => {
    stopPolling();
});

watch(displayRows, () => {
    if (inProgressPage.value > inProgressMaxPage.value) {
        inProgressPage.value = inProgressMaxPage.value;
    }
    if (finishedPage.value > finishedMaxPage.value) {
        finishedPage.value = finishedMaxPage.value;
    }
});

watch(filterText, () => {
    inProgressPage.value = 1;
    finishedPage.value = 1;
});

function onInProgressPageChange(page: number) {
    inProgressPage.value = page;
}

function onFinishedPageChange(page: number) {
    finishedPage.value = page;
}

function formatStartedAt(startedAt: string) {
    const date = new Date(startedAt);
    return Number.isNaN(date.getTime()) ? startedAt : date.toLocaleString();
}

function getTargetStoreDisplayName(targetObjectStoreId: string) {
    return objectStoreStore.getObjectStoreNameById(targetObjectStoreId) ?? targetObjectStoreId;
}
</script>

<template>
    <div class="storage-operation-history-view p-3">
        <Heading h2 separator size="md">{{ localize("History Storage Operations") }}</Heading>

        <BAlert show variant="info">
            {{
                localize(
                    "This page shows tracked background storage operations for this history, split by in-progress and finished runs.",
                )
            }}
        </BAlert>

        <BAlert v-if="!hasRuns" show variant="secondary">
            {{ localize("No tracked storage operations for this history.") }}
        </BAlert>

        <template v-else>
            <div class="d-flex flex-wrap align-items-center mb-2 gap-2">
                <BFormInput
                    v-model="filterText"
                    class="storage-run-filter"
                    :placeholder="localize('Filter runs by status, mode, store, run id...')" />
            </div>

            <Heading h3 size="sm">{{ localize("In Progress") }}</Heading>
            <GTable
                id="storage-operation-history-in-progress-table"
                striped
                hover
                stacked="md"
                show-empty
                :fields="fields"
                :items="inProgressRows"
                :current-page="inProgressPage"
                :per-page="perPage"
                :sort-by="sortBy"
                :sort-desc="sortDesc"
                :local-sorting="false"
                :local-filtering="false"
                :empty-state="{ message: localize('No in-progress runs found.') }"
                @sort-changed="onSortChanged">
                <template v-slot:cell(state)="slot">
                    <BBadge :variant="getStateVariant(slot.item.state)">{{ slot.item.state }}</BBadge>
                </template>

                <template v-slot:cell(mode)="slot">
                    <span class="text-monospace">{{ slot.item.mode }}</span>
                </template>

                <template v-slot:cell(target_object_store_id)="slot">
                    {{ getTargetStoreDisplayName(slot.item.target_object_store_id) }}
                </template>

                <template v-slot:cell(progressPercent)="slot">
                    <div>
                        <div class="progress storage-progress">
                            <div
                                class="progress-bar"
                                :class="getProgressBarClass(slot.item)"
                                role="progressbar"
                                :style="{ width: `${slot.item.progressPercent}%` }"
                                :aria-valuenow="slot.item.progressPercent"
                                aria-valuemin="0"
                                aria-valuemax="100" />
                        </div>
                        <small class="text-muted">
                            {{ slot.item.succeeded_count + slot.item.failed_count + slot.item.skipped_count }} /
                            {{ slot.item.total_count }} ({{ slot.item.progressPercent }}%)
                        </small>
                    </div>
                </template>

                <template v-slot:cell(create_time)="slot">
                    {{ formatStartedAt(slot.item.create_time) }}
                </template>

                <template v-slot:cell(actions)="slot">
                    <div class="d-flex align-items-center">
                        <router-link class="btn btn-sm btn-outline-primary mr-2" :to="slot.item.runUrl">
                            <FontAwesomeIcon :icon="faExternalLinkAlt" fixed-width class="mr-1" />
                            {{ localize("Go to details") }}
                        </router-link>
                        <BButton size="sm" variant="link" class="p-0" @click.stop="dismissStorageRun(slot.item.run_id)">
                            {{ localize("Dismiss") }}
                        </BButton>
                    </div>
                </template>
            </GTable>

            <div v-if="inProgressRows.length > perPage" class="d-flex justify-content-end mt-2 mb-3">
                <BPagination
                    :value="inProgressPage"
                    :total-rows="inProgressRows.length"
                    :per-page="perPage"
                    align="right"
                    size="sm"
                    first-number
                    last-number
                    @change="onInProgressPageChange" />
            </div>

            <Heading h3 size="sm" class="mt-3">{{ localize("Finished") }}</Heading>
            <GTable
                id="storage-operation-history-finished-table"
                striped
                hover
                stacked="md"
                show-empty
                :fields="fields"
                :items="finishedRows"
                :current-page="finishedPage"
                :per-page="perPage"
                :sort-by="sortBy"
                :sort-desc="sortDesc"
                :local-sorting="false"
                :local-filtering="false"
                :empty-state="{ message: localize('No finished runs found.') }"
                @sort-changed="onSortChanged">
                <template v-slot:cell(state)="slot">
                    <BBadge :variant="getStateVariant(slot.item.state)">{{ slot.item.state }}</BBadge>
                </template>

                <template v-slot:cell(mode)="slot">
                    <span class="text-monospace">{{ slot.item.mode }}</span>
                </template>

                <template v-slot:cell(target_object_store_id)="slot">
                    {{ getTargetStoreDisplayName(slot.item.target_object_store_id) }}
                </template>

                <template v-slot:cell(progressPercent)="slot">
                    <div>
                        <div class="progress storage-progress">
                            <div
                                class="progress-bar"
                                :class="getProgressBarClass(slot.item)"
                                role="progressbar"
                                :style="{ width: `${slot.item.progressPercent}%` }"
                                :aria-valuenow="slot.item.progressPercent"
                                aria-valuemin="0"
                                aria-valuemax="100" />
                        </div>
                        <small class="text-muted">
                            {{ slot.item.succeeded_count + slot.item.failed_count + slot.item.skipped_count }} /
                            {{ slot.item.total_count }} ({{ slot.item.progressPercent }}%)
                        </small>
                    </div>
                </template>

                <template v-slot:cell(create_time)="slot">
                    {{ formatStartedAt(slot.item.create_time) }}
                </template>

                <template v-slot:cell(actions)="slot">
                    <div class="d-flex align-items-center">
                        <router-link class="btn btn-sm btn-outline-primary mr-2" :to="slot.item.runUrl">
                            <FontAwesomeIcon :icon="faExternalLinkAlt" fixed-width class="mr-1" />
                            {{ localize("Go to details") }}
                        </router-link>
                        <BButton size="sm" variant="link" class="p-0" @click.stop="dismissStorageRun(slot.item.run_id)">
                            {{ localize("Dismiss") }}
                        </BButton>
                    </div>
                </template>
            </GTable>

            <div v-if="finishedRows.length > perPage" class="d-flex justify-content-end mt-2">
                <BPagination
                    :value="finishedPage"
                    :total-rows="finishedRows.length"
                    :per-page="perPage"
                    align="right"
                    size="sm"
                    first-number
                    last-number
                    @change="onFinishedPageChange" />
            </div>
        </template>
    </div>
</template>

<style scoped>
.storage-run-filter {
    min-width: 280px;
    max-width: 520px;
}

.storage-progress {
    height: 0.6rem;
}
</style>
