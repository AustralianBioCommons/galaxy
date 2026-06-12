<script setup lang="ts">
import { faArrowLeft, faEdit } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";

import type { PAGE_LABELS } from "@/components/Page/constants";

import type { MarkdownConfig } from "../Markdown/types.js";

import GButton from "../BaseComponents/GButton.vue";
import Markdown from "../Markdown/Markdown.vue";

const props = defineProps<{
    labels: (typeof PAGE_LABELS)[keyof typeof PAGE_LABELS];
    currentTitle?: string;
    markdownConfig?: MarkdownConfig;
}>();

const emit = defineEmits<{
    (e: "edit"): void;
    (e: "back"): void;
}>();
</script>

<template>
    <div class="d-flex flex-column">
        <div
            class="page-display-toolbar d-flex align-items-center p-2 border-bottom"
            data-description="page display toolbar">
            <GButton color="blue" transparent size="small" data-description="page back button" @click="emit('back')">
                <FontAwesomeIcon :icon="faArrowLeft" />
                {{ props.labels.editorBackLabel }}
            </GButton>
            <span class="flex-grow-1 text-center font-weight-bold">
                {{ props.currentTitle || props.labels.defaultTitle }}
            </span>
            <GButton color="blue" outline size="small" data-description="page edit button" @click="emit('edit')">
                <FontAwesomeIcon :icon="faEdit" />
                Edit
            </GButton>
        </div>
        <div class="page-display-content" data-description="page rendered view">
            <Markdown
                v-if="markdownConfig"
                class="px-3 pt-3"
                :markdown-config="markdownConfig"
                read-only
                no-heading
                download-endpoint="" />
        </div>
    </div>
</template>

<style scoped>
.page-display-toolbar {
    background: var(--color-grey-100);
}

.page-display-content {
    overflow: auto;
    flex: 1 1 0;
}
</style>
