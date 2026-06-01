<script setup lang="ts">
import { storeToRefs } from "pinia";
import { ref } from "vue";
import { useRouter } from "vue-router/composables";

import { getGalaxyInstance } from "@/app";
import { useChatStore } from "@/stores/chatStore";

import ChatActions from "./ChatActions.vue";
import GalaxyAI from "@/components/GalaxyAI.vue";

const router = useRouter();
const chatStore = useChatStore();
const { activeChatId } = storeToRefs(chatStore);

const collapsed = ref(false);

function maximize() {
    const path = activeChatId.value ? `/galaxyai/${activeChatId.value}` : "/galaxyai";
    chatStore.setLocation("center");
    chatStore.hideChat();
    router.push(path);
}

function popOut() {
    const Galaxy = getGalaxyInstance();
    const id = activeChatId.value;
    const path = id ? `/galaxyai/${id}` : "/galaxyai/new";
    Galaxy.frame.add({ title: "GalaxyAI", url: `${path}?compact=true` });
    chatStore.hideChat();
}

function close() {
    chatStore.hideChat();
}

function startNewChat() {
    chatStore.showChat(null);
}
</script>

<template>
    <div class="chat-panel" :class="collapsed ? 'collapsed' : 'expanded'">
        <div class="chat-panel-header">
            <span class="chat-panel-title">GalaxyAI</span>
            <ChatActions
                source="panel"
                :collapsed.sync="collapsed"
                @maximize="maximize"
                @pop-out="popOut"
                @close="close"
                @start-new="startNewChat" />
        </div>
        <div v-show="!collapsed" class="chat-panel-body">
            <GalaxyAI :exchange-id="activeChatId || undefined" panel />
        </div>
    </div>
</template>

<style lang="scss" scoped>
@import "@/style/scss/theme/blue.scss";

.chat-panel {
    flex-shrink: 0;
    border-top: $border-default;
}

.chat-panel.expanded {
    height: 50vh;
    display: flex;
    flex-direction: column;
}

.chat-panel-header {
    padding: 0.5rem 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: $panel-bg-color;
    user-select: none;
}

.chat-panel-title {
    font-weight: 600;
    font-size: 0.85rem;
}

.chat-panel-body {
    flex: 1;
    min-height: 0;
    overflow: hidden;
}
</style>
