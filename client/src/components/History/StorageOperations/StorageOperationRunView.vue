<script setup lang="ts">
import { BAlert, BBadge, BFormInput, BPagination } from "bootstrap-vue";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import type { HistoryReference } from "@/api/histories";
import type { TableField } from "@/components/Common/GTable.types";
import { useStorageRunWatcher } from "@/composables/useStorageRunWatcher";
import { useObjectStoreStore } from "@/stores/objectStoreStore";
import { useStorageOperationsStore } from "@/stores/storageOperationsStore";
import localize from "@/utils/localization";
import { toTrackedStorageRun } from "@/utils/storageOperations";

import BreadcrumbHeading from "@/components/Common/BreadcrumbHeading.vue";
import DatasetPopoverLink from "@/components/Common/DatasetPopoverLink.vue";
import GTable from "@/components/Common/GTable.vue";
import Heading from "@/components/Common/Heading.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

const props = defineProps<{
    historyId: string;
    runId: string;
}>();

const history: HistoryReference = {
    id: props.historyId,
    model_class: "History",
};

const { runStatus, isTerminal, startPolling, stopPolling } = useStorageRunWatcher(history, props.runId);
const storageOperationsStore = useStorageOperationsStore();
const objectStoreStore = useObjectStoreStore();

const run = computed(() => runStatus.value?.run);
const items = computed(() => runStatus.value?.items ?? []);
const sortBy = ref("dataset_id");
const sortDesc = ref(false);
const filterText = ref("");
const currentPage = ref(1);
const perPage = 50;

const breadcrumbItems = computed(() => [
    { title: "History Storage Operations", to: `/histories/${props.historyId}/storage/operations` },
    { title: "Storage Operation Run" },
]);

const tableFields: TableField[] = [
    { key: "dataset_id", label: localize("Dataset"), sortable: true, width: "260px" },
    { key: "state", label: localize("State"), sortable: true, width: "120px" },
    { key: "reason_code", label: localize("Reason code"), sortable: true, width: "180px" },
    { key: "message", label: localize("Message"), sortable: true, class: "run-item-message" },
];

const stateVariant = computed(() => {
    const state = run.value?.state;
    if (state === "failed") {
        return "danger";
    }
    if (state === "completed") {
        if ((run.value?.failed_count ?? 0) > 0 || (run.value?.skipped_count ?? 0) > 0) {
            return "warning";
        }
        return "success";
    }
    return "info";
});

const failedOrSkippedItems = computed(() => {
    return items.value.filter((item) => item.state === "failed" || item.state === "skipped");
});

const filteredItems = computed(() => {
    const filter = filterText.value.trim().toLowerCase();
    if (!filter) {
        return failedOrSkippedItems.value;
    }

    return failedOrSkippedItems.value.filter((item) => {
        return [item.dataset_id, item.state, item.reason_code ?? "", item.message ?? ""]
            .join(" ")
            .toLowerCase()
            .includes(filter);
    });
});

const displayItems = computed(() => {
    return [...filteredItems.value].sort((a, b) => {
        const aValue = getSortableValue(a, sortBy.value);
        const bValue = getSortableValue(b, sortBy.value);

        let comparison = 0;
        if (typeof aValue === "number" && typeof bValue === "number") {
            comparison = aValue - bValue;
        } else {
            comparison = String(aValue).localeCompare(String(bValue));
        }

        return sortDesc.value ? -comparison : comparison;
    });
});

const succeededPercent = computed(() => {
    const total = run.value?.total_count ?? 0;
    return total > 0 ? Math.round(((run.value?.succeeded_count ?? 0) / total) * 100) : 0;
});

const failedPercent = computed(() => {
    const total = run.value?.total_count ?? 0;
    return total > 0 ? Math.round(((run.value?.failed_count ?? 0) / total) * 100) : 0;
});

const skippedPercent = computed(() => {
    const total = run.value?.total_count ?? 0;
    return total > 0 ? Math.round(((run.value?.skipped_count ?? 0) / total) * 100) : 0;
});

const failedItemsEmptyStateMessage = computed(() => {
    if (!isTerminal.value) {
        return localize("No failed or skipped items yet. This run is still in progress.");
    }
    return localize("No failed or skipped items for this run.");
});

const maxPage = computed(() => {
    return Math.max(1, Math.ceil(displayItems.value.length / perPage));
});

const targetStoreDisplayName = computed(() => {
    return (
        objectStoreStore.getObjectStoreNameById(run.value?.target_object_store_id) ??
        run.value?.target_object_store_id ??
        ""
    );
});

function onSortChanged(newSortBy: string, newSortDesc: boolean) {
    sortBy.value = newSortBy;
    sortDesc.value = newSortDesc;
}

function onPageChange(page: number) {
    currentPage.value = page;
}

function getSortableValue(item: Record<string, string | number | null | undefined>, key: string) {
    return item[key] ?? "";
}

function getItemStateVariant(state: string) {
    if (state === "failed") {
        return "danger";
    }
    if (state === "skipped") {
        return "warning";
    }
    return "secondary";
}

watch(filterText, () => {
    currentPage.value = 1;
});

watch(displayItems, () => {
    if (currentPage.value > maxPage.value) {
        currentPage.value = maxPage.value;
    }
});

watch(
    run,
    (currentRun) => {
        if (!currentRun) {
            return;
        }

        storageOperationsStore.startRun(toTrackedStorageRun(props.historyId, currentRun));
    },
    { immediate: true },
);

onMounted(() => {
    startPolling();
});

onBeforeUnmount(() => {
    stopPolling();
});
</script>

<template>
    <div class="storage-operation-run-view p-3">
        <BreadcrumbHeading :items="breadcrumbItems" />

        <LoadingSpan v-if="!run" :message="localize('Loading storage operation run status')" />

        <template v-else>
            <BAlert show :variant="stateVariant">
                <div class="d-flex align-items-center flex-wrap">
                    <strong class="mr-2">{{ localize("State:") }}</strong>
                    <BBadge :variant="stateVariant" class="mr-3">{{ run.state }}</BBadge>
                    <span class="mr-3">
                        <strong>{{ localize("Mode:") }}</strong> {{ run.mode }}
                    </span>
                    <span>
                        <strong>{{ localize("Target store:") }}</strong> {{ targetStoreDisplayName }}
                    </span>
                </div>
            </BAlert>

            <div class="mb-3">
                <strong>{{ localize("Total:") }}</strong> {{ run.total_count }}
                <span class="mx-2">|</span>
                <strong>{{ localize("Succeeded:") }}</strong> {{ run.succeeded_count }}
                <span class="mx-2">|</span>
                <strong>{{ localize("Failed:") }}</strong> {{ run.failed_count }}
                <span class="mx-2">|</span>
                <strong>{{ localize("Skipped:") }}</strong> {{ run.skipped_count }}
            </div>

            <div class="mb-3">
                <div
                    class="progress storage-run-summary-progress"
                    role="progressbar"
                    aria-valuemin="0"
                    aria-valuemax="100">
                    <div class="progress-bar bg-success" :style="{ width: `${succeededPercent}%` }">
                        {{ succeededPercent > 7 ? `${succeededPercent}%` : "" }}
                    </div>
                    <div class="progress-bar bg-danger" :style="{ width: `${failedPercent}%` }">
                        {{ failedPercent > 7 ? `${failedPercent}%` : "" }}
                    </div>
                    <div class="progress-bar bg-warning text-dark" :style="{ width: `${skippedPercent}%` }">
                        {{ skippedPercent > 7 ? `${skippedPercent}%` : "" }}
                    </div>
                </div>
            </div>

            <BAlert v-if="!isTerminal" show variant="info">
                {{ localize("This run is still in progress. Status is updated automatically.") }}
            </BAlert>

            <div class="mt-3">
                <Heading h3 size="sm">{{ localize("Failed or Skipped Items") }}</Heading>

                <BFormInput
                    v-model="filterText"
                    class="run-item-filter mb-2"
                    :placeholder="localize('Filter by dataset, state, reason code, or message')" />

                <GTable
                    id="storage-operation-run-items-table"
                    striped
                    hover
                    stacked="md"
                    show-empty
                    :fields="tableFields"
                    :items="displayItems"
                    :current-page="currentPage"
                    :per-page="perPage"
                    :sort-by="sortBy"
                    :sort-desc="sortDesc"
                    :local-sorting="false"
                    :local-filtering="false"
                    :empty-state="{ message: failedItemsEmptyStateMessage }"
                    @sort-changed="onSortChanged">
                    <template v-slot:cell(dataset_id)="slot">
                        <DatasetPopoverLink :dataset-id="slot.item.dataset_id" />
                    </template>

                    <template v-slot:cell(state)="slot">
                        <BBadge :variant="getItemStateVariant(slot.item.state)">{{ slot.item.state }}</BBadge>
                    </template>

                    <template v-slot:cell(reason_code)="slot">
                        <span>{{ slot.item.reason_code || "-" }}</span>
                    </template>

                    <template v-slot:cell(message)="slot">
                        <span>{{ slot.item.message || "-" }}</span>
                    </template>
                </GTable>

                <div v-if="displayItems.length > perPage" class="d-flex justify-content-end mt-2">
                    <BPagination
                        :value="currentPage"
                        :total-rows="displayItems.length"
                        :per-page="perPage"
                        align="right"
                        size="sm"
                        first-number
                        last-number
                        @change="onPageChange" />
                </div>
            </div>
        </template>
    </div>
</template>

<style scoped>
.run-item-filter {
    min-width: 280px;
    max-width: 520px;
}

.storage-run-summary-progress {
    height: 1rem;
}

:deep(.run-item-message) {
    white-space: normal;
    word-break: break-word;
}
</style>
