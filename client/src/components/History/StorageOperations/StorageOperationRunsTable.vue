<script setup lang="ts">
import { faExternalLinkAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BBadge, BButton, BPagination } from "bootstrap-vue";
import { computed } from "vue";

import type { TableField } from "@/components/Common/GTable.types";
import { useObjectStoreStore } from "@/stores/objectStoreStore";
import type { StorageRun } from "@/stores/storageOperationsStore";
import localize from "@/utils/localization";
import { isTerminalRunState } from "@/utils/storageOperations";

import GTable from "@/components/Common/GTable.vue";
import Heading from "@/components/Common/Heading.vue";
import UtcDate from "@/components/UtcDate.vue";

type StorageOperationTableRow = StorageRun & {
    progressPercent: number;
};

interface Props {
    title: string;
    rows: StorageOperationTableRow[];
    currentPage: number;
    perPage: number;
    sortBy: string;
    sortDesc: boolean;
    emptyMessage: string;
    headingClass?: string;
    paginationClass?: string;
}

const props = withDefaults(defineProps<Props>(), {
    headingClass: undefined,
    paginationClass: undefined,
});

const emit = defineEmits<{
    (e: "sort-changed", sortBy: string, sortDesc: boolean): void;
    (e: "page-change", page: number): void;
    (e: "dismiss", runId: string): void;
}>();

const objectStoreStore = useObjectStoreStore();

const fields: TableField[] = [
    { key: "state", label: localize("Status"), sortable: true, width: "130px" },
    { key: "mode", label: localize("Mode"), sortable: true, width: "120px" },
    { key: "target_object_store_id", label: localize("Target store"), sortable: true },
    { key: "total_count", label: localize("Datasets"), sortable: true, align: "center", width: "120px" },
    { key: "progressPercent", label: localize("Progress"), sortable: true, width: "220px" },
    { key: "create_time", label: localize("Started"), sortable: true, width: "180px" },
    { key: "update_time", label: localize("Completed"), sortable: true, width: "180px" },
    { key: "actions", label: localize("Actions"), sortable: false, width: "180px" },
];

const showPagination = computed(() => props.rows.length > props.perPage);

function onSortChanged(newSortBy: string, newSortDesc: boolean) {
    emit("sort-changed", newSortBy, newSortDesc);
}

function onPageChange(page: number) {
    emit("page-change", page);
}

function dismissStorageRun(runId: string) {
    emit("dismiss", runId);
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

function getProgressBarClass(row: StorageOperationTableRow) {
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

function getTargetStoreDisplayName(targetObjectStoreId: string) {
    return objectStoreStore.getObjectStoreNameById(targetObjectStoreId) ?? targetObjectStoreId;
}
</script>

<template>
    <div>
        <Heading h3 size="sm" :class="props.headingClass">{{ props.title }}</Heading>

        <GTable
            striped
            hover
            stacked="md"
            show-empty
            :fields="fields"
            :items="props.rows"
            :current-page="props.currentPage"
            :per-page="props.perPage"
            :sort-by="props.sortBy"
            :sort-desc="props.sortDesc"
            :local-sorting="false"
            :local-filtering="false"
            :empty-state="{ message: props.emptyMessage }"
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
                <UtcDate :date="slot.item.create_time" mode="elapsed" />
            </template>

            <template v-slot:cell(update_time)="slot">
                <span v-if="isTerminalRunState(slot.item.state)">
                    <UtcDate :date="slot.item.update_time" mode="elapsed" />
                </span>
                <span v-else class="text-muted">—</span>
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

        <div v-if="showPagination" class="d-flex justify-content-end" :class="props.paginationClass">
            <BPagination
                :value="props.currentPage"
                :total-rows="props.rows.length"
                :per-page="props.perPage"
                align="right"
                size="sm"
                first-number
                last-number
                @change="onPageChange" />
        </div>
    </div>
</template>

<style scoped>
.storage-progress {
    height: 0.6rem;
}
</style>
