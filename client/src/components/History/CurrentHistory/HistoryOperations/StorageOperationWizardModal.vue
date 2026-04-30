<script setup lang="ts">
import { BAlert, BButton } from "bootstrap-vue";
import { storeToRefs } from "pinia";
import { computed, ref, watch } from "vue";
import Multiselect from "vue-multiselect";

import type { HistoryContentItemBase, UserConcreteObjectStoreModel } from "@/api";
import type { HistoryReference, StorageOperationPreviewResponse } from "@/api/histories";
import { useWizard } from "@/components/Common/Wizard/useWizard";
import { HistoryFilters } from "@/components/History/HistoryFilters";
import { bulkStorageExecute, bulkStoragePreview } from "@/components/History/model/queries";
import { QuotaSourceUsageProvider } from "@/components/User/DiskUsage/Quota/QuotaUsageProvider.js";
import { Toast } from "@/composables/toast";
import { useObjectStoreStore } from "@/stores/objectStoreStore";
import { useStorageOperationsStore } from "@/stores/storageOperationsStore";
import { errorMessageAsString } from "@/utils/simple-error";
import { toTrackedStorageRun } from "@/utils/storageOperations";

import GModal from "@/components/BaseComponents/GModal.vue";
import GenericWizard from "@/components/Common/Wizard/GenericWizard.vue";
import StorageOperationPreviewReport from "@/components/History/CurrentHistory/HistoryOperations/StorageOperationPreviewReport.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import ObjectStoreBadges from "@/components/ObjectStore/ObjectStoreBadges.vue";
import QuotaUsageBar from "@/components/User/DiskUsage/Quota/QuotaUsageBar.vue";

type SelectableObjectStoreWithId = UserConcreteObjectStoreModel & { object_store_id: string };

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
const { loading: objectStoresLoading, loadErrorMessage } = storeToRefs(objectStoreStore);

const selectedTargetObjectStoreId = ref<string | null>(null);
const storagePreview = ref<StorageOperationPreviewResponse | null>(null);
const storagePreviewLoading = ref(false);
const storageExecuting = ref(false);
const previewError = ref<string | null>(null);
const executionError = ref<string | null>(null);
const notifyOnCompletion = ref(true);

const wizard = useWizard({
    configure: {
        label: "Destination",
        instructions: computed(() => `Choose the storage location to move ${props.numSelected} selected item(s) to.`),
        isValid: () => Boolean(selectedTargetObjectStoreId.value),
        isSkippable: () => false,
    },
    preview: {
        label: "Preview",
        instructions: "Review what will be moved and the estimated impact before starting.",
        isValid: () => Boolean(storagePreview.value?.snapshot_id) && !storageExecuting.value,
        isSkippable: () => false,
    },
});

const isBusy = computed(() => storagePreviewLoading.value || storageExecuting.value);

const showProxy = computed({
    get: () => props.show,
    set: (value: boolean) => emit("update:show", value),
});

const storageTargetOptions = computed<SelectableObjectStoreWithId[]>(() => {
    const stores = objectStoreStore.selectableObjectStores ?? [];
    return stores
        .filter(
            (store): store is UserConcreteObjectStoreModel & { object_store_id: string } =>
                Boolean(store.object_store_id) && !store.hidden,
        )
        .map((store) => store);
});

const selectedTargetObjectStore = computed<SelectableObjectStoreWithId | null>(() => {
    if (!selectedTargetObjectStoreId.value) {
        return null;
    }
    return storageTargetOptions.value.find((s) => s.object_store_id === selectedTargetObjectStoreId.value) ?? null;
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

function onCancel() {
    showProxy.value = false;
    resetState();
}

function onTargetStoreChanged() {
    previewError.value = null;
    executionError.value = null;
}

function onTargetStoreSelected(target: SelectableObjectStoreWithId | null) {
    selectedTargetObjectStoreId.value = target?.object_store_id ?? null;
    onTargetStoreChanged();
}

function resetState() {
    wizard.goTo("configure");
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
        const previewResponse = await bulkStoragePreview(
            props.history,
            selectedTargetObjectStoreId.value,
            filters,
            items,
        );
        if (!previewResponse) {
            throw new Error("Failed to preview storage operation.");
        }
        storagePreview.value = previewResponse;
    } catch (error) {
        storagePreview.value = null;
        previewError.value =
            errorMessageAsString(error) || "An unknown error occurred while previewing the storage operation.";
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
        executionError.value =
            errorMessageAsString(error) || "An unknown error occurred while executing the storage operation.";
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
    <GModal :show.sync="showProxy" title="Move Datasets to New Storage Location" size="medium" overflow-visible>
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
                <div class="mb-3">
                    <label class="d-block mb-1 font-weight-bold" for="storage-target-select">
                        Target storage location
                    </label>
                    <LoadingSpan v-if="objectStoresLoading" message="Loading Galaxy storage information" />
                    <BAlert v-else-if="loadErrorMessage" show variant="danger" class="mb-2">
                        {{ loadErrorMessage }}
                    </BAlert>
                    <Multiselect
                        v-else
                        id="storage-target-select"
                        :value="selectedTargetObjectStore"
                        :options="storageTargetOptions"
                        :allow-empty="false"
                        :searchable="false"
                        :show-labels="false"
                        track-by="object_store_id"
                        label="name"
                        placeholder="Select target storage location"
                        class="w-100 multiselect--soft-option-highlight"
                        @input="onTargetStoreSelected">
                        <template v-slot:singleLabel="{ option }">
                            <span>{{ option.name ?? "Unknown storage location" }}</span>
                        </template>
                        <template v-slot:option="{ option }">
                            <div class="w-100 text-wrap py-1">
                                <div class="d-flex align-items-start justify-content-between">
                                    <span class="font-weight-bold">{{
                                        option.name ?? "Unknown storage location"
                                    }}</span>
                                    <ObjectStoreBadges :badges="option.badges" size="lg" class="ml-2 flex-shrink-0" />
                                </div>
                                <div v-if="option.description" class="small text-muted mt-1 text-break">
                                    {{ option.description }}
                                </div>
                                <QuotaSourceUsageProvider
                                    v-if="option.quota && option.quota.enabled"
                                    v-slot="{ result: quotaUsage, loading: isLoadingUsage }"
                                    :quota-source-label="option.quota.source">
                                    <LoadingSpan v-if="isLoadingUsage" message="Loading quota" />
                                    <QuotaUsageBar
                                        v-else-if="quotaUsage"
                                        :quota-usage="quotaUsage"
                                        :embedded="true"
                                        class="mt-1" />
                                </QuotaSourceUsageProvider>
                            </div>
                        </template>
                    </Multiselect>
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

                <StorageOperationPreviewReport
                    v-else-if="storagePreview"
                    :preview="storagePreview"
                    :target-store-id="selectedTargetObjectStoreId || ''" />
            </div>
        </GenericWizard>
    </GModal>
</template>
