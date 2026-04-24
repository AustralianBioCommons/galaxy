<script setup lang="ts">
import { BAlert, BButton } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import type { HistoryContentItemBase, UserConcreteObjectStoreModel } from "@/api";
import type { HistoryReference, StorageOperationMode, StorageOperationPreviewResponse } from "@/api/histories";
import { useWizard } from "@/components/Common/Wizard/useWizard";
import { HistoryFilters } from "@/components/History/HistoryFilters";
import { bulkStorageExecute, bulkStoragePreview } from "@/components/History/model/queries";
import { Toast } from "@/composables/toast";
import { useObjectStoreStore } from "@/stores/objectStoreStore";
import { useStorageOperationsStore } from "@/stores/storageOperationsStore";
import { getIneligibleReasonDescription, toTrackedStorageRun } from "@/utils/storageOperations";
import { bytesToString } from "@/utils/utils";

import GModal from "@/components/BaseComponents/GModal.vue";
import GenericWizard from "@/components/Common/Wizard/GenericWizard.vue";

interface StorageTargetOption {
    object_store_id: string;
    name: string;
}

const props = defineProps<{
    show: boolean;
    history: HistoryReference;
    filterText: string;
    contentSelection: Map<unknown, HistoryContentItemBase>;
    isQuerySelection: boolean;
    numSelected: number;
}>();

const emit = defineEmits<{
    (e: "update:show", value: boolean): void;
    (e: "completed"): void;
}>();

const objectStoreStore = useObjectStoreStore();
const storageOperationsStore = useStorageOperationsStore();

const storageOperationMode = ref<StorageOperationMode>("relocate");
const selectedTargetObjectStoreId = ref<string | null>(null);
const storagePreview = ref<StorageOperationPreviewResponse | null>(null);
const storagePreviewLoading = ref(false);
const storageExecuting = ref(false);
const previewError = ref<string | null>(null);
const executionError = ref<string | null>(null);
const notifyOnCompletion = ref(true);

const wizard = useWizard({
    configure: {
        label: "Configure",
        instructions: computed(() => `Select the target storage location for ${props.numSelected} selected item(s).`),
        isValid: () => Boolean(selectedTargetObjectStoreId.value),
        isSkippable: () => false,
    },
    preview: {
        label: "Preview",
        instructions: "Review the estimated impact before running the operation.",
        isValid: () => Boolean(storagePreview.value?.snapshot_id) && !storageExecuting.value,
        isSkippable: () => false,
    },
});

const isBusy = computed(() => storagePreviewLoading.value || storageExecuting.value);

const showProxy = computed({
    get: () => props.show,
    set: (value: boolean) => emit("update:show", value),
});

const storageTargetOptions = computed<StorageTargetOption[]>(() => {
    const stores = (objectStoreStore.selectableObjectStores ?? []) as UserConcreteObjectStoreModel[];
    return stores
        .filter((store): store is UserConcreteObjectStoreModel & { object_store_id: string } =>
            Boolean(store.object_store_id),
        )
        .map((store) => ({
            object_store_id: store.object_store_id,
            name: store.name ?? store.object_store_id,
        }));
});

const ineligibleReasonBreakdown = computed(() => {
    const items = storagePreview.value?.eligibility?.items ?? [];
    const byReason = new Map<string, number>();

    for (const item of items) {
        if (item.state !== "ineligible") {
            continue;
        }
        const reason = item.reason_code ?? "unknown";
        byReason.set(reason, (byReason.get(reason) ?? 0) + 1);
    }

    return Array.from(byReason.entries())
        .map(([code, count]) => ({ code, count }))
        .sort((a, b) => b.count - a.count);
});

const sourceQuotaDeltaEntries = computed(() => {
    const deltas = storagePreview.value?.estimates?.quota_delta_by_source ?? {};
    return Object.entries(deltas)
        .map(([source, delta]) => ({ source, delta }))
        .sort((a, b) => a.source.localeCompare(b.source));
});

const transferEstimate = computed(() => {
    const bytes = storagePreview.value?.estimates?.bytes_to_transfer;
    if (bytes == null) {
        return "Not available";
    }
    return bytesToString(bytes);
});

const hasWarnings = computed(() => Boolean(storagePreview.value?.warnings?.length));

const selectedTargetStoreName = computed(() => {
    if (!selectedTargetObjectStoreId.value) {
        return "";
    }
    const store = storageTargetOptions.value.find(
        (option) => option.object_store_id === selectedTargetObjectStoreId.value,
    );
    return store?.name || selectedTargetObjectStoreId.value;
});

// Trigger preview fetch when wizard navigates to the preview step.
watch(wizard.index, async (newIndex, oldIndex) => {
    if (newIndex === 1) {
        storagePreview.value = null;
        await previewStorageOperation();
    } else if (newIndex === 0 && oldIndex === 1) {
        // Went back to configure — clear preview/error state.
        storagePreview.value = null;
        previewError.value = null;
        executionError.value = null;
    }
});

watch(
    () => props.show,
    (newVal) => {
        if (newVal) {
            resetState();
        }
    },
);

function formatBytes(size: number) {
    return bytesToString(size);
}

function onCancel() {
    showProxy.value = false;
    resetState();
}

function onTargetStoreChanged() {
    previewError.value = null;
    executionError.value = null;
}

function resetState() {
    wizard.goTo("configure");
    storageOperationMode.value = "relocate";
    selectedTargetObjectStoreId.value = null;
    storagePreview.value = null;
    storagePreviewLoading.value = false;
    storageExecuting.value = false;
    previewError.value = null;
    executionError.value = null;
    notifyOnCompletion.value = true;
}

async function previewStorageOperation() {
    if (!selectedTargetObjectStoreId.value) {
        return;
    }

    previewError.value = null;
    executionError.value = null;
    storagePreviewLoading.value = true;

    try {
        const filters = HistoryFilters.getQueryDict(props.filterText);
        const items = getExplicitlySelectedItems();
        const previewResponse = (await bulkStoragePreview(
            props.history,
            storageOperationMode.value,
            selectedTargetObjectStoreId.value,
            filters,
            items,
        )) as StorageOperationPreviewResponse | undefined;
        if (!previewResponse) {
            throw new Error("Failed to preview storage operation.");
        }
        storagePreview.value = previewResponse;
    } catch (error) {
        storagePreview.value = null;
        previewError.value = error instanceof Error ? error.message : "Failed to preview storage operation.";
        Toast.error(previewError.value, "Storage Preview Failed");
        wizard.goTo("configure");
    } finally {
        storagePreviewLoading.value = false;
    }
}

async function executeStorageOperation() {
    const snapshotId = storagePreview.value?.snapshot_id;
    if (!snapshotId) {
        return;
    }

    storageExecuting.value = true;
    executionError.value = null;

    try {
        const executeResponse = await bulkStorageExecute(
            props.history,
            snapshotId,
            undefined,
            notifyOnCompletion.value,
        );
        storageOperationsStore.startRun(toTrackedStorageRun(props.history.id, executeResponse.run));

        Toast.success("Storage operation submitted successfully.", "Storage Operation Submitted");
        emit("completed");
        showProxy.value = false;
        resetState();
    } catch (error) {
        executionError.value = error instanceof Error ? error.message : "Failed to execute storage operation.";
        Toast.error(executionError.value, "Storage Operation Failed");
    } finally {
        storageExecuting.value = false;
    }
}

function getExplicitlySelectedItems(): HistoryContentItemBase[] {
    if (props.isQuerySelection) {
        return [];
    }

    return Array.from(props.contentSelection.values()).map((item) => {
        return {
            id: item.id,
            history_content_type: item.history_content_type,
        };
    });
}
</script>

<template>
    <GModal :show.sync="showProxy" title="Manage Storage Location" size="medium" overflow-visible>
        <BAlert v-if="previewError" show variant="danger" dismissible class="mb-2" @dismissed="previewError = null">
            {{ previewError }}
        </BAlert>

        <BAlert v-if="executionError" show variant="danger" dismissible class="mb-2" @dismissed="executionError = null">
            {{ executionError }}
        </BAlert>

        <GenericWizard
            :use="wizard"
            :is-busy="isBusy"
            submit-button-label="Run operation"
            container-component="div"
            @submit="executeStorageOperation">
            <template v-slot:cancel-button>
                <BButton variant="secondary" @click="onCancel">Cancel</BButton>
            </template>

            <div v-if="wizard.isCurrent('configure')">
                <div class="mb-2">
                    <label for="storage-operation-mode" class="d-block mb-1">Mode</label>
                    <select id="storage-operation-mode" v-model="storageOperationMode" class="form-control" disabled>
                        <option value="relocate">Relocate</option>
                    </select>
                </div>

                <div class="mb-2">
                    <label for="storage-operation-target" class="d-block mb-1">Target storage location</label>
                    <select
                        id="storage-operation-target"
                        v-model="selectedTargetObjectStoreId"
                        class="form-control"
                        @change="onTargetStoreChanged">
                        <option :value="null" disabled>Select target storage location</option>
                        <option
                            v-for="target in storageTargetOptions"
                            :key="target.object_store_id"
                            :value="target.object_store_id">
                            {{ target.name || target.object_store_id }}
                        </option>
                    </select>
                </div>

                <div class="mb-2">
                    <label class="d-flex align-items-center mb-0">
                        <input v-model="notifyOnCompletion" type="checkbox" class="mr-2" />
                        Notify me when the storage operation completes
                    </label>
                    <small class="text-muted d-block mt-1">
                        When disabled, no completion notification will be sent for this run.
                    </small>
                </div>
            </div>

            <div v-else-if="wizard.isCurrent('preview')">
                <div v-if="storagePreviewLoading" class="text-center text-muted py-3">Loading preview...</div>

                <div v-else-if="storagePreview">
                    <p class="mb-1"><strong>Target storage location:</strong> {{ selectedTargetStoreName }}</p>
                    <p class="mb-1">
                        <strong>Selected items:</strong> {{ storagePreview.selection_counts.selected_items_count }}
                        <span class="mx-2">|</span>
                        <strong>Expanded leaves:</strong> {{ storagePreview.selection_counts.expanded_leaf_count }}
                        <span class="mx-2">|</span>
                        <strong>Total datasets:</strong> {{ storagePreview.selection_counts.unique_dataset_count }}
                    </p>
                    <p class="mb-1">
                        <strong>Eligible:</strong> {{ storagePreview.eligibility.eligible_count }}
                        <span class="mx-2">|</span>
                        <strong>Ineligible:</strong> {{ storagePreview.eligibility.ineligible_count }}
                    </p>
                    <p class="mb-1"><strong>Estimated transfer:</strong> {{ transferEstimate }}</p>

                    <div v-if="sourceQuotaDeltaEntries.length" class="mb-2">
                        <strong>Storage space change by source:</strong>
                        <ul class="mb-0 mt-1">
                            <li v-for="entry in sourceQuotaDeltaEntries" :key="entry.source">
                                {{ entry.source }}: {{ formatBytes(entry.delta) }}
                            </li>
                        </ul>
                    </div>

                    <div v-if="ineligibleReasonBreakdown.length" class="mb-2">
                        <strong>Reasons for ineligibility:</strong>
                        <ul class="mb-0 mt-1">
                            <li v-for="reason in ineligibleReasonBreakdown" :key="reason.code" class="mb-1">
                                <strong>{{ getIneligibleReasonDescription(reason.code).label }}:</strong>
                                {{ reason.count }}
                                <span
                                    v-if="getIneligibleReasonDescription(reason.code).description"
                                    class="text-muted small d-block">
                                    {{ getIneligibleReasonDescription(reason.code).description }}
                                </span>
                            </li>
                        </ul>
                    </div>

                    <div v-if="hasWarnings" class="mb-2">
                        <strong>Warnings:</strong>
                        <ul class="mb-0 mt-1">
                            <li v-for="(warning, index) in storagePreview.warnings" :key="index">
                                {{ warning }}
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </GenericWizard>
    </GModal>
</template>
