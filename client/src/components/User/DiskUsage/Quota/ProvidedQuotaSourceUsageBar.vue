<template>
    <div v-if="objectStore.quota.enabled">
        <LoadingSpan v-if="isLoadingUsage" :message="loadingMessage" />
        <QuotaUsageBar v-else-if="quotaUsage" :quota-usage="quotaUsage" :embedded="true" :compact="true" />
    </div>
</template>

<script setup lang="ts">
import { computed, watch } from "vue";

import type { ConcreteObjectStoreModel } from "@/api";
import { useQuotaUsageStore } from "@/stores/quotaUsageStore";

import QuotaUsageBar from "./QuotaUsageBar.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

interface Props {
    objectStore: ConcreteObjectStoreModel;
    embedded?: boolean;
    compact?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    embedded: true,
    compact: false,
});

const loadingMessage = "Loading Galaxy storage information";

const quotaUsageStore = useQuotaUsageStore();

const quotaSourceLabel = computed(() => props.objectStore.quota.source ?? null);
const quotaSourceKey = computed(() => quotaSourceLabel.value ?? "__null__");

const quotaUsage = computed(() => quotaUsageStore.getQuotaUsageBySourceLabel(quotaSourceLabel.value) ?? null);
const isLoadingUsage = computed(() => Boolean(quotaUsageStore.loadingBySource[quotaSourceKey.value]));

watch(
    () => [props.objectStore.quota.enabled, quotaSourceLabel.value] as const,
    ([enabled, sourceLabel]) => {
        if (!enabled) {
            return;
        }

        void quotaUsageStore.loadQuotaUsageForSource(sourceLabel, true);
    },
    { immediate: true },
);
</script>
