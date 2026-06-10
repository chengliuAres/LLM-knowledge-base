/**
 * 术语 hover tooltip — 单例 DOM + 事件委托
 *
 * 用法: 不需要手动调用, 加载此脚本后, 任何带 [data-glossary] 属性的元素
 * 鼠标 hover 都会自动显示 tooltip
 *
 * 行为:
 * - mouseenter 0.15s 防抖后显示
 * - mouseleave 0.1s 延迟隐藏 (含移入 tooltip 自身)
 * - focus 时显示, Esc 关闭
 * - 视口边界检测: 超出右/下边界时翻向左/上
 */

(function () {
    const SHOW_DELAY = 150;
    const HIDE_DELAY = 100;
    const TOOLTIP_GAP = 8;        // 目标元素与 tooltip 的间距
    const TOOLTIP_MAX_WIDTH = 320;

    let tooltipEl = null;
    let currentTarget = null;
    let showTimer = null;
    let hideTimer = null;

    function ensureTooltip() {
        if (tooltipEl) return tooltipEl;
        tooltipEl = document.createElement("div");
        tooltipEl.className = "glossary-tooltip";
        tooltipEl.setAttribute("role", "tooltip");
        tooltipEl.style.position = "fixed";
        tooltipEl.style.maxWidth = TOOLTIP_MAX_WIDTH + "px";
        tooltipEl.style.pointerEvents = "auto";   // 允许 hover 到 tooltip 自身
        document.body.appendChild(tooltipEl);
        return tooltipEl;
    }

    function lookupGlossary(key) {
        return (window.GLOSSARY && window.GLOSSARY[key]) || null;
    }

    function show(target) {
        if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        const key = target.getAttribute("data-glossary");
        const text = lookupGlossary(key);
        if (!text) return;

        const tip = ensureTooltip();
        tip.textContent = text;
        tip.classList.remove("is-bottom");
        tip.classList.add("is-visible");
        currentTarget = target;

        // 定位: 默认在目标元素上方居中
        const rect = target.getBoundingClientRect();
        const tipRect = tip.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        // 水平: 居中, 防止溢出
        let left = rect.left + rect.width / 2 - tipRect.width / 2;
        left = Math.max(8, Math.min(left, vw - tipRect.width - 8));

        // 垂直: 优先上方, 超出上边界则翻下
        let top = rect.top - tipRect.height - TOOLTIP_GAP;
        let isBottom = false;
        if (top < 8) {
            top = rect.bottom + TOOLTIP_GAP;
            isBottom = true;
        }

        tip.style.left = left + "px";
        tip.style.top = top + "px";
        if (isBottom) tip.classList.add("is-bottom");
    }

    function hide() {
        if (!tooltipEl) return;
        tooltipEl.classList.remove("is-visible");
        currentTarget = null;
    }

    function scheduleShow(target) {
        if (showTimer) { clearTimeout(showTimer); showTimer = null; }
        if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        showTimer = setTimeout(() => {
            showTimer = null;
            show(target);
        }, SHOW_DELAY);
    }

    function scheduleHide() {
        if (showTimer) { clearTimeout(showTimer); showTimer = null; }
        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = setTimeout(() => {
            hideTimer = null;
            hide();
        }, HIDE_DELAY);
    }

    // 事件委托在 document
    document.addEventListener("mouseover", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        scheduleShow(t);
    });

    document.addEventListener("mouseout", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        // 如果鼠标移到了 tooltip 自身, 不隐藏
        // 注意: 鼠标移出视口时 relatedTarget === null, 此时应正常隐藏
        const related = e.relatedTarget;
        if (related && tooltipEl?.contains(related)) return;
        scheduleHide();
    });

    // tooltip 自身的 hover: 取消隐藏
    document.addEventListener("mouseover", (e) => {
        if (e.target === tooltipEl || tooltipEl?.contains(e.target)) {
            if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        }
    });
    document.addEventListener("mouseout", (e) => {
        if (e.target === tooltipEl || tooltipEl?.contains(e.target)) {
            scheduleHide();
        }
    });

    // 键盘可达: focus 显示, blur 隐藏
    document.addEventListener("focusin", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        if (showTimer) { clearTimeout(showTimer); showTimer = null; }
        show(t);
    });
    document.addEventListener("focusout", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        scheduleHide();
    });

    // Esc 关闭
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && tooltipEl?.classList.contains("is-visible")) {
            if (showTimer) { clearTimeout(showTimer); showTimer = null; }
            if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
            hide();
            if (currentTarget && currentTarget.focus) currentTarget.blur();
        }
    });
})();
