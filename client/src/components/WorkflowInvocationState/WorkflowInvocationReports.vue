<script setup lang="ts">
import { ref } from "vue";

import HistoryPageView from "../PageEditor/HistoryPageView.vue";
import InvocationReport from "../Workflow/InvocationReport.vue";

const props = defineProps<{
    invocationId: string;
    historyId: string;
}>();

/** Tracks what is currently being viewed in the reports section:
 * - `fromTemplate` shows the original report generated from the template
 * - `editedReports` shows a list of edited reports if any exist
 * - `editedReport` shows a specific edited report when selected from the list
 */
const currentView = ref<"fromTemplate" | "editedReports" | "editedReport">("fromTemplate");

const currentEditedReportId = ref<string | null>(null);
const displayOnly = ref(false);

function editOrViewPage(pageId: string, displayOnlyValue: boolean) {
    currentView.value = "editedReport";
    currentEditedReportId.value = pageId;
    displayOnly.value = displayOnlyValue;
}

function goBackFromEditedReport() {
    currentView.value = "editedReports";
    currentEditedReportId.value = null;
    displayOnly.value = false;
}
</script>

<template>
    <InvocationReport
        v-if="currentView === 'fromTemplate'"
        :invocation-id="props.invocationId"
        from-runtime-report
        @view-existing-reports="currentView = 'editedReports'" />
    <div v-else-if="currentView === 'editedReports'">
        <HistoryPageView
            :history-id="props.historyId"
            :invocation-id="props.invocationId"
            emits-actions
            @edit-page="(pageId) => editOrViewPage(pageId, false)"
            @go-back="currentView = 'fromTemplate'"
            @view-page="(pageId) => editOrViewPage(pageId, true)" />
    </div>
    <div v-else-if="currentView === 'editedReport'">
        <HistoryPageView
            :history-id="props.historyId"
            :invocation-id="props.invocationId"
            :page-id="currentEditedReportId || undefined"
            :display-only="displayOnly"
            emits-actions
            @edit-page="(pageId) => editOrViewPage(pageId, false)"
            @go-back="goBackFromEditedReport"
            @view-page="(pageId) => editOrViewPage(pageId, true)" />
    </div>
</template>
