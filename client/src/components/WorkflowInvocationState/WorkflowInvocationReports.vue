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
</script>

<template>
    <InvocationReport
        v-if="currentView === 'fromTemplate'"
        :invocation-id="props.invocationId"
        from-runtime-report
        @view-existing-reports="currentView = 'editedReports'" />
    <div v-else-if="currentView === 'editedReports'">
        <!-- TODO: For now, no way to route back -->
        <HistoryPageView :history-id="props.historyId" :invocation-id="props.invocationId" />
    </div>
    <div v-else-if="currentView === 'editedReport'">
        <!-- TODO: Placeholder for a specific edited report -->
        <p>Specific edited report goes here.</p>
    </div>
</template>
