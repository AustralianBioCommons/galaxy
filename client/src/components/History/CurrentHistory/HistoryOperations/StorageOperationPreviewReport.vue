<script setup lang="ts">
import { BAlert, BBadge, BListGroup, BListGroupItem } from "bootstrap-vue";
import { computed } from "vue";

import type { StorageOperationPreviewResponse } from "@/api/histories";
import { useObjectStoreStore } from "@/stores/objectStoreStore";
import { getIneligibleReasonDescription } from "@/utils/storageOperations";
import { bytesToString } from "@/utils/utils";

const props = defineProps<{
    preview: StorageOperationPreviewResponse;
    targetStoreId: string;
}>();

const objectStoreStore = useObjectStoreStore();

const transferEstimate = computed(() => {
    const bytes = props.preview.estimates?.bytes_to_transfer;
    if (bytes == null) {
        return "Not available";
    }
    return bytesToString(bytes);
});

const quotaAvailabilityEntries = computed(() => {
    const transfers = props.preview.estimates?.quota_delta_transfers ?? [];
    const byStore = new Map<string, number>();

    for (const transfer of transfers) {
        const bytes = transfer.bytes ?? 0;
        byStore.set(transfer.source_object_store_id, (byStore.get(transfer.source_object_store_id) ?? 0) + bytes);
        byStore.set(transfer.target_object_store_id, (byStore.get(transfer.target_object_store_id) ?? 0) - bytes);
    }

    return Array.from(byStore.entries())
        .map(([storeId, availableQuotaDelta]) => ({
            storeId,
            availableQuotaDelta,
        }))
        .sort((a, b) => a.storeId.localeCompare(b.storeId));
});

const quotaGains = computed(() => quotaAvailabilityEntries.value.filter((entry) => entry.availableQuotaDelta > 0));
const quotaLosses = computed(() => quotaAvailabilityEntries.value.filter((entry) => entry.availableQuotaDelta < 0));

const ineligibleReasonBreakdown = computed(() => {
    return (props.preview.eligibility?.reasons ?? [])
        .map((reason) => ({
            code: reason.reason_code,
            count: reason.count,
        }))
        .sort((a, b) => b.count - a.count);
});

const hasIneligible = computed(() => props.preview.eligibility.ineligible_count > 0);
const hasWarnings = computed(() => Boolean(props.preview.warnings?.length));

const targetStoreName = computed(() => {
    return objectStoreStore.getObjectStoreNameById(props.targetStoreId) ?? "Unknown storage location";
});

function getObjectStoreLabel(storeId: string) {
    return objectStoreStore.getObjectStoreNameById(storeId) ?? "Unknown storage location";
}

function formatQuotaDelta(delta: number) {
    const sign = delta > 0 ? "+" : "-";
    return `${sign}${bytesToString(Math.abs(delta))}`;
}
</script>

<template>
    <div class="storage-operation-preview-report">
        <!-- Destination -->
        <p class="mb-3">
            <span class="text-muted">Moving to: </span>
            <strong>{{ targetStoreName }}</strong>
        </p>

        <!-- Selection counts -->
        <div class="d-flex flex-wrap mb-3">
            <div class="mr-4 mb-2">
                <div class="font-weight-bold h5 mb-0">{{ preview.selection_counts.selected_items_count }}</div>
                <small class="text-muted">Selected items</small>
            </div>
            <div class="mr-4 mb-2">
                <div class="font-weight-bold h5 mb-0">{{ preview.selection_counts.expanded_leaf_count }}</div>
                <small class="text-muted">Expanded datasets</small>
            </div>
            <div class="mr-4 mb-2">
                <div class="font-weight-bold h5 mb-0">{{ preview.selection_counts.unique_dataset_count }}</div>
                <small class="text-muted">Unique datasets</small>
            </div>
        </div>

        <!-- Eligibility summary -->
        <div class="d-flex align-items-center flex-wrap mb-3">
            <BBadge variant="success" class="mr-2 mb-1 px-2 py-1">
                {{ preview.eligibility.eligible_count }} eligible
            </BBadge>
            <BBadge :variant="hasIneligible ? 'danger' : 'secondary'" class="mr-3 mb-1 px-2 py-1">
                {{ preview.eligibility.ineligible_count }} ineligible
            </BBadge>
            <span class="text-muted small mb-1">Estimated transfer: {{ transferEstimate }}</span>
        </div>

        <!-- Storage quota changes -->
        <div v-if="quotaAvailabilityEntries.length" class="mb-3">
            <p class="mb-1 font-weight-bold">Quota availability impact by location:</p>
            <p class="text-muted small mb-2">
                Positive values mean you gain available quota. Negative values mean you lose available quota.
            </p>
            <BListGroup flush>
                <BListGroupItem
                    v-for="entry in quotaGains"
                    :key="entry.storeId"
                    class="px-0 py-1 d-flex justify-content-between align-items-center border-0">
                    <div class="d-flex align-items-center">
                        <BBadge variant="success" class="mr-2">Gain</BBadge>
                        <span class="text-muted small">{{ getObjectStoreLabel(entry.storeId) }}</span>
                    </div>
                    <span class="small text-success">{{ formatQuotaDelta(entry.availableQuotaDelta) }}</span>
                </BListGroupItem>
                <BListGroupItem
                    v-for="entry in quotaLosses"
                    :key="`loss-${entry.storeId}`"
                    class="px-0 py-1 d-flex justify-content-between align-items-center border-0">
                    <div class="d-flex align-items-center">
                        <BBadge variant="warning" class="mr-2">Loss</BBadge>
                        <span class="text-muted small">{{ getObjectStoreLabel(entry.storeId) }}</span>
                    </div>
                    <span class="small text-warning">{{ formatQuotaDelta(entry.availableQuotaDelta) }}</span>
                </BListGroupItem>
            </BListGroup>
        </div>

        <!-- Ineligibility breakdown -->
        <div v-if="ineligibleReasonBreakdown.length" class="mb-3">
            <p class="mb-1 font-weight-bold">Why some datasets cannot be moved:</p>
            <BListGroup flush>
                <BListGroupItem
                    v-for="reason in ineligibleReasonBreakdown"
                    :key="reason.code"
                    class="px-0 py-2 d-flex align-items-start border-0">
                    <BBadge variant="danger" class="mr-2 mt-1 flex-shrink-0">{{ reason.count }}</BBadge>
                    <div>
                        <div class="font-weight-bold small">
                            {{ getIneligibleReasonDescription(reason.code).label }}
                        </div>
                        <div v-if="getIneligibleReasonDescription(reason.code).description" class="text-muted small">
                            {{ getIneligibleReasonDescription(reason.code).description }}
                        </div>
                    </div>
                </BListGroupItem>
            </BListGroup>
        </div>

        <!-- Warnings -->
        <BAlert v-if="hasWarnings" show variant="warning" class="mb-0 py-2">
            <div class="font-weight-bold small mb-1">Warnings</div>
            <div v-for="(warning, index) in preview.warnings" :key="index" class="small py-1">
                {{ warning }}
            </div>
        </BAlert>
    </div>
</template>
