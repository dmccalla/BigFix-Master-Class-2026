# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Measure painted glyphs, excluding empty font ascent/descent space."""

TEXT_OUTSIDE_CARD = """() => {
    const card = document.querySelector('#mount');
    if (!card) return ['missing chart card'];
    const box = card.getBoundingClientRect();
    const bad = [];
    const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
    const context = document.createElement('canvas').getContext('2d');
    while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.textContent.trim()) continue;
        const style = getComputedStyle(node.parentElement);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        const range = document.createRange(); range.selectNodeContents(node);
        const rects = [...range.getClientRects()];
        for (const rect of rects) {
            if (!rect.width || !rect.height) continue;
            let top = rect.top, bottom = rect.bottom;
            // For a single untransformed line, the browser's Range contains
            // the font ascent/descent, including unused space above digits.
            // Wrapped text retains the conservative per-line rectangle check.
            if (rects.length === 1 && style.transform === 'none') {
                context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
                const metrics = context.measureText(node.textContent);
                const fontHeight = metrics.fontBoundingBoxAscent + metrics.fontBoundingBoxDescent;
                if (Math.abs(fontHeight - rect.height) <= 2) {
                    const baseline = rect.top + metrics.fontBoundingBoxAscent;
                    top = baseline - metrics.actualBoundingBoxAscent;
                    bottom = baseline + metrics.actualBoundingBoxDescent;
                }
            }
            if (rect.left < box.left - 2 || rect.right > box.right + 2 || top < box.top - 2 || bottom > box.bottom + 2) bad.push(node.textContent.trim());
        }
    }
    return bad;
}"""
