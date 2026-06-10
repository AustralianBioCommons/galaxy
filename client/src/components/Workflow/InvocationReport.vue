<script setup lang="ts">
import { faFileContract } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, provide, ref } from "vue";
import { useRouter } from "vue-router/composables";

import { fetchInvocationReport } from "@/api/invocations";
import { useConfig } from "@/composables/config";
import { useToast } from "@/composables/toast";

import GButton from "../BaseComponents/GButton.vue";
import HelpText from "../Help/HelpText.vue";
import Markdown from "@/components/Markdown/Markdown.vue";

const props = defineProps<{
    invocationId: string;
    /** Whether to enforce displaying a "Runtime Report" heading with help text */
    fromRuntimeReport?: boolean;
}>();

const emit = defineEmits<{
    (e: "view-existing-reports"): void;
}>();

const { config, isConfigLoaded } = useConfig(true);

const Toast = useToast();

const router = useRouter();

const markdownConfig = ref({});

const exportUrl = computed(() => `/api/invocations/${props.invocationId}/report.pdf`);

fetchReport();

async function fetchReport() {
    try {
        const data = await fetchInvocationReport(props.invocationId);
        markdownConfig.value = data;
    } catch (error) {
        Toast.error("Failed to load invocation report.");
    }
}

function onEdit() {
    router.push(`/pages/create?invocation_id=${props.invocationId}`);
}

// Provide invocationId to all descendant components for inline directive resolution
provide("invocationId", props.invocationId);
</script>

<template>
    <Markdown
        v-if="isConfigLoaded"
        :markdown-config="markdownConfig"
        :enable_beta_markdown_export="config.enable_beta_markdown_export"
        :export-link="exportUrl"
        :download-endpoint="exportUrl"
        direct-download-link
        @onEdit="onEdit">
        <template v-if="props.fromRuntimeReport" v-slot:heading>
            Runtime Report
            <HelpText uri="galaxy.invocations.reports.runtimeReport" info-icon />
        </template>

        <template v-if="props.fromRuntimeReport" v-slot:extra-actions>
            <GButton
                tooltip
                title="Click to view existing/edited report for this workflow invocation"
                outline
                color="blue"
                @click="emit('view-existing-reports')">
                View Existing Reports
                <FontAwesomeIcon :icon="faFileContract" />
            </GButton>
        </template>
    </Markdown>
</template>
