<script setup lang="ts">
import { faDatabase } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BAlert, BModal } from "bootstrap-vue";
import { storeToRefs } from "pinia";
import { computed, ref } from "vue";

import { useTargetObjectStoreUploadState } from "@/composables/upload/useTargetObjectStoreUploadState";
import { useObjectStoreStore } from "@/stores/objectStoreStore";

import SelectObjectStore from "@/components/ObjectStore/SelectObjectStore.vue";

interface Props {
    targetObjectStoreId: string | null;
    targetHistoryId: string;
    storeCaption?: string;
    changeLinkText?: string;
    changeLinkTooltip?: string;
    modalTitle?: string;
}

const props = withDefaults(defineProps<Props>(), {
    storeCaption: "Target storage",
    changeLinkText: "change",
    changeLinkTooltip: "Change target storage location",
    modalTitle: "Select storage location",
});

const emit = defineEmits<{
    (e: "select-store", selection: { object_store_id: string | null; private: boolean }): void;
}>();

const showModal = ref(false);

const objectStoreStore = useObjectStoreStore();
const { selectableObjectStores } = storeToRefs(objectStoreStore);

const canChangeStore = computed(() => (selectableObjectStores.value?.length ?? 0) > 1);

const { storeName, storeDescription, warningMessage } = useTargetObjectStoreUploadState(
    computed(() => props.targetObjectStoreId),
    computed(() => props.targetHistoryId),
);

function openStoreSelector() {
    showModal.value = true;
}

function handleStoreSelected(objectStoreId: string | null, isPrivate: boolean) {
    showModal.value = false;
    emit("select-store", {
        object_store_id: objectStoreId,
        private: isPrivate,
    });
}
</script>

<template>
    <div>
        <div class="d-flex align-items-center">
            <span class="d-flex flex-gapx-1 align-items-center">
                <span v-g-tooltip.hover title="The storage location where these datasets will be uploaded.">
                    <FontAwesomeIcon class="mr-1" :icon="faDatabase" />{{ storeCaption }}:
                </span>
                <span v-g-tooltip.hover :title="storeDescription">
                    <b>{{ storeName }}</b>
                </span>
            </span>
            <a
                v-if="canChangeStore"
                v-g-tooltip.hover
                href="#"
                class="change-store-link ml-2"
                :title="changeLinkTooltip"
                @click.prevent="openStoreSelector">
                {{ changeLinkText }}
            </a>
        </div>

        <BAlert v-if="warningMessage" show variant="warning" class="mb-2 py-1">
            {{ warningMessage }}
        </BAlert>

        <BModal
            v-model="showModal"
            centered
            scrollable
            size="lg"
            :title="modalTitle"
            title-class="h-sm"
            title-tag="h3"
            ok-only
            ok-title="Close">
            <SelectObjectStore
                for-what="New datasets uploaded in this history"
                :selected-object-store-id="targetObjectStoreId"
                default-option-title="Use history preference"
                default-option-description="Uploads will follow the selected history storage preference."
                @onSubmit="handleStoreSelected" />
        </BModal>
    </div>
</template>

<style scoped lang="scss">
@import "@/style/scss/theme/blue.scss";

.change-store-link {
    &:hover {
        text-decoration: underline;
        color: $brand-primary;
    }
}
</style>
