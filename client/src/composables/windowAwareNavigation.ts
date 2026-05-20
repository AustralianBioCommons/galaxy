/**
 * Composable for "open in window-manager frame when active, else navigate inline".
 *
 * The window-manager-aware navigation pattern recurs across components
 * (HistoryCounter, HistoryPageView, PageEditorView, ContentItem, etc.):
 *
 * 1. Check ``Galaxy?.frame?.active``.
 * 2. When active: push a *framed* URL (typically with ``?displayOnly=true``
 *    or ``?embed=true``) plus a ``title`` option, so the monkeypatched
 *    ``router.push`` (``client/src/entry/analysis/router-push.js``)
 *    intercepts and opens it as a floating frame.
 * 3. When inactive: push the *inline* URL plainly.
 */
import { useRouter } from "vue-router/composables";

import { getGalaxyInstance } from "@/app";
import type { RouterPushOptions } from "@/components/History/Content/router-push-options";

interface FrameOrPageOptions {
    /** URL to push when the window manager is active. Typically carries ``?displayOnly=true``/``?embed=true``. */
    framedUrl: string;
    /** URL to push otherwise. Defaults to ``framedUrl``. */
    inlineUrl?: string;
    /** Title shown on the floating frame's tab. Required for the monkeypatch to open a frame. */
    title: string;
}

export function useWindowAwareNavigation() {
    const router = useRouter();

    function pushToFrameOrPage({ framedUrl, inlineUrl, title }: FrameOrPageOptions): void {
        const Galaxy = getGalaxyInstance();
        if (Galaxy?.frame?.active) {
            const options: RouterPushOptions = { title, preventWindowManager: false };
            // @ts-ignore - monkeypatched router accepts {title}; drop with migration.
            router.push(framedUrl, options);
        } else {
            router.push(inlineUrl ?? framedUrl);
        }
    }

    return { pushToFrameOrPage };
}
