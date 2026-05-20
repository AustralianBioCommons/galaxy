import { storeToRefs } from "pinia";
import { computed, type ComputedRef, type Ref, ref, watch } from "vue";

import type { UserConcreteObjectStoreModel } from "@/api";
import { useHistoryStore } from "@/stores/historyStore";
import { useObjectStoreStore } from "@/stores/objectStoreStore";

interface TargetObjectStoreSelectionState {
    targetObjectStoreId: Ref<string | null>;
    shouldShowObjectStoreSelector: ComputedRef<boolean>;
    objectStoreUploadBlockReason: ComputedRef<string | null>;
    handleObjectStoreSelected: (store: UserConcreteObjectStoreModel | null) => void;
}

export function useTargetObjectStoreSelectionState(
    targetHistoryId: Ref<string>,
    advancedMode: ComputedRef<boolean>,
): TargetObjectStoreSelectionState {
    const historyStore = useHistoryStore();
    const objectStoreStore = useObjectStoreStore();
    const { selectableObjectStores } = storeToRefs(objectStoreStore);

    const targetObjectStoreId = ref<string | null>(null);
    const userManuallySelectedStore = ref(false);

    const shouldShowObjectStoreSelector = computed(() => {
        return advancedMode.value && (selectableObjectStores.value?.length ?? 0) > 1;
    });

    const objectStoreUploadBlockReason = computed(() => {
        if (!targetObjectStoreId.value || !selectableObjectStores.value) {
            return null;
        }

        return selectableObjectStores.value.some((store) => store.object_store_id === targetObjectStoreId.value)
            ? null
            : "Selected storage location is no longer available.";
    });

    watch(
        [targetHistoryId, selectableObjectStores],
        ([newHistoryId, stores]) => {
            if (!newHistoryId || userManuallySelectedStore.value) {
                return;
            }

            const history = historyStore.getHistoryById(newHistoryId);
            const preferredObjectStoreId = history?.preferred_object_store_id ?? null;

            if (preferredObjectStoreId && stores?.some((store) => store.object_store_id === preferredObjectStoreId)) {
                targetObjectStoreId.value = preferredObjectStoreId;
                return;
            }

            targetObjectStoreId.value = stores?.[0]?.object_store_id ?? preferredObjectStoreId;
        },
        { immediate: true },
    );

    function handleObjectStoreSelected(store: UserConcreteObjectStoreModel | null) {
        userManuallySelectedStore.value = true;
        targetObjectStoreId.value = store?.object_store_id ?? null;
    }

    return {
        targetObjectStoreId,
        shouldShowObjectStoreSelector,
        objectStoreUploadBlockReason,
        handleObjectStoreSelected,
    };
}
