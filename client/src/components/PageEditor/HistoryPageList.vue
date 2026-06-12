<script setup lang="ts">
import { faPlus } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, toRef } from "vue";

import type { HistoryPageSummary } from "@/api/pages";
import { PAGE_LABELS } from "@/components/Page/constants";
import { useHistoryBreadCrumbsTo } from "@/composables/historyBreadcrumbs";

import BreadcrumbHeading from "../Common/BreadcrumbHeading.vue";
import PageCard from "./PageCard.vue";
import GButton from "@/components/BaseComponents/GButton.vue";

const props = defineProps<{
    pages: HistoryPageSummary[];
    historyId: string;
    invocationId?: string;
    noHeading?: boolean;
}>();

const emit = defineEmits<{
    (e: "select", pageId: string): void;
    (e: "view", pageId: string): void;
    (e: "create"): void;
}>();

const labels = computed(() => (props.invocationId ? PAGE_LABELS.invocation : PAGE_LABELS.history));

const { breadcrumbItems } = useHistoryBreadCrumbsTo(toRef(props, "historyId"), labels.value.entityNamePlural);
</script>

<template>
    <div class="d-flex flex-column overflow-hidden" data-description="history page list">
        <BreadcrumbHeading v-if="!props.noHeading" :items="breadcrumbItems">
            <GButton
                class="text-nowrap"
                color="blue"
                size="small"
                data-description="create page button"
                @click="emit('create')">
                <FontAwesomeIcon :icon="faPlus" />
                {{ labels.newButton }}
            </GButton>
        </BreadcrumbHeading>

        <div v-if="pages.length === 0" class="empty-state text-center p-4" data-description="page empty state">
            <p class="text-muted">{{ labels.emptyStateTitle }}</p>
            <p class="text-muted small">
                {{ labels.emptyStateDescription }}
            </p>
        </div>

        <div v-else class="page-items mt-3">
            <PageCard
                v-for="page in pages"
                :key="page.id"
                data-description="page item"
                :page="page"
                :default-title="labels.defaultTitle"
                :entity-name="labels.entityName"
                :edit-title="labels.editButton"
                :show-invocation-badge="!props.invocationId"
                :view-title="labels.viewButton"
                @select="emit('select', page.id)"
                @view="emit('view', page.id)" />
        </div>
    </div>
</template>

<style scoped>
.page-item:hover {
    background: var(--panel-header-bg);
}
.page-items {
    flex: 1 1 0;
    overflow-y: auto;
}
.cursor-pointer {
    cursor: pointer;
}
</style>
