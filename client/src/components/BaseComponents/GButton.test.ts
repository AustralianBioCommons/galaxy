import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import GButton from "./GButton.vue";

const localVue = getLocalVue(true);

function mountGButton(props: object) {
    return mount(GButton as object, { propsData: props, localVue });
}

describe("GButton.vue", () => {
    it("uses the regular title when enabled", () => {
        const wrapper = mountGButton({ title: "Click me" });
        const button = wrapper.get("button");

        expect(button.attributes("title")).toBe("Click me");
        expect(button.attributes("data-title")).toBe("Click me");
    });

    it("uses the disabled title when disabled", () => {
        const wrapper = mountGButton({
            disabled: true,
            title: "Click me",
            disabledTitle: "Cannot click right now",
        });
        const button = wrapper.get("button");

        expect(button.attributes("title")).toBe("Cannot click right now");
        expect(button.attributes("data-title")).toBe("Cannot click right now");
    });

    it("falls back to the regular title when disabled without a disabled title", () => {
        const wrapper = mountGButton({ disabled: true, title: "Click me" });
        const button = wrapper.get("button");

        expect(button.attributes("title")).toBe("Click me");
    });

    // A disabled button must stay hoverable so the (disabled) title can surface its
    // tooltip. We mark it disabled via aria-disabled and a JS click guard rather than
    // the native `disabled` attribute (which would suppress hover events).
    it("remains hoverable when disabled", () => {
        const wrapper = mountGButton({ disabled: true, disabledTitle: "Nope" });
        const button = wrapper.get("button");

        expect(button.attributes("aria-disabled")).toBe("true");
        expect(button.attributes("disabled")).toBeUndefined();
    });

    it("does not emit click when disabled", async () => {
        const wrapper = mountGButton({ disabled: true, disabledTitle: "Nope" });

        await wrapper.get("button").trigger("click");

        expect(wrapper.emitted("click")).toBeUndefined();
    });

    it("emits click when enabled", async () => {
        const wrapper = mountGButton({ title: "Click me" });

        await wrapper.get("button").trigger("click");

        expect(wrapper.emitted("click")).toHaveLength(1);
    });
});
