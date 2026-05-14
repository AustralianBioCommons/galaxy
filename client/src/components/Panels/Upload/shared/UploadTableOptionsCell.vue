<script setup lang="ts">
import { BFormCheckbox } from "bootstrap-vue";

import type { UploadOptionVisibility } from "./uploadOptionVisibility";
import { defaultUploadOptionVisibility } from "./uploadOptionVisibility";

interface Props {
    /** Whether to convert spaces to tabs */
    spaceToTab: boolean;
    /** Whether to convert to POSIX line endings */
    toPosixLines: boolean;
    /** Which option toggles are visible */
    optionVisibility?: UploadOptionVisibility;
    /** Whether to defer data fetching (optional, for URLs) */
    deferred?: boolean;
    /** Whether to auto-decompress compressed inputs */
    autoDecompress?: boolean;
}

withDefaults(defineProps<Props>(), {
    optionVisibility: () => defaultUploadOptionVisibility,
    deferred: false,
    autoDecompress: true,
});

const emit = defineEmits<{
    (e: "updateSpaceToTab", value: boolean): void;
    (e: "updateToPosixLines", value: boolean): void;
    (e: "updateDeferred", value: boolean): void;
    (e: "updateAutoDecompress", value: boolean): void;
}>();

function updateSpaceToTab(value: boolean) {
    emit("updateSpaceToTab", value);
}

function updateToPosixLines(value: boolean) {
    emit("updateToPosixLines", value);
}

function updateDeferred(value: boolean) {
    emit("updateDeferred", value);
}

function updateAutoDecompress(value: boolean) {
    emit("updateAutoDecompress", value);
}
</script>

<template>
    <div class="options-cell options-controls d-inline-flex align-items-center flex-nowrap">
        <BFormCheckbox
            v-g-tooltip.hover
            :checked="spaceToTab"
            size="sm"
            title="Convert spaces to tab characters"
            @change="updateSpaceToTab">
            <span class="small">Spaces→Tabs</span>
        </BFormCheckbox>
        <BFormCheckbox
            v-if="optionVisibility.posix"
            v-g-tooltip.hover
            :checked="toPosixLines"
            size="sm"
            title="Convert line endings to POSIX standard"
            @change="updateToPosixLines">
            <span class="small">POSIX</span>
        </BFormCheckbox>
        <div v-if="optionVisibility.deferred" data-test-id="deferred-toggle">
            <BFormCheckbox
                v-g-tooltip.hover
                :checked="deferred"
                size="sm"
                title="Galaxy will store a reference and fetch data only when needed by a tool"
                @change="updateDeferred">
                <span class="small">Deferred</span>
            </BFormCheckbox>
        </div>
        <div v-if="optionVisibility.autoDecompress" data-test-id="auto-decompress-toggle">
            <BFormCheckbox
                v-g-tooltip.hover
                :checked="autoDecompress"
                size="sm"
                title="Automatic decompression of compressed inputs after upload"
                @change="updateAutoDecompress">
                <span class="small">Auto-decompress</span>
            </BFormCheckbox>
        </div>
    </div>
</template>
