import { getLocalVue } from "@tests/vitest/helpers";
import { setupMockHistoryBreadcrumbs } from "@tests/vitest/mockHistoryBreadcrumbs";
import { shallowMount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it } from "vitest";

import type { HistoryPageSummary } from "@/api/pages";

import { FAKE_PAGE_SUMMARY, FAKE_PAGE_UNTITLED } from "./testData";

import HistoryPageList from "./HistoryPageList.vue";

const localVue = getLocalVue();

const SELECTORS = {
    NEW_BUTTON: "[data-description='create page button']",
    EMPTY_STATE: ".empty-state",
    PAGE_ITEMS: ".page-items",
    PAGE_ITEM: "[data-description='page item']",
};

setupMockHistoryBreadcrumbs();

async function mountComponent(propsData: { pages: HistoryPageSummary[] }) {
    const wrapper = shallowMount(HistoryPageList as object, {
        localVue,
        propsData: { ...propsData, historyId: "history-1" },
    });
    await flushPromises();
    return wrapper;
}

describe("HistoryPageList", () => {
    describe("Header", () => {
        let wrapper: Wrapper<Vue>;

        beforeEach(async () => {
            wrapper = await mountComponent({ pages: [] });
        });

        it("always shows 'New Notebook' button", () => {
            const button = wrapper.find(SELECTORS.NEW_BUTTON);
            expect(button.exists()).toBe(true);
            expect(button.text()).toContain("New Notebook");
        });
    });

    describe("Empty state", () => {
        let wrapper: Wrapper<Vue>;

        beforeEach(async () => {
            wrapper = await mountComponent({ pages: [] });
        });

        it("shows 'No notebooks yet' when pages prop is empty array", () => {
            const emptyState = wrapper.find(SELECTORS.EMPTY_STATE);
            expect(emptyState.exists()).toBe(true);
            expect(emptyState.text()).toContain("No notebooks yet");
        });

        it("shows create guidance text when no pages", () => {
            const emptyState = wrapper.find(SELECTORS.EMPTY_STATE);
            expect(emptyState.text()).toContain("Create a notebook to document your analysis");
        });

        it("does NOT show page items when empty", () => {
            expect(wrapper.find(SELECTORS.PAGE_ITEMS).exists()).toBe(false);
        });
    });

    describe("Page list", () => {
        let wrapper: Wrapper<Vue>;

        beforeEach(async () => {
            wrapper = await mountComponent({
                pages: [FAKE_PAGE_SUMMARY, FAKE_PAGE_UNTITLED],
            });
        });

        it("renders each page as a card", () => {
            const items = wrapper.findAll(SELECTORS.PAGE_ITEM);
            expect(items.length).toBe(2);
        });

        it("does NOT show empty state when pages exist", () => {
            expect(wrapper.find(SELECTORS.EMPTY_STATE).exists()).toBe(false);
        });
    });
});
