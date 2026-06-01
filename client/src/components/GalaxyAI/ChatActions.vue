<script setup lang="ts">
import {
    faAngleDoubleDown,
    faChevronDown,
    faChevronUp,
    faColumns,
    faExpand,
    faExternalLinkAlt,
    faList,
    faPlus,
    faTimes,
    faTrash,
} from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import { useActivityStore } from "@/stores/activityStore.js";

import GButton from "../BaseComponents/GButton.vue";

const props = defineProps<{
    source: "docked" | "panel" | "center";
    collapsed?: boolean;
    enableDelete?: boolean;
}>();

const emit = defineEmits<{
    (e: "close"): void;
    (e: "delete"): void;
    (e: "dock-to", location: "right" | "bottom"): void;
    (e: "maximize"): void;
    (e: "pop-out"): void;
    (e: "start-new"): void;
    (e: "update:collapsed", value: boolean): void;
}>();

const activityStore = useActivityStore("default");

const showingActivityPanel = computed(() => activityStore.toggledSideBar === "galaxyai");

function onOperation(operation: "start-new" | "dock-right" | "dock-bottom") {
    if (operation === "start-new") {
        emit("start-new");
    } else if (operation === "dock-right") {
        emit("dock-to", "right");
    } else if (operation === "dock-bottom") {
        emit("dock-to", "bottom");
    }
    emit("update:collapsed", false);
}
</script>

<template>
    <div class="chat-panel-actions">
        <GButton
            size="small"
            transparent
            outline
            :pressed="showingActivityPanel"
            :title="showingActivityPanel ? 'Hide Chats Panel' : 'Show Chats Panel'"
            @click="activityStore.toggleSideBar('galaxyai')">
            <FontAwesomeIcon :icon="faList" fixed-width />
            <span class="btn-label">
                <span v-if="showingActivityPanel">Hide</span>
                <span v-else>Show</span>
                Chats
            </span>
        </GButton>
        <GButton
            data-description="new chat button"
            size="small"
            transparent
            title="Start New Chat"
            @click="onOperation('start-new')">
            <FontAwesomeIcon :icon="faPlus" fixed-width />
            <span class="btn-label">New</span>
        </GButton>
        <GButton
            v-if="(props.source === 'center' || props.source === 'docked') && !props.collapsed"
            color="red"
            data-description="delete chat button"
            :disabled="!props.enableDelete"
            size="small"
            transparent
            title="Delete this conversation"
            @click="emit('delete')">
            <FontAwesomeIcon :icon="faTrash" fixed-width />
        </GButton>
        <GButton
            v-if="props.source !== 'center'"
            size="small"
            transparent
            title="Open in center view"
            @click="emit('maximize')">
            <FontAwesomeIcon :icon="faExpand" fixed-width />
        </GButton>
        <template v-if="props.source === 'center'">
            <GButton size="small" transparent title="Dock to side panel" @click="onOperation('dock-right')">
                <FontAwesomeIcon :icon="faColumns" fixed-width />
            </GButton>
            <GButton size="small" transparent title="Dock to bottom panel" @click="onOperation('dock-bottom')">
                <FontAwesomeIcon :icon="faAngleDoubleDown" fixed-width />
            </GButton>
        </template>
        <GButton size="small" transparent title="Open in floating window" @click="emit('pop-out')">
            <FontAwesomeIcon :icon="faExternalLinkAlt" fixed-width />
        </GButton>
        <GButton
            v-if="props.source === 'panel'"
            size="small"
            transparent
            title="Toggle panel"
            @click="emit('update:collapsed', !props.collapsed)">
            <FontAwesomeIcon :icon="props.collapsed ? faChevronUp : faChevronDown" fixed-width />
        </GButton>
        <GButton v-if="props.source !== 'center'" size="small" transparent title="Close panel" @click="emit('close')">
            <FontAwesomeIcon :icon="faTimes" fixed-width />
        </GButton>
    </div>
</template>

<style scoped>
.chat-panel-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 0.25rem;
}

@container (max-width: 440px) {
    .btn-label {
        display: none;
    }
}
</style>
