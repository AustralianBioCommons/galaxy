<script setup lang="ts">
import { faCheckSquare, faSquare } from "@fortawesome/free-regular-svg-icons";
import { faClock, faPlus, faTimes, faTrash } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { storeToRefs } from "pinia";
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router/composables";

import { GalaxyApi } from "@/api";
import { useConfirmDialog } from "@/composables/confirmDialog";
import { useSidebarSelection } from "@/composables/useSidebarSelection";
import { useChatStore } from "@/stores/chatStore";

import { getAgentIcon } from "./agentTypes";
import type { ChatHistoryItem } from "./chatTypes";

import GButton from "../BaseComponents/GButton.vue";
import ChatModeSelector from "./ChatModeSelector.vue";
import ActivityPanel from "@/components/Panels/ActivityPanel.vue";
import ScrollList from "@/components/ScrollList/ScrollList.vue";
import UtcDate from "@/components/UtcDate.vue";

const { confirm } = useConfirmDialog();
const route = useRoute();
const router = useRouter();
const chatStore = useChatStore();

const { chatHistory, loading } = storeToRefs(chatStore);

const {
    selectionMode,
    selectedIds,
    allSelected,
    toggleSelectionMode,
    toggleSelectAll,
    handleSelectionClick,
    pruneAfterDelete,
} = useSidebarSelection(chatHistory, (item) => item.id);

const currentExhangeId = computed(() => {
    if (chatStore.isCenterMode) {
        return route.params["exchangeId"] || null;
    } else {
        return chatStore.activeChatId;
    }
});

onMounted(async () => {
    await chatStore.loadHistory();
});

function handleItemClick(item: ChatHistoryItem, index: number, event: MouseEvent) {
    if (handleSelectionClick(item, index, event)) {
        return;
    }
    if (chatStore.isCenterMode) {
        router.push(`/galaxyai/${item.id}`);
    } else {
        chatStore.setActiveChatId(item.id);
        chatStore.showChat();
    }
}

function startNewChat() {
    if (chatStore.isCenterMode) {
        router.push("/galaxyai/new");
    } else {
        chatStore.setActiveChatId(null);
        chatStore.showChat();
    }
}

async function deleteSelected() {
    if (selectedIds.value.size === 0) {
        return;
    }

    const confirmed = await confirm(
        `Are you sure you want to delete the ${selectedIds.value.size} selected conversation(s)?`,
        {
            title: "Delete Conversations",
            okText: "Delete",
            okIcon: faTrash,
            okColor: "red",
        },
    );
    if (confirmed) {
        const ids = Array.from(selectedIds.value);
        try {
            const { error } = await GalaxyApi().PUT("/api/chat/exchanges/batch/delete", {
                body: { ids },
            });
            if (!error) {
                chatStore.deleteChats(selectedIds.value);
                pruneAfterDelete();
            }
        } catch (e) {
            console.error("Failed to delete exchanges:", e);
        }
    }
}
</script>

<template>
    <ActivityPanel title="GalaxyAI">
        <template v-slot:header-buttons>
            <GButton color="blue" outline title="New Chat" @click="startNewChat">
                <FontAwesomeIcon :icon="faPlus" fixed-width />
            </GButton>
            <GButton
                :color="selectionMode ? 'grey' : 'red'"
                outline
                :title="selectionMode ? 'Cancel selection' : 'Select chats to delete'"
                @click="toggleSelectionMode">
                <FontAwesomeIcon :icon="selectionMode ? faTimes : faTrash" fixed-width />
            </GButton>
        </template>

        <template v-slot:header>
            <ChatModeSelector class="pt-1" />
        </template>

        <div v-if="selectionMode && chatHistory.length > 0" class="selection-toolbar">
            <!-- eslint-disable-next-line vuejs-accessibility/click-events-have-key-events vuejs-accessibility/no-static-element-interactions -->
            <span class="select-all-toggle" @click="toggleSelectAll">
                <FontAwesomeIcon :icon="allSelected ? faCheckSquare : faSquare" fixed-width />
                {{ allSelected ? "Deselect all" : "Select all" }}
            </span>
            <button class="btn btn-sm btn-danger" :disabled="selectedIds.size === 0" @click="deleteSelected">
                Delete {{ selectedIds.size > 0 ? selectedIds.size : "" }}
            </button>
        </div>

        <ScrollList
            :prop-items="chatHistory"
            :prop-busy="loading"
            :prop-total-count="chatHistory.length"
            :item-key="(item) => item.id"
            load-disabled
            in-panel
            name="chat"
            name-plural="chats">
            <template v-slot:item="{ item, index }">
                <!-- eslint-disable-next-line vuejs-accessibility/click-events-have-key-events vuejs-accessibility/no-static-element-interactions -->
                <div
                    class="chat-history-item d-flex align-items-start p-2 border-bottom unselectable"
                    :class="{ selected: selectedIds.has(item.id), current: item.id === currentExhangeId }"
                    role="button"
                    tabindex="0"
                    @click="(event) => handleItemClick(item, index, event)">
                    <span v-if="selectionMode" class="history-checkbox">
                        <FontAwesomeIcon :icon="selectedIds.has(item.id) ? faCheckSquare : faSquare" fixed-width />
                    </span>
                    <div class="history-content">
                        <div class="history-query">{{ item.query }}</div>
                        <div class="history-meta">
                            <span class="history-agent">
                                <FontAwesomeIcon :icon="getAgentIcon(item.agent_type)" fixed-width />
                            </span>
                            <span class="history-time">
                                <FontAwesomeIcon :icon="faClock" class="mr-1" />
                                <UtcDate :date="item.timestamp" mode="elapsed" />
                            </span>
                        </div>
                    </div>
                </div>
            </template>
        </ScrollList>
    </ActivityPanel>
</template>

<style lang="scss" scoped>
@import "@/style/scss/theme/blue.scss";

.selection-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.375rem 0.5rem;
    border-bottom: 1px solid darken($panel-bg-color, 5%);
    font-size: 0.75rem;
}

.select-all-toggle {
    cursor: pointer;
    color: $text-muted;
    display: flex;
    align-items: center;
    gap: 0.25rem;

    &:hover {
        color: $text-color;
    }
}

:deep(.chat-history-item) {
    cursor: pointer;
    &:hover {
        background: var(--color-grey-200) !important;
    }
}
:deep(.chat-history-item.selected) {
    background: var(--color-blue-200);
}
:deep(.chat-history-item.current) {
    border-left: 0.25rem solid $brand-primary;
}

.history-checkbox {
    flex-shrink: 0;
    color: $text-muted;
    padding-top: 0.1rem;
}

.history-content {
    flex: 1;
    min-width: 0;
}

.history-query {
    font-size: 0.8rem;
    color: $text-color;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin-bottom: 0.2rem;
}

.history-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.7rem;
    color: $text-light;

    .history-agent {
        color: $brand-primary;
    }

    .history-time {
        display: flex;
        align-items: center;
        gap: 0.25rem;
    }
}
</style>
