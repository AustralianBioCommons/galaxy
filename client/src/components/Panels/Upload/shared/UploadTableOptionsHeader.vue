<script setup lang="ts">
import { BFormCheckbox } from "bootstrap-vue";

import type { UploadOptionVisibility } from "./uploadOptionVisibility";
import { defaultUploadOptionVisibility } from "./uploadOptionVisibility";

interface Props {
    /** All items have spaceToTab enabled */
    allSpaceToTab: boolean;
    /** Some but not all items have spaceToTab enabled */
    spaceToTabIndeterminate: boolean;
    /** All items have toPosixLines enabled */
    allToPosixLines: boolean;
    /** Some but not all items have toPosixLines enabled */
    toPosixLinesIndeterminate: boolean;
    /** Which option toggles are visible */
    optionVisibility?: UploadOptionVisibility;
    /** All items have deferred enabled */
    allDeferred?: boolean;
    /** Some but not all items have deferred enabled */
    deferredIndeterminate?: boolean;
    /** All items have auto-decompress enabled */
    allAutoDecompress?: boolean;
    /** Some but not all items have auto-decompress enabled */
    autoDecompressIndeterminate?: boolean;
}

withDefaults(defineProps<Props>(), {
    optionVisibility: () => defaultUploadOptionVisibility,
    allDeferred: false,
    deferredIndeterminate: false,
    allAutoDecompress: true,
    autoDecompressIndeterminate: false,
});

const emit = defineEmits<{
    (e: "toggle-space-to-tab"): void;
    (e: "toggle-to-posix-lines"): void;
    (e: "toggle-deferred"): void;
    (e: "toggle-auto-decompress"): void;
}>();

function handleToggleSpaceToTab() {
    emit("toggle-space-to-tab");
}

function handleToggleToPosixLines() {
    emit("toggle-to-posix-lines");
}

function handleToggleDeferred() {
    emit("toggle-deferred");
}

function handleToggleAutoDecompress() {
    emit("toggle-auto-decompress");
}
</script>

<template>
    <div class="options-header">
        <span class="options-title">Upload Settings</span>
        <div class="options-controls d-inline-flex align-items-center flex-nowrap">
            <BFormCheckbox
                v-g-tooltip.hover
                :checked="allSpaceToTab"
                :indeterminate="spaceToTabIndeterminate"
                size="sm"
                title="Toggle all: Convert spaces to tab characters"
                @change="handleToggleSpaceToTab">
                <span class="small">Spaces→Tabs</span>
            </BFormCheckbox>
            <BFormCheckbox
                v-if="optionVisibility.posix"
                v-g-tooltip.hover
                :checked="allToPosixLines"
                :indeterminate="toPosixLinesIndeterminate"
                size="sm"
                title="Toggle all: Convert line endings to POSIX standard"
                @change="handleToggleToPosixLines">
                <span class="small">POSIX</span>
            </BFormCheckbox>
            <BFormCheckbox
                v-if="optionVisibility.deferred"
                v-g-tooltip.hover
                :checked="allDeferred"
                :indeterminate="deferredIndeterminate"
                size="sm"
                title="Toggle all: Galaxy will store a reference and fetch data only when needed by a tool"
                @change="handleToggleDeferred">
                <span class="small">Deferred</span>
            </BFormCheckbox>
            <BFormCheckbox
                v-if="optionVisibility.autoDecompress"
                v-g-tooltip.hover
                :checked="allAutoDecompress"
                :indeterminate="autoDecompressIndeterminate"
                size="sm"
                title="Toggle all: Disable automatic decompression of compressed inputs"
                @change="handleToggleAutoDecompress">
                <span class="small">Auto-decompress</span>
            </BFormCheckbox>
        </div>
    </div>
</template>

<style scoped lang="scss">
@import "../shared/upload-table-shared.scss";
</style>
