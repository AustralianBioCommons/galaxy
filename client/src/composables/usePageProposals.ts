import { computed, type Ref, ref } from "vue";

import type { ChatMessage } from "@/components/GalaxyAI/chatTypes";
import { applySectionEdit, djb2Hash } from "@/components/PageEditor/sectionDiffUtils";
import type { EditProposal } from "@/composables/agentActions";
import type { ActiveContext } from "@/composables/useActiveContext";
import { usePageEditorStore } from "@/stores/pageEditorStore";

/**
 * Encapsulates proposal rendering state and actions for the GalaxyAI panel
 * when operating in notebook (page_assistant) context.
 *
 * Owns the `dismissedProposals` set and all helpers needed to render
 * ProposalDiffView / SectionPatchView inside ChatMessageCell.
 */
export function usePageProposals(activeContext: Readonly<Ref<ActiveContext | null>>) {
    const pageEditorStore = usePageEditorStore();

    /** Live page content — empty when not in notebook context. */
    const pageContent = computed(() =>
        activeContext.value?.contextType === "notebook" ? pageEditorStore.currentContent : "",
    );

    /** Message IDs whose proposals have been dismissed or already applied. */
    const dismissedProposals = ref(new Set<string>());

    /** Load the persisted dismissed set for a page after fetching a conversation. */
    function loadForPage(pageId: string) {
        dismissedProposals.value = new Set(pageEditorStore.getDismissedProposals(pageId));
    }

    /** Clear the dismissed set (new chat or leaving notebook context). */
    function clear() {
        dismissedProposals.value = new Set();
    }

    function getEditProposal(msg: ChatMessage): EditProposal | null {
        const meta = msg.agentResponse?.metadata;
        const editMode = meta?.edit_mode as EditProposal["mode"] | undefined;
        if (!editMode) {
            return null;
        }
        return {
            mode: editMode,
            content: (meta?.content as string) || (meta?.new_section_content as string) || "",
            target_section_heading: meta?.target_section_heading as string | undefined,
            new_section_content: meta?.new_section_content as string | undefined,
        };
    }

    function isProposalStale(msg: ChatMessage): boolean {
        const originalHash = msg.agentResponse?.metadata?.original_content_hash as string | undefined;
        return !!originalHash && originalHash !== djb2Hash(pageContent.value);
    }

    function isProposalVisible(msg: ChatMessage): boolean {
        if (activeContext.value?.contextType !== "notebook") {
            return false;
        }
        if (dismissedProposals.value.has(msg.id)) {
            return false;
        }
        const proposal = getEditProposal(msg);
        if (!proposal) {
            return false;
        }
        if (proposal.mode === "full_replacement" && proposal.content === pageContent.value) {
            return false;
        }
        return true;
    }

    function buildProposedContent(msg: ChatMessage): string {
        const proposal = getEditProposal(msg);
        if (!proposal) {
            return pageContent.value;
        }
        if (proposal.mode === "full_replacement") {
            return proposal.content;
        }
        return applySectionEdit(
            pageContent.value,
            proposal.target_section_heading || "",
            proposal.new_section_content || proposal.content,
        );
    }

    async function applyFullReplacement(msg: ChatMessage) {
        const proposal = getEditProposal(msg);
        if (!proposal) {
            return;
        }
        pageEditorStore.updateContent(proposal.content);
        await pageEditorStore.savePage("agent");
        dismissedProposals.value.add(msg.id);
        if (activeContext.value?.contextType === "notebook") {
            pageEditorStore.addDismissedProposal(activeContext.value.pageId, msg.id);
        }
    }

    async function applySectionPatched(patchedContent: string, msg: ChatMessage) {
        pageEditorStore.updateContent(patchedContent);
        await pageEditorStore.savePage("agent");
        dismissedProposals.value.add(msg.id);
        if (activeContext.value?.contextType === "notebook") {
            pageEditorStore.addDismissedProposal(activeContext.value.pageId, msg.id);
        }
    }

    function dismissProposal(msg: ChatMessage) {
        dismissedProposals.value.add(msg.id);
        if (activeContext.value?.contextType === "notebook") {
            pageEditorStore.addDismissedProposal(activeContext.value.pageId, msg.id);
        }
    }

    return {
        pageContent,
        dismissedProposals,
        loadForPage,
        clear,
        getEditProposal,
        isProposalStale,
        isProposalVisible,
        buildProposedContent,
        applyFullReplacement,
        applySectionPatched,
        dismissProposal,
    };
}
