# app.py — OGQ 스티커 닥터
# 기존 VER2 기능 유지 + OGQ 시장 비교 + 심사 기준 커스텀 + AI 문제 위치 표시
# 시장 비교 AI가 실패해도 앱 전체가 중단되지 않도록 별도 오류 처리와 모델 fallback을 사용한다.

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from datetime import date

import streamlit as st
import streamlit.components.v1 as components
try:
    import streamlit.components.v2 as components_v2
except Exception:
    components_v2 = None
from streamlit_cookies_controller import CookieController, RemoveEmptyElementContainer
from PIL import Image, ImageDraw

from checker import SPECS, check_image, classify_type
from diagnosis import diagnose_detailed, render_diagnosis_markdown
from criteria import DEFAULT_CRITERIA, PLATFORM_PRESETS, build_selected_criteria
from market_analysis import (
    MARKET_SCHEMA,
    build_market_analysis_prompt,
    build_market_context_for_diagnosis,
    download_market_reference_images,
    normalize_market_analysis,
    generate_public_web_check,
)
from ogq_market import OGQAPIError, search_by_keywords
from user_store import (
    create_user,
    load_user_diagnosis_history,
    save_diagnosis_record,
    verify_user,
    save_review,
    load_reviews_for_record,
    load_public_reviews,
    load_all_reviews,
    create_login_session,
    get_username_by_session,
    delete_login_session,
)
from report_utils import (
    build_pdf_report,
    build_priority_todo,
    compute_score,
)


st.set_page_config(
    page_title="OGQ 스티커 닥터",
    page_icon="🩺",
    layout="wide",
)

# 새로고침 시에도 같은 브라우저 세션에서는 로그인 상태를 복원합니다.
if "_sd_cookie_controller" not in st.session_state:
    st.session_state["_sd_cookie_controller"] = CookieController(key="sd_cookie_controller")
_cookie_controller = st.session_state["_sd_cookie_controller"]
RemoveEmptyElementContainer()


# 최신 Streamlit의 페이지 DOM에 직접 연결되는 UI 보조 컴포넌트입니다.
# 브라우저 자동재생 정책 때문에 iframe 내부에서만 재생하던 기존 방식 대신,
# 실제 3·4단계 실행 버튼의 클릭 이벤트에서 AudioContext를 먼저 활성화합니다.
_completion_sound_component = None
if components_v2 is not None:
    _UI_HELPER_JS = r"""
export default function(component) {
    const { data } = component;
    const state = window.__ogqStickerDoctorUI || (window.__ogqStickerDoctorUI = {
        audioContext: null,
        clickHandler: null,
        sidebarObserver: null,
        bodyObserver: null,
        sidebarButton: null,
        lastPlayNonce: null,
        menuButton: null,
        menuClickHandler: null,
        lastActivatedTab: null,
    });

    function createAudioContext() {
        try {
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return null;
            if (!state.audioContext || state.audioContext.state === 'closed') {
                state.audioContext = new AC();
            }
            if (state.audioContext.state === 'suspended') {
                state.audioContext.resume().catch(() => {});
            }
            return state.audioContext;
        } catch (_) {
            return null;
        }
    }

    function playDing() {
        const ctx = createAudioContext();
        if (!ctx) return;
        try {
            const now = ctx.currentTime + 0.01;
            const gain = ctx.createGain();
            gain.gain.setValueAtTime(0.0001, now);
            gain.gain.exponentialRampToValueAtTime(0.40, now + 0.015);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.45);
            gain.connect(ctx.destination);

            const osc1 = ctx.createOscillator();
            osc1.type = 'sine';
            osc1.frequency.setValueAtTime(880, now);
            osc1.frequency.exponentialRampToValueAtTime(1320, now + 0.10);
            osc1.connect(gain);

            const osc2 = ctx.createOscillator();
            osc2.type = 'sine';
            osc2.frequency.setValueAtTime(1320, now + 0.12);
            osc2.frequency.exponentialRampToValueAtTime(1760, now + 0.24);
            osc2.connect(gain);

            osc1.start(now);
            osc1.stop(now + 0.11);
            osc2.start(now + 0.12);
            osc2.stop(now + 0.30);
        } catch (_) {}
    }

    function onAppClick(event) {
        const button = event.target.closest && event.target.closest('button');
        if (!button) return;
        const label = (button.innerText || button.getAttribute('aria-label') || '')
            .replace(/\s+/g, ' ')
            .trim();
        if (
            label.includes('OGQ 시장과 비교하기') ||
            label.includes('전체 AI 진단 받기')
        ) {
            // 사용자 클릭 제스처 안에서 오디오 컨텍스트를 활성화합니다.
            createAudioContext();
        }
    }

    if (!state.clickHandler) {
        state.clickHandler = onAppClick;
        document.addEventListener('click', state.clickHandler, true);
    }

    function findWorkspaceTab(label) {
        const tabs = Array.from(document.querySelectorAll('button[role="tab"], [data-baseweb="tab"]'));
        return tabs.find((tab) => (tab.innerText || '').replace(/\s+/g, ' ').trim() === label) || null;
    }

    function getSidebarToggle() {
        return document.querySelector(
            '[data-testid="stSidebarCollapseButton"] button, ' +
            '[data-testid="collapsedControl"] button'
        );
    }

    function toggleSidebar() {
        const toggle = getSidebarToggle();
        if (toggle) toggle.click();
    }

    function ensureMenuUI() {
        let button = document.getElementById('ogq-main-menu');
        if (!button) {
            button = document.createElement('button');
            button.id = 'ogq-main-menu';
            button.type = 'button';
            button.setAttribute('aria-label', '메뉴 열기');
            button.setAttribute('aria-expanded', 'false');
            button.innerHTML = '☰ <span>메뉴</span>';
            button.style.cssText = [
                'position:fixed', 'left:14px', 'top:116px', 'z-index:1000001',
                'display:none', 'align-items:center', 'gap:7px', 'height:42px', 'padding:0 16px',
                'border:1px solid #D9DCEA', 'border-radius:13px', 'background:#ffffff',
                'color:#171A2B', 'font:800 14px/1 sans-serif', 'box-shadow:0 10px 28px rgba(25,31,57,.15)',
                'cursor:pointer',
            ].join(';');
            button.addEventListener('click', () => {
                toggleSidebar();
                button.setAttribute('aria-expanded', 'true');
            });
            document.body.appendChild(button);
        }
        state.menuButton = button;
        return button;
    }

    function updateMenuVisibility(authenticated) {
        const button = ensureMenuUI();
        const sidebar = document.querySelector('[data-testid="stSidebar"]');
        const expanded = sidebar && sidebar.getAttribute('aria-expanded') === 'true';
        const visible = authenticated === true && !expanded;
        button.style.display = visible ? 'flex' : 'none';
        button.setAttribute('aria-expanded', expanded ? 'false' : 'false');

        // 로그인 후에는 메인 탭 UI를 숨기고, 실제 사이드바의 메뉴 버튼으로 이동합니다.
        document.querySelectorAll('div[role="tablist"]').forEach((tablist) => {
            const labels = Array.from(tablist.querySelectorAll('[role="tab"], [data-baseweb="tab"]'))
                .map((tab) => (tab.innerText || '').replace(/\s+/g, ' ').trim());
            if (labels.includes('🩺 검사하기') && labels.includes('📚 히스토리') && labels.includes('💬 리뷰')) {
                tablist.style.display = authenticated === true ? 'none' : '';
            }
        });
    }

    function activateTargetTab(target) {
        if (!target || state.lastActivatedTab === target) return;
        const labelMap = { check: '🩺 검사하기', history: '📚 히스토리', reviews: '💬 리뷰' };
        const tab = findWorkspaceTab(labelMap[target]);
        if (!tab) return;
        state.lastActivatedTab = target;
        tab.click();
    }

    const sidebar = document.querySelector('[data-testid="stSidebar"]');
    if (sidebar) {
        if (state.sidebarObserver) state.sidebarObserver.disconnect();
        state.sidebarObserver = new MutationObserver(() => updateMenuVisibility(Boolean(data && data.authenticated)));
        state.sidebarObserver.observe(sidebar, { attributes: true, attributeFilter: ['aria-expanded'] });
    }

    if (state.bodyObserver) state.bodyObserver.disconnect();
    state.bodyObserver = new MutationObserver(() => {
        updateMenuVisibility(Boolean(data && data.authenticated));
        activateTargetTab(data && data.target_tab);
    });
    state.bodyObserver.observe(document.body, { childList: true, subtree: true });

    updateMenuVisibility(Boolean(data && data.authenticated));
    activateTargetTab(data && data.target_tab);

    if (data && data.play && data.nonce !== state.lastPlayNonce) {
        state.lastPlayNonce = data.nonce;
        setTimeout(playDing, 30);
    }

    return () => {};
}
"""
    _completion_sound_component = components_v2.component(
        "ogq_sticker_doctor_ui_helper",
        html='<div aria-hidden="true"></div>',
        css=':host { display: none !important; width: 0 !important; height: 0 !important; }',
        js=_UI_HELPER_JS,
        isolate_styles=False,
    )

# 페이지 DOM 보조 컴포넌트를 한 번 등록합니다.
if _completion_sound_component is not None:
    _completion_sound_component(data={"play": False, "nonce": 0, "authenticated": False})


st.markdown(
    """
    <style>
    /* =========================================================
       STICKER DOCTOR — DESIGN ONLY
       기능/상태/API/위젯 구조와 무관한 시각 레이어만 정의합니다.
       ========================================================= */
    @import url('https://fonts.googleapis.com/icon?family=Material+Symbols+Rounded');
    @import url('https://fonts.googleapis.com/css2?family=Jua&family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');

    :root {
        --sd-primary: #5B63F6;
        --sd-primary-2: #7C68EE;
        --sd-accent: #B7A8FF;
        --sd-mint: #63D7B1;
        --sd-sky: #69B8FF;
        --sd-pink: #FF89B4;

        --sd-bg: #F6F7FB;
        --sd-card: #FFFFFF;
        --sd-card-soft: #FBFBFE;
        --sd-ink: #171A2B;
        --sd-muted: #73798E;
        --sd-line: #E7E9F1;
        --sd-line-strong: #D9DCEA;

        --sd-success: #3DB98A;
        --sd-warning: #E9B64D;
        --sd-danger: #EF6C84;

        --sd-radius: 22px;
        --sd-radius-sm: 14px;
        --sd-radius-lg: 30px;
        --sd-shadow-sm: 0 5px 18px rgba(25, 31, 57, .05);
        --sd-shadow-md: 0 14px 38px rgba(25, 31, 57, .09);
        --sd-shadow-lg: 0 24px 60px rgba(25, 31, 57, .12);
    }

    * { box-sizing: border-box; }

    html, body, [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 8% 4%, rgba(91,99,246,.08), transparent 25%),
            radial-gradient(circle at 92% 10%, rgba(99,215,177,.08), transparent 22%),
            var(--sd-bg) !important;
        color: var(--sd-ink) !important;
    }

    body,
    [data-testid="stAppViewContainer"] * {
        font-family: 'Noto Sans KR', system-ui, sans-serif;
    }

    /* Streamlit Material Symbols: isolate native icons from the app font. */
    [data-testid="stIconMaterial"],
    [data-testid="stIconMaterial"] *,
    .material-symbols-rounded,
    .material-symbols-outlined,
    .material-symbols-sharp,
    .material-icons,
    .material-icons-outlined,
    .material-icons-round,
    .material-icons-sharp {
        font-family: 'Material Symbols Rounded' !important;
        font-style: normal !important;
        font-weight: 500 !important;
        font-size: 1.25rem !important;
        line-height: 1 !important;
        letter-spacing: normal !important;
        text-transform: none !important;
        white-space: nowrap !important;
        word-wrap: normal !important;
        direction: ltr !important;
        -webkit-font-feature-settings: 'liga' !important;
        font-feature-settings: 'liga' !important;
        font-variation-settings: 'FILL' 0, 'wght' 500, 'GRAD' 0, 'opsz' 24 !important;
        -webkit-font-smoothing: antialiased !important;
    }

    [data-testid="stAppViewContainer"] > .main {
        padding-top: 1.2rem;
        padding-bottom: 4.5rem;
    }

    .block-container {
        max-width: 1320px !important;
        padding-left: clamp(1rem, 3vw, 2.6rem) !important;
        padding-right: clamp(1rem, 3vw, 2.6rem) !important;
    }

    [data-testid="stHeader"] {
        background: transparent !important;
        box-shadow: none !important;
    }

    [data-testid="stToolbar"] { display: none !important; }
    footer { visibility: hidden; height: 0; }

    h1, h2, h3, h4,
    [data-testid="stMetricValue"] {
        font-family: 'Jua', 'Noto Sans KR', sans-serif !important;
        color: var(--sd-ink) !important;
        letter-spacing: -.025em;
    }

    h1 { font-size: clamp(2.1rem, 4.4vw, 4rem) !important; line-height: 1.06 !important; }
    h2 { font-size: clamp(1.35rem, 2vw, 1.8rem) !important; line-height: 1.2 !important; }
    h3 { font-size: 1.18rem !important; }

    p, label, [data-testid="stCaptionContainer"] {
        color: var(--sd-muted) !important;
    }

    /* =========================================================
       HERO
       ========================================================= */
    .hero-banner {
        position: relative;
        overflow: hidden;
        min-height: 330px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        padding: 48px clamp(26px, 5vw, 64px);
        margin: 0 0 22px;
        border: 1px solid rgba(91,99,246,.13);
        border-radius: var(--sd-radius-lg);
        background:
            radial-gradient(circle at 86% 18%, rgba(183,168,255,.42), transparent 18%),
            radial-gradient(circle at 93% 76%, rgba(99,215,177,.25), transparent 20%),
            linear-gradient(135deg, #FFFFFF 0%, #F8F9FF 52%, #F7FAFF 100%);
        box-shadow: var(--sd-shadow-lg);
        isolation: isolate;
        animation: sd-hero-in .55s cubic-bezier(.2,.8,.2,1) both;
    }

    .hero-banner::before {
        content: "";
        position: absolute;
        width: 230px;
        height: 230px;
        right: 8%;
        top: 50%;
        border-radius: 50%;
        transform: translateY(-50%);
        background: linear-gradient(145deg, rgba(91,99,246,.15), rgba(124,104,238,.05));
        filter: blur(1px);
        z-index: -1;
        animation: sd-float 5.5s ease-in-out infinite;
    }

    .hero-banner::after {
        content: "";
        position: absolute;
        width: 76px;
        height: 76px;
        right: 16%;
        top: 21%;
        border-radius: 20px;
        background: rgba(255,255,255,.72);
        border: 1px solid rgba(91,99,246,.12);
        box-shadow: var(--sd-shadow-md);
        transform: rotate(11deg);
        z-index: -1;
        animation: sd-float 4.4s ease-in-out infinite reverse;
    }

    .hero-banner h1,
    .hero-banner h2,
    .hero-banner p {
        color: var(--sd-ink) !important;
        position: relative;
        z-index: 1;
    }

    .hero-banner h1 {
        max-width: 760px;
        margin: 0 0 14px !important;
    }

    .hero-banner p {
        max-width: 650px;
        margin: 0 !important;
        font-size: 1rem;
        line-height: 1.8;
    }

    .sd-kicker {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        width: fit-content;
        margin-bottom: 14px;
        padding: 7px 11px;
        border: 1px solid rgba(91,99,246,.16);
        border-radius: 999px;
        background: rgba(255,255,255,.82);
        color: var(--sd-primary);
        font-size: .74rem;
        font-weight: 800;
        letter-spacing: .08em;
        box-shadow: 0 4px 14px rgba(25,31,57,.04);
        backdrop-filter: blur(10px);
    }

    .sd-note {
        padding: 10px 14px;
        border: 1px solid var(--sd-line);
        border-radius: 999px;
        background: rgba(255,255,255,.86);
        color: var(--sd-ink) !important;
        box-shadow: var(--sd-shadow-sm);
        backdrop-filter: blur(10px);
    }

    /* =========================================================
       TABS / NAV
       ========================================================= */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 5px;
        padding: 5px;
        margin-bottom: 24px;
        border: 1px solid var(--sd-line);
        border-radius: 16px;
        background: rgba(255,255,255,.72);
        box-shadow: var(--sd-shadow-sm);
        backdrop-filter: blur(10px);
    }

    [data-testid="stTabs"] [data-baseweb="tab"] {
        height: 44px;
        padding: 0 18px;
        border: 0 !important;
        border-radius: 11px;
        background: transparent !important;
        color: var(--sd-muted) !important;
        font-weight: 800;
        font-size: .88rem;
        transition: transform .18s ease, background-color .18s ease, color .18s ease, box-shadow .18s ease;
    }

    [data-testid="stTabs"] [data-baseweb="tab"]:hover {
        color: var(--sd-ink) !important;
        transform: translateY(-1px);
    }

    [data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
        background: var(--sd-ink) !important;
        color: #FFFFFF !important;
        box-shadow: 0 7px 16px rgba(23,26,43,.12);
    }

    [data-testid="stTabs"] [data-baseweb="tab-highlight"],
    [data-testid="stTabs"] [data-baseweb="tab-border"] {
        display: none !important;
    }

    /* =========================================================
       FLOW / BENTO
       ========================================================= */
    .sd-flow {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin: 0 0 26px;
        animation: sd-fade-up .5s .06s cubic-bezier(.2,.8,.2,1) both;
    }

    .sd-flow-item {
        position: relative;
        padding: 14px 15px;
        border: 1px solid var(--sd-line);
        border-radius: 16px;
        background: rgba(255,255,255,.92);
        box-shadow: var(--sd-shadow-sm);
        color: var(--sd-ink);
        font-size: .82rem;
        font-weight: 800;
        transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
        overflow: hidden;
    }

    .sd-flow-item::after {
        content: "";
        position: absolute;
        width: 72px;
        height: 72px;
        right: -30px;
        bottom: -34px;
        border-radius: 50%;
        background: rgba(91,99,246,.07);
        pointer-events: none;
    }

    .sd-flow-item:hover {
        transform: translateY(-3px);
        border-color: rgba(91,99,246,.18);
        box-shadow: var(--sd-shadow-md);
    }

    .sd-flow-arrow { display: none; }

    /* =========================================================
       BUTTONS
       ========================================================= */
    [data-testid="stButton"] button,
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stDownloadButton"] button {
        min-height: 44px;
        padding: 0 18px !important;
        border: 1px solid var(--sd-line-strong) !important;
        border-radius: 12px !important;
        background: #FFFFFF !important;
        color: var(--sd-ink) !important;
        box-shadow: var(--sd-shadow-sm) !important;
        font-weight: 800 !important;
        transition: transform .18s cubic-bezier(.2,.8,.2,1), box-shadow .18s ease, border-color .18s ease, background-color .18s ease !important;
        will-change: transform;
    }

    [data-testid="stButton"] button:hover,
    [data-testid="stFormSubmitButton"] button:hover,
    [data-testid="stDownloadButton"] button:hover {
        transform: translateY(-3px) scale(1.018);
        box-shadow: var(--sd-shadow-md) !important;
        border-color: rgba(91,99,246,.25) !important;
        background: #FCFCFF !important;
    }

    [data-testid="stButton"] button:active,
    [data-testid="stFormSubmitButton"] button:active,
    [data-testid="stDownloadButton"] button:active {
        transform: translateY(-1px) scale(.987) !important;
        box-shadow: var(--sd-shadow-sm) !important;
    }

    [data-testid="stButton"] button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"] {
        background: var(--sd-primary) !important;
        border-color: var(--sd-primary) !important;
        color: #FFFFFF !important;
        box-shadow: 0 10px 22px rgba(91,99,246,.22) !important;
    }

    [data-testid="stButton"] button[kind="primary"]:hover,
    [data-testid="stFormSubmitButton"] button[kind="primary"]:hover {
        background: var(--sd-primary-2) !important;
        border-color: var(--sd-primary-2) !important;
        box-shadow: 0 15px 28px rgba(91,99,246,.28) !important;
    }

    /* 주요 실행 버튼의 텍스트/아이콘 대비를 확실하게 고정 */
    [data-testid="stButton"] button[kind="primary"] *,
    [data-testid="stFormSubmitButton"] button[kind="primary"] * {
        color: #FFFFFF !important;
        text-shadow: 0 1px 2px rgba(20, 24, 48, .12);
    }

    /* 사이드바를 닫았을 때도 Streamlit 기본 펼치기 토글이 항상 보이도록 보정 */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"] {
        visibility: visible !important;
        opacity: 1 !important;
        z-index: 999999 !important;
    }

    [data-testid="collapsedControl"] button,
    [data-testid="stSidebarCollapseButton"] button {
        color: #171A2B !important;
        background: rgba(255,255,255,.97) !important;
        border: 1px solid #D9DCEA !important;
        border-radius: 12px !important;
        box-shadow: 0 8px 24px rgba(25,31,57,.12) !important;
    }

    [data-testid="collapsedControl"] button:hover,
    [data-testid="stSidebarCollapseButton"] button:hover {
        background: #FFFFFF !important;
        border-color: rgba(91,99,246,.30) !important;
    }

    /* =========================================================
       INPUTS
       ========================================================= */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input,
    [data-testid="stSelectbox"] > div > div,
    [data-testid="stMultiSelect"] > div > div {
        border: 1px solid var(--sd-line-strong) !important;
        border-radius: 12px !important;
        background: #FFFFFF !important;
        color: var(--sd-ink) !important;
        box-shadow: 0 2px 8px rgba(25,31,57,.025);
        transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
    }

    [data-testid="stTextInput"] input:hover,
    [data-testid="stTextArea"] textarea:hover,
    [data-testid="stNumberInput"] input:hover,
    [data-testid="stSelectbox"] > div > div:hover,
    [data-testid="stMultiSelect"] > div > div:hover {
        border-color: #CCD0E0 !important;
    }

    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus,
    [data-testid="stNumberInput"] input:focus {
        border-color: rgba(91,99,246,.55) !important;
        box-shadow: 0 0 0 4px rgba(91,99,246,.08) !important;
    }

    [data-testid="stTextArea"] textarea {
        min-height: 110px;
        padding: 13px 15px !important;
        border-radius: 14px !important;
    }

    /* =========================================================
       CARDS / CONTAINERS / EXPANDERS
       ========================================================= */
    [data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid var(--sd-line) !important;
        border-radius: var(--sd-radius) !important;
        background: rgba(255,255,255,.94) !important;
        box-shadow: var(--sd-shadow-sm) !important;
        transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
    }

    [data-testid="stVerticalBlockBorderWrapper"]:hover {
        transform: translateY(-2px);
        border-color: rgba(91,99,246,.14) !important;
        box-shadow: var(--sd-shadow-md) !important;
    }

    [data-testid="stExpander"] {
        border: 1px solid var(--sd-line) !important;
        border-radius: 16px !important;
        background: rgba(255,255,255,.94) !important;
        box-shadow: var(--sd-shadow-sm) !important;
        overflow: hidden;
        margin: 10px 0;
        transition: border-color .2s ease, box-shadow .2s ease;
    }

    [data-testid="stExpander"]:hover {
        border-color: rgba(91,99,246,.16) !important;
        box-shadow: var(--sd-shadow-md) !important;
    }

    [data-testid="stExpander"] summary {
        color: var(--sd-ink) !important;
        font-family: 'Noto Sans KR', sans-serif !important;
        font-weight: 800;
    }

    .sd-stage-heading {
        display: flex;
        align-items: center;
        gap: 12px;
        width: fit-content;
        max-width: 100%;
        margin: 20px 0 6px;
        padding: 10px 16px 10px 10px;
        border: 1px solid #E2E5F0;
        border-radius: 16px;
        background: rgba(255,255,255,.98);
        color: #171A2B !important;
        box-shadow: 0 7px 20px rgba(25,31,57,.06);
        font-family: 'Jua', 'Noto Sans KR', sans-serif;
        font-size: clamp(1.12rem, 1.9vw, 1.48rem);
        font-weight: 800;
        line-height: 1.2;
    }

    .sd-stage-heading .step {
        display: inline-flex;
        align-items: center;
        min-height: 32px;
        padding: 0 11px;
        border-radius: 10px;
        background: linear-gradient(135deg, var(--sd-primary), var(--sd-primary-2));
        color: #FFFFFF !important;
        font-family: 'Noto Sans KR', sans-serif;
        font-size: .78rem;
        font-weight: 800;
        white-space: nowrap;
        box-shadow: 0 6px 14px rgba(91,99,246,.22);
    }

    .sd-stage-heading > span:last-child {
        color: #171A2B !important;
        text-shadow: none;
    }

    /* =========================================================
       SCORE / BENTO SUMMARY
       ========================================================= */
    .score-wrap {
        display: grid;
        grid-template-columns: 230px minmax(0, 1fr);
        gap: 30px;
        align-items: center;
        margin: 12px 0 16px;
        padding: 28px;
        border: 1px solid rgba(91,99,246,.12);
        border-radius: 28px;
        background:
            linear-gradient(135deg, rgba(255,255,255,.97), rgba(248,249,255,.95));
        box-shadow: var(--sd-shadow-md);
        animation: sd-fade-up .5s .12s cubic-bezier(.2,.8,.2,1) both;
    }

    .score-ring {
        --score: 0;
        width: 204px;
        height: 204px;
        border-radius: 50%;
        background:
            radial-gradient(circle at center, #FFFFFF 0 59%, transparent 60%),
            conic-gradient(
                var(--sd-primary) calc(var(--score) * 1%),
                #E8EAF5 0
            );
        border: 1px solid rgba(91,99,246,.14);
        box-shadow: var(--sd-shadow-md);
        display: grid;
        place-items: center;
        position: relative;
        margin: auto;
        transform: rotate(-8deg);
        transition: transform .3s cubic-bezier(.2,.8,.2,1), box-shadow .25s ease;
        animation: sd-score-in .8s .12s cubic-bezier(.2,.8,.2,1) both;
    }

    .score-ring:hover {
        transform: rotate(-2deg) scale(1.035);
        box-shadow: var(--sd-shadow-lg);
    }

    .score-ring::after {
        content: "";
        position: absolute;
        inset: 20px;
        border-radius: 50%;
        background: rgba(255,255,255,.96);
        border: 1px solid rgba(91,99,246,.08);
        box-shadow: inset 0 0 22px rgba(91,99,246,.045);
    }

    .score-center {
        position: relative;
        z-index: 2;
        text-align: center;
        transform: rotate(8deg);
    }

    .score-center .num {
        font-family: 'Jua', 'Noto Sans KR', sans-serif;
        font-size: 2.7rem;
        line-height: 1;
        color: var(--sd-primary);
    }

    .score-center .unit {
        margin-top: 5px;
        color: var(--sd-muted);
        font-size: .76rem;
        font-weight: 800;
    }

    .score-info h3 { margin: 0 0 7px !important; }
    .score-info p { margin: 0 0 16px !important; color: var(--sd-muted); }

    .score-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }

    .score-badge {
        display: inline-flex;
        align-items: center;
        min-height: 32px;
        border: 1px solid var(--sd-line-strong);
        border-radius: 999px;
        padding: 5px 10px;
        background: #FFFFFF;
        color: var(--sd-ink);
        font-size: .75rem;
        font-weight: 800;
        box-shadow: 0 2px 8px rgba(25,31,57,.03);
    }

    .score-badge.good { background: rgba(99,215,177,.18); border-color: rgba(61,185,138,.23); }
    .score-badge.warn { background: rgba(255,217,125,.27); border-color: rgba(233,182,77,.26); }
    .score-badge.bad { background: rgba(255,137,180,.18); border-color: rgba(239,108,132,.23); }

    .sd-mini-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0,1fr));
        gap: 12px;
        margin: 0 0 24px;
    }

    .sd-mini {
        position: relative;
        overflow: hidden;
        min-height: 94px;
        padding: 15px 16px;
        border: 1px solid var(--sd-line);
        border-radius: 17px;
        background: #FFFFFF;
        box-shadow: var(--sd-shadow-sm);
        transition: transform .2s ease, box-shadow .2s ease;
    }

    .sd-mini::after {
        content: "";
        position: absolute;
        width: 56px;
        height: 56px;
        right: -18px;
        bottom: -18px;
        border-radius: 50%;
        background: rgba(91,99,246,.065);
    }

    .sd-mini:hover {
        transform: translateY(-3px);
        box-shadow: var(--sd-shadow-md);
    }

    .sd-mini b {
        display: block;
        margin-bottom: 3px;
        font-family: 'Jua', 'Noto Sans KR', sans-serif;
        font-size: 1.3rem;
        color: var(--sd-ink);
    }

    .sd-mini span {
        color: var(--sd-muted);
        font-size: .74rem;
        font-weight: 700;
    }

    /* =========================================================
       METRICS / FILE UPLOAD / PROGRESS / IMAGE
       ========================================================= */
    [data-testid="stMetric"] {
        background: rgba(255,255,255,.94);
        border: 1px solid var(--sd-line);
        border-radius: 17px;
        box-shadow: var(--sd-shadow-sm);
        padding: 15px 16px;
        transition: transform .2s ease, box-shadow .2s ease;
    }

    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: var(--sd-shadow-md);
    }

    [data-testid="stMetricLabel"] {
        color: var(--sd-muted) !important;
        font-weight: 700;
    }

    [data-testid="stFileUploaderDropzone"] {
        min-height: 170px;
        display: grid;
        place-items: center;
        border: 1px dashed #CCD1E2 !important;
        border-radius: 20px !important;
        background:
            linear-gradient(180deg, #FFFFFF, #FBFBFF) !important;
        box-shadow: var(--sd-shadow-sm);
        transition: transform .2s ease, border-color .2s ease, background-color .2s ease, box-shadow .2s ease;
    }

    [data-testid="stFileUploaderDropzone"]:hover {
        transform: translateY(-2px);
        border-color: rgba(91,99,246,.4) !important;
        background: #FCFCFF !important;
        box-shadow: var(--sd-shadow-md);
    }

    [data-testid="stProgressBar"] > div > div > div {
        background: linear-gradient(90deg, var(--sd-primary), var(--sd-primary-2)) !important;
        border-radius: 999px !important;
    }

    [data-testid="stProgressBar"] > div {
        border: 1px solid var(--sd-line) !important;
        border-radius: 999px;
        background: #FFFFFF;
    }

    [data-testid="stImage"] img {
        border: 1px solid var(--sd-line) !important;
        border-radius: 18px;
        background: #FFFFFF;
        box-shadow: var(--sd-shadow-sm);
        transition: transform .2s ease, box-shadow .2s ease;
    }

    [data-testid="stImage"] img:hover {
        transform: translateY(-2px);
        box-shadow: var(--sd-shadow-md);
    }

    /* =========================================================
       ALERTS / CHECKS / DIVIDERS
       ========================================================= */
    [data-testid="stAlert"] {
        border-radius: 15px !important;
        border-width: 1px !important;
        box-shadow: var(--sd-shadow-sm);
    }

    [data-testid="stCheckbox"] label,
    [data-testid="stRadio"] label {
        color: var(--sd-ink) !important;
    }

    hr {
        border: 0 !important;
        border-top: 1px solid var(--sd-line) !important;
        margin: 30px 0 !important;
    }

    [data-testid="stSlider"] [role="slider"] {
        background: var(--sd-primary) !important;
        border: 2px solid #FFFFFF !important;
        box-shadow: 0 0 0 1px rgba(91,99,246,.18), 0 4px 12px rgba(91,99,246,.18);
    }

    /* =========================================================
       TODO / RESULT ROWS
       ========================================================= */
    .todo-row {
        padding: 15px 17px;
        margin: 9px 0;
        border: 1px solid var(--sd-line);
        border-radius: 15px;
        background: #FFFFFF;
        box-shadow: var(--sd-shadow-sm);
        transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
        animation: sd-fade-up .45s cubic-bezier(.2,.8,.2,1) both;
    }

    .todo-row:hover {
        transform: translateX(3px);
        box-shadow: var(--sd-shadow-md);
    }

    .todo-row.fail { border-left: 4px solid var(--sd-danger); }
    .todo-row.warn { border-left: 4px solid var(--sd-warning); }

    /* =========================================================
       ANIMATION
       ========================================================= */
    @keyframes sd-hero-in {
        from { opacity: 0; transform: translateY(10px) scale(.992); }
        to { opacity: 1; transform: translateY(0) scale(1); }
    }

    @keyframes sd-fade-up {
        from { opacity: 0; transform: translateY(12px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes sd-float {
        0%, 100% { transform: translateY(-50%) translate3d(0,0,0); }
        50% { transform: translateY(calc(-50% - 9px)) translate3d(0,0,0); }
    }

    @keyframes sd-score-in {
        from { opacity: 0; transform: rotate(-18deg) scale(.9); }
        to { opacity: 1; transform: rotate(-8deg) scale(1); }
    }

    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            animation-duration: .01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: .01ms !important;
            scroll-behavior: auto !important;
        }
    }

    /* =========================================================
       RESPONSIVE
       ========================================================= */
    @media (max-width: 960px) {
        .hero-banner { min-height: 290px; padding: 38px 28px; }
        .hero-banner::before { right: -30px; opacity: .75; }
        .hero-banner::after { right: 8%; }
        .score-wrap { grid-template-columns: 1fr; text-align: center; }
        .score-badges { justify-content: center; }
        .sd-mini-grid { grid-template-columns: 1fr 1fr; }
        .sd-flow { grid-template-columns: 1fr 1fr; }
    }

    @media (max-width: 600px) {
        .block-container { padding-left: .8rem !important; padding-right: .8rem !important; }
        .hero-banner { min-height: 250px; padding: 28px 20px; border-radius: 22px; }
        .hero-banner h1 { font-size: 2.35rem !important; }
        .hero-banner p { font-size: .92rem; }
        .hero-banner::before { width: 160px; height: 160px; right: -38px; }
        .hero-banner::after { width: 54px; height: 54px; right: 9%; }
        .sd-flow { grid-template-columns: 1fr; }
        .sd-mini-grid { grid-template-columns: 1fr; }
        .score-ring { width: 180px; height: 180px; }
        .score-wrap { padding: 21px 17px; border-radius: 22px; }
        [data-testid="stTabs"] [data-baseweb="tab"] { padding: 0 11px; font-size: .8rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _restore_auth_from_cookie() -> str | None:
    """브라우저 세션 쿠키가 있으면 현재 Streamlit 세션으로 로그인 상태를 복원합니다."""
    if st.session_state.get("auth_user"):
        return str(st.session_state["auth_user"])

    session_token = None
    try:
        session_token = st.context.cookies.get("sd_session_token")
    except Exception:
        session_token = None

    if not session_token:
        try:
            session_token = _cookie_controller.get("sd_session_token")
        except Exception:
            session_token = None

    if session_token:
        username = get_username_by_session(str(session_token))
        if username:
            st.session_state["auth_user"] = username
            st.session_state["auth_session_token"] = str(session_token)
            return username
    return None


def _set_auth_cookie(username: str) -> bool:
    token = create_login_session(username)
    if not token:
        return False
    try:
        secure = str(getattr(st.context, "url", "")).startswith("https://")
    except Exception:
        secure = False
    try:
        # 만료일을 지정하지 않아 브라우저를 닫으면 세션이 종료됩니다.
        _cookie_controller.set(
            "sd_session_token",
            token,
            path="/",
            secure=secure,
            same_site="lax",
        )
    except Exception:
        delete_login_session(token)
        return False
    st.session_state["auth_user"] = username.strip()
    st.session_state["auth_session_token"] = token
    return True


def _logout() -> None:
    token = st.session_state.get("auth_session_token")
    try:
        if token:
            delete_login_session(str(token))
        _cookie_controller.remove("sd_session_token")
    except Exception:
        pass
    st.session_state.pop("auth_user", None)
    st.session_state.pop("auth_session_token", None)
    time.sleep(0.5)
    st.rerun()


def _render_auth_gate() -> str | None:
    """아이디/비밀번호 로그인. 새로고침 시 브라우저 세션 쿠키로 복원합니다."""
    restored_user = _restore_auth_from_cookie()
    if restored_user:
        if "sd_active_tab" not in st.session_state:
            st.session_state["sd_active_tab"] = "check"

        with st.sidebar:
            st.markdown("### 👤 로그인 상태")
            st.success(f"{restored_user}님")
            st.caption("현재 로그인한 계정")
            st.markdown("### 🧭 메뉴")

            if st.button("🩺 검사하기", key="sidebar_nav_check", use_container_width=True):
                st.session_state["sd_active_tab"] = "check"
                st.rerun()
            if st.button("📚 히스토리", key="sidebar_nav_history", use_container_width=True):
                st.session_state["sd_active_tab"] = "history"
                st.rerun()
            if st.button("💬 리뷰", key="sidebar_nav_reviews", use_container_width=True):
                st.session_state["sd_active_tab"] = "reviews"
                st.rerun()

            st.divider()
            if st.button("로그아웃", key="auth_logout", use_container_width=True):
                _logout()
        return restored_user

    st.markdown(
        """
        <div class="hero-banner">
            <h1>🩺 OGQ 스티커 닥터</h1>
            <p>로그인하면 내 진단 결과를 사용자별로 저장하고 재검사 기록을 확인할 수 있어요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
    with tab_login:
        with st.form("login_form"):
            username = st.text_input("아이디", key="login_username")
            password = st.text_input("비밀번호", type="password", key="login_password")
            submitted = st.form_submit_button("로그인", type="primary")
        if submitted:
            clean_username = username.strip()
            if verify_user(clean_username, password):
                if _set_auth_cookie(clean_username):
                    time.sleep(0.7)
                    st.rerun()
                else:
                    st.error("로그인 세션을 저장하지 못했습니다. 다시 시도해주세요.")
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

    with tab_signup:
        with st.form("signup_form"):
            username = st.text_input("새 아이디", key="signup_username")
            password = st.text_input("새 비밀번호", type="password", key="signup_password")
            password_confirm = st.text_input("비밀번호 확인", type="password", key="signup_password_confirm")
            birth_date = st.date_input(
                "생년월일",
                value=date(2008, 1, 1),
                min_value=date(1940, 1, 1),
                max_value=date.today(),
                format="YYYY/MM/DD",
                key="signup_birth_date",
                help="달력에서 고르거나 직접 입력해서 날짜를 바꿀 수 있어요.",
            )
            submitted = st.form_submit_button("회원가입")
        if submitted:
            if password != password_confirm:
                st.error("비밀번호 확인이 일치하지 않습니다.")
            else:
                ok, message = create_user(username, password, birth_date)
                if ok:
                    st.success(message + " 이제 로그인해 주세요.")
                else:
                    st.error(message)

    st.caption("로그인 상태는 브라우저 세션 동안 유지되며, 직접 로그아웃하면 즉시 종료됩니다.")
    return None


current_user = _render_auth_gate()
if _completion_sound_component is not None:
    _completion_sound_component(
        data={
            "play": False,
            "nonce": 0,
            "authenticated": bool(current_user),
            "target_tab": str(st.session_state.get("sd_active_tab", "check")),
        }
    )
if not current_user:
    st.stop()

st.markdown(
    """
    <div class="hero-banner">
        <div class="sd-kicker">🩺 OGQ STICKER DOCTOR</div>
        <h1>내 스티커,<br>어디가 문제일까요?</h1>
        <p>규격부터 시장 비교, AI 문제 위치 표시, 나만의 검사 기준까지 한곳에서 확인해보세요.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

col_head_a, col_head_b = st.columns([8, 2])
with col_head_a:
    st.caption(f"현재 로그인 · {current_user}")
with col_head_b:
    st.markdown('<div class="sd-note" style="text-align:center;font-weight:800;">CREATE · CHECK · IMPROVE</div>', unsafe_allow_html=True)

st.markdown(
    """
    <div class="sd-flow">
      <span class="sd-flow-item">📐 규격 검사</span><span class="sd-flow-arrow">→</span>
      <span class="sd-flow-item">📊 시장 비교</span><span class="sd-flow-arrow">→</span>
      <span class="sd-flow-item">🧠 AI 진단</span><span class="sd-flow-arrow">→</span>
      <span class="sd-flow-item">🛠 개선</span>
    </div>
    """,
    unsafe_allow_html=True,
)

def _draw_annotations(file_bytes: bytes, findings: list[dict]) -> Image.Image:
    """Gemini 공식 bbox 형식 [ymin, xmin, ymax, xmax]을 실제 이미지 좌표로 변환한다."""
    import io

    image = Image.open(io.BytesIO(file_bytes)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    width, height = image.size

    for idx, finding in enumerate(findings, 1):
        bbox = finding.get("bbox", [])
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue

        try:
            ymin, xmin, ymax, xmax = [max(0, min(1000, float(v))) for v in bbox]
        except (TypeError, ValueError):
            continue
        if xmax <= xmin or ymax <= ymin:
            continue

        # Gemini 공식 형식: [ymin, xmin, ymax, xmax]
        left = int(xmin / 1000 * width)
        top = int(ymin / 1000 * height)
        right = int(xmax / 1000 * width)
        bottom = int(ymax / 1000 * height)

        if right <= left or bottom <= top:
            continue

        # 지나치게 큰 영역은 표시하지 않는다. (모델이 전체 화면을 잘못 지정한 경우)
        area_ratio = ((right - left) * (bottom - top)) / max(1, width * height)
        if area_ratio > 0.90:
            continue

        line_width = max(3, min(width, height) // 85)
        draw.ellipse(
            (left, top, right, bottom),
            outline="#D92D20",
            width=line_width,
        )
        badge_left = max(0, left)
        badge_top = max(0, top - 28)
        draw.rounded_rectangle(
            (badge_left, badge_top, badge_left + 26, badge_top + 24),
            radius=8,
            fill="#D92D20",
        )
        draw.text(
            (badge_left + 8, badge_top + 4),
            str(idx),
            fill="#FFFFFF",
        )

    return image


def _speak_completion(message: str = "") -> None:
    """진단/시장 비교 완료 시 짧은 2음 벨소리를 재생합니다."""
    if _completion_sound_component is not None:
        _completion_sound_component(
            data={
                "play": True,
                "nonce": int(time.time() * 1000000),
            }
        )
        return

    # 구버전 Streamlit에서는 기존 iframe 방식으로 폴백합니다.
    components.html(
        """
        <div style="font-family:sans-serif; padding:2px 0;">
          <button id="ding-btn" style="border:1px solid #BFEFE9;border-radius:999px;padding:7px 14px;background:#EEFBF9;color:#0B3B36;font-weight:600;cursor:pointer;">🔔 완료음 다시 듣기</button>
        </div>
        <script>
        (() => {
          function ding() {
            try {
              const AC = window.AudioContext || window.webkitAudioContext;
              if (!AC) return;
              const ctx = new AC();
              const now = ctx.currentTime;
              const gain = ctx.createGain();
              gain.gain.setValueAtTime(0.0001, now);
              gain.gain.exponentialRampToValueAtTime(0.42, now + 0.015);
              gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.42);
              gain.connect(ctx.destination);
              const osc1 = ctx.createOscillator();
              osc1.type = 'sine';
              osc1.frequency.setValueAtTime(880, now);
              osc1.frequency.exponentialRampToValueAtTime(1320, now + 0.10);
              osc1.connect(gain);
              const osc2 = ctx.createOscillator();
              osc2.type = 'sine';
              osc2.frequency.setValueAtTime(1320, now + 0.12);
              osc2.frequency.exponentialRampToValueAtTime(1760, now + 0.22);
              osc2.connect(gain);
              osc1.start(now); osc1.stop(now + 0.11);
              osc2.start(now + 0.12); osc2.stop(now + 0.28);
              setTimeout(() => { try { ctx.close(); } catch (_) {} }, 650);
            } catch (_) {}
          }
          document.getElementById('ding-btn')?.addEventListener('click', ding);
        })();
        </script>
        """,
        height=45,
    )


def _get_secret(name: str, default: str = "") -> str:
    """Streamlit Secrets에서 문자열 값을 안전하게 읽는다."""
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = default
    return str(value or "").strip()


def _is_developer(username: str) -> bool:
    """Streamlit Secrets의 DEVELOPER_USERNAMES에 등록된 계정인지 확인한다."""
    raw = _get_secret("DEVELOPER_USERNAMES")
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return username.strip() in allowed


def _history_image_b64(file_bytes: bytes, findings: list[dict] | None = None, max_side: int = 420) -> str:
    """히스토리에서 다시 볼 수 있도록 문제 표시 이미지의 작은 PNG를 저장한다."""
    try:
        image = _draw_annotations(file_bytes, findings or [])
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _safe_market_results_for_history(results: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "content_id": item.get("content_id") or item.get("asset_id") or item.get("assetId") or "",
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "main_image_url": item.get("main_image_url") or item.get("thumbnail_url") or item.get("thumbnailUrl") or "",
                "creator_name": item.get("creator_name") or item.get("creator", {}).get("nickname", "") if isinstance(item.get("creator"), dict) else item.get("creator_name", ""),
                "published_at": item.get("published_at") or item.get("publishedAt") or "",
                "tags": list(item.get("tags") or [])[:10],
                "matched_keyword": item.get("matched_keyword", ""),
                "visual_match_score": item.get("visual_match_score", 0),
                "visual_match_hint": item.get("visual_match_hint", ""),
            }
        )
    return cleaned


def _build_history_payload(
    all_file_results: list[dict],
    selected_criteria: list[str],
    custom_rules: list[str],
    feelings: str,
    user_tags: list[str],
) -> dict:
    files_payload: dict[str, dict] = {}
    for file_result in all_file_results:
        digest = hashlib.sha256(file_result["bytes"]).hexdigest()[:16]
        cache_prefix = f"diag_v5_{file_result['name']}_{digest}_"
        matched_keys = [
            key for key in st.session_state.keys()
            if isinstance(key, str) and key.startswith(cache_prefix)
        ]
        diagnosis = st.session_state[matched_keys[-1]] if matched_keys else {}
        findings = diagnosis.get("findings", []) if isinstance(diagnosis, dict) else []
        files_payload[file_result["name"]] = {
            "img_type": file_result.get("img_type"),
            "results": file_result.get("results", []),
            "diagnosis": diagnosis,
            "annotated_image_b64": _history_image_b64(file_result["bytes"], findings),
        }

    return {
        "history_version": 2,
        "feelings": feelings,
        "user_tags": user_tags,
        "selected_criteria": selected_criteria,
        "custom_rules": custom_rules,
        "market_analysis": st.session_state.get("market_analysis", {}),
        "market_results": _safe_market_results_for_history(st.session_state.get("market_results", [])),
        "public_web_check": st.session_state.get("public_web_check", {}),
        "files": files_payload,
        "market_auto_diagnose": bool(st.session_state.get("auto_diagnose_after_market", False)),
    }


def _render_review_for_history(current_user: str, record: dict, developer_mode: bool = False) -> None:
    """선택한 히스토리에 대한 사용자 리뷰를 입력하고 기존 리뷰를 보여준다."""
    st.subheader("📝 이 진단에 대한 리뷰")
    st.caption("리뷰는 다음 AI 피드백을 개선하기 위한 데이터로 활용할 수 있습니다. 한 진단당 한 번 작성하며, 다시 제출하면 수정됩니다.")

    existing = load_reviews_for_record(record["id"], include_developer_only=True)
    own = next((r for r in existing if r.get("username") == current_user), None)

    with st.form(f"review_form_history_{record['id']}"):
        overall = st.slider("전체 만족도", 1, 5, int(own["overall_rating"]) if own else 4)
        usefulness = st.slider("도움이 된 정도", 1, 5, int(own["usefulness_rating"]) if own else 4)
        accuracy = st.slider("진단 정확도", 1, 5, int(own["accuracy_rating"]) if own else 4)
        issue_tags = st.multiselect(
            "아쉬웠던 부분 (여러 개 선택 가능)",
            [
                "문제 위치가 부정확함",
                "시장 비교가 부정확함",
                "비슷한 콘텐츠 판단이 아쉬움",
                "설명이 너무 일반적임",
                "수정 방법이 구체적이지 않음",
                "오탈자/텍스트 인식이 부정확함",
                "결과가 너무 길거나 복잡함",
                "특별한 아쉬움 없음",
            ],
            default=(own.get("issue_tags", []) if own else []),
        )
        comment = st.text_area(
            "추가 의견",
            value=(own.get("comment", "") if own else ""),
            placeholder="예: 시장의 유사 스티커는 잘 찾았지만, 왜 비슷한지 설명이 조금 더 구체적이면 좋겠습니다.",
        )
        visibility_label = st.radio(
            "리뷰 공개 범위",
            ["모두 공개", "개발자만 보기"],
            index=0 if not own or own.get("visibility") == "public" else 1,
            horizontal=True,
            help="모두 공개: 다른 사용자도 볼 수 있습니다. 개발자만 보기: 개발자 계정만 볼 수 있습니다.",
        )
        submitted = st.form_submit_button("리뷰 저장", type="primary")

    if submitted:
        review_id = save_review(
            current_user,
            record["id"],
            overall_rating=overall,
            usefulness_rating=usefulness,
            accuracy_rating=accuracy,
            issue_tags=issue_tags,
            comment=comment,
            visibility="public" if visibility_label == "모두 공개" else "developer",
        )
        if review_id:
            st.success("리뷰가 저장됐어요. 다음 진단을 개선하는 데 활용할 수 있습니다.")
            st.rerun()
        else:
            st.error("리뷰 저장에 실패했습니다.")

    if existing:
        st.markdown("**이 진단에 남겨진 리뷰**")
        visible_reviews = existing if developer_mode else [r for r in existing if r.get("visibility") == "public" or r.get("username") == current_user]
        for review in visible_reviews:
            visibility_text = "모두 공개" if review.get("visibility") == "public" else "개발자만"
            st.markdown(
                f"**{review.get('username', '사용자')}** · {'⭐' * int(review.get('overall_rating', 0))} · {visibility_text} · {review.get('timestamp', '')}"
            )
            st.caption(
                f"도움 {review.get('usefulness_rating', 0)}/5 · 정확도 {review.get('accuracy_rating', 0)}/5"
            )
            if review.get("issue_tags"):
                st.caption(" · ".join(review["issue_tags"]))
            if review.get("comment"):
                st.write(review["comment"])


def _save_current_diagnosis_to_history(
    current_user: str,
    all_file_results: list[dict],
    selected_criteria: list[str],
    custom_rules: list[str],
    feelings: str,
    user_tags: list[str],
) -> int | None:
    """현재 진단 결과를 한 번만 저장하고 record id를 세션에 기억합니다."""
    run_key_material = "|".join(
        f"{fr.get('name','')}:{hashlib.sha256(fr.get('bytes', b'')).hexdigest()}"
        for fr in all_file_results
    )
    run_key = hashlib.sha256(run_key_material.encode("utf-8")).hexdigest()

    if (
        st.session_state.get("current_history_run_key") == run_key
        and st.session_state.get("current_history_record_id")
    ):
        return int(st.session_state["current_history_record_id"])

    grades = [
        grade
        for fr in all_file_results
        for grade, _, _ in fr.get("results", [])
    ]
    checklist_status = {
        label: bool(st.session_state.get(f"chk_{key}", False))
        for label, key in {
            "저작권 있는 폰트를 상업적으로 이용 가능한 라이선스로만 사용했다": "font_license",
            "생성형 AI 사용 여부와 관련 규정을 확인했다": "ai_rule_check",
            "다른 판매자의 기존 콘텐츠와 차별화되는 요소가 있다": "no_duplicate",
            "텍스트가 잘리지 않고 세이프존 안에 들어와 있다": "text_safezone",
            "욕설·폭력·선정성·정치/종교 관련 부적합 요소가 없다": "no_sensitive_content",
        }.items()
    }
    checklist_done = sum(checklist_status.values())
    checklist_total = len(checklist_status)
    record_id = save_diagnosis_record(
        current_user,
        score=compute_score(all_file_results, checklist_done, checklist_total),
        pass_count=grades.count("pass"),
        warn_count=grades.count("warn"),
        fail_count=grades.count("fail"),
        checklist_done=checklist_done,
        checklist_total=checklist_total,
        file_count=len(all_file_results),
        market_keywords=_keywords_from_user_input(feelings, user_tags, limit=5),
        diagnosis_payload=_build_history_payload(
            all_file_results,
            selected_criteria,
            custom_rules,
            feelings,
            user_tags,
        ),
    )
    if record_id:
        st.session_state["current_history_run_key"] = run_key
        st.session_state["current_history_record_id"] = int(record_id)
    return record_id


def _render_immediate_review(current_user: str, record_id: int) -> None:
    """검사 완료 직후 같은 화면에서 리뷰를 남길 수 있게 합니다."""
    history = load_user_diagnosis_history(current_user, limit=50)
    record = next((item for item in history if int(item.get("id", -1)) == int(record_id)), None)
    if not record:
        st.error("방금 완료한 진단 기록을 불러오지 못했습니다. 히스토리 탭에서 확인해주세요.")
        return
    with st.expander("💬 방금 받은 AI 진단 리뷰 남기기", expanded=True):
        existing = load_reviews_for_record(record_id, include_developer_only=True)
        own = next((r for r in existing if r.get("username") == current_user), None)
        with st.form(f"review_form_immediate_{record_id}"):
            overall = st.slider("전체 만족도", 1, 5, int(own["overall_rating"]) if own else 4, key=f"immediate_overall_{record_id}")
            usefulness = st.slider("도움이 된 정도", 1, 5, int(own["usefulness_rating"]) if own else 4, key=f"immediate_usefulness_{record_id}")
            accuracy = st.slider("진단 정확도", 1, 5, int(own["accuracy_rating"]) if own else 4, key=f"immediate_accuracy_{record_id}")
            issue_tags = st.multiselect(
                "아쉬웠던 부분 (여러 개 선택 가능)",
                [
                    "문제 위치가 부정확함",
                    "시장 비교가 부정확함",
                    "비슷한 콘텐츠 판단이 아쉬움",
                    "설명이 너무 일반적임",
                    "수정 방법이 구체적이지 않음",
                    "오탈자/텍스트 인식이 부정확함",
                    "결과가 너무 길거나 복잡함",
                    "특별한 아쉬움 없음",
                ],
                default=(own.get("issue_tags", []) if own else []),
                key=f"immediate_issue_tags_{record_id}",
            )
            comment = st.text_area(
                "추가 의견",
                value=(own.get("comment", "") if own else ""),
                placeholder="예: 시장 비교는 좋았지만 문제 위치를 조금 더 정확하게 표시해주면 좋겠습니다.",
                key=f"immediate_comment_{record_id}",
            )
            visibility_label = st.radio(
                "리뷰 공개 범위",
                ["모두 공개", "개발자만 보기"],
                index=0 if not own or own.get("visibility") == "public" else 1,
                horizontal=True,
                key=f"immediate_visibility_{record_id}",
            )
            submitted = st.form_submit_button("리뷰 저장", type="primary")
        if submitted:
            saved = save_review(
                current_user, record_id,
                overall_rating=overall,
                usefulness_rating=usefulness,
                accuracy_rating=accuracy,
                issue_tags=issue_tags,
                comment=comment,
                visibility="public" if visibility_label == "모두 공개" else "developer",
            )
            if saved:
                st.success("리뷰가 저장됐어요. 다음 AI 개선에 활용할 수 있습니다.")
                st.rerun()
            else:
                st.error("리뷰 저장에 실패했습니다.")


def _render_history_detail(current_user: str, record: dict, developer_mode: bool = False) -> None:
    payload = record.get("diagnosis") or {}
    st.markdown(
        f"### 검사 #{record['id']} · {record['timestamp']} · {record['score']:.0f}점" if record.get("score") is not None else f"### 검사 #{record['id']} · {record['timestamp']}"
    )
    st.caption(
        f"파일 {record['file_count']}개 · PASS {record['pass']} · WARN {record['warn']} · FAIL {record['fail']} · 체크리스트 {record['checklist']}"
    )
    if record.get("market_keywords"):
        st.write("시장 검색어: " + ", ".join(record["market_keywords"]))

    if payload.get("feelings"):
        st.write("느낌/분위기: " + payload["feelings"])
    if payload.get("user_tags"):
        st.write("사용자 태그: " + ", ".join(f"#{t}" for t in payload["user_tags"]))

    with st.expander("적용된 검사 기준", expanded=False):
        selected = payload.get("selected_criteria") or []
        custom = payload.get("custom_rules") or []
        st.success(f"기본/공개 기준 {max(0, len(selected) - len(custom))}개 + 나만의 기준 {len(custom)}개 적용")
        for criterion in selected:
            st.write("✓ " + criterion)

    market = payload.get("market_analysis") or {}
    if market:
        st.markdown("### 📊 AI 시장 비교 결과")
        level = market.get("similarity_level", "보통")
        st.write(f"시장 유사성: **{level}**")
        if market.get("similarity_summary"):
            st.write(market["similarity_summary"])
        if market.get("differences"):
            st.markdown("**시장과의 차이점**")
            for item in market["differences"]:
                st.write("- " + item)
        if market.get("gaps"):
            st.markdown("**보완하면 좋은 점**")
            for item in market["gaps"]:
                st.write("- " + item)

    history_files = payload.get("files") or {}
    if history_files:
        st.markdown("### 🔴 AI 문제 위치 기록")
        for filename, item in history_files.items():
            diagnosis = item.get("diagnosis") or {}
            with st.expander(filename, expanded=False):
                image_b64 = item.get("annotated_image_b64")
                if image_b64:
                    try:
                        st.image(base64.b64decode(image_b64), caption="저장된 AI 문제 위치 표시", use_container_width=True)
                    except Exception:
                        pass
                st.markdown(f"**한 줄 총평:** {diagnosis.get('summary', '기록 없음')}")
                if diagnosis.get("detail"):
                    st.write(diagnosis["detail"])
                findings = diagnosis.get("findings") or []
                for idx, finding in enumerate(findings, 1):
                    st.markdown(
                        f"**{idx}. {finding.get('area', '검토 항목')}** · {finding.get('severity', '')}"
                    )
                    st.write(f"- 어디가: {finding.get('what', '')}")
                    st.write(f"- 왜: {finding.get('why', '')}")
                    st.write(f"- 어떻게: {finding.get('how', '')}")
                    if finding.get("market_basis"):
                        st.caption("시장 근거: " + finding["market_basis"])
                custom_results = diagnosis.get("custom_criteria_results") or []
                if custom_results:
                    st.markdown("**나만의 검사 기준 결과**")
                    for result in custom_results:
                        st.write(f"{result.get('status', '판단 어려움')} · {result.get('criterion', '')}: {result.get('result', '')}")

    _render_review_for_history(current_user, record, developer_mode=developer_mode)


def _render_history_center(current_user: str) -> None:
    """로그인 사용자가 자신의 과거 진단 기록을 언제든지 확인할 수 있는 탭."""
    history = load_user_diagnosis_history(current_user, limit=50)
    st.header("📚 내 진단 히스토리")
    st.caption("로그인한 계정의 과거 검사 결과를 언제든지 다시 볼 수 있어요.")

    if not history:
        st.info("아직 저장된 진단 히스토리가 없습니다. 검사를 저장하면 여기에 계속 남습니다.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("저장된 검사", len(history))
    with col2:
        st.metric("최근 점수", f"{history[-1]['score']:.0f}" if history[-1].get("score") is not None else "-")
    with col3:
        avg = sum(float(h.get("score") or 0) for h in history) / max(1, len(history))
        st.metric("평균 점수", f"{avg:.0f}")

    if len(history) >= 2:
        st.line_chart({"score": [h["score"] for h in history]})

    labels = {
        h["id"]: f"검사 #{h['id']} · {h['timestamp']} · {h['score']:.0f}점 · 파일 {h['file_count']}개"
        for h in reversed(history)
    }
    selected_id = st.selectbox(
        "확인할 히스토리",
        options=list(labels.keys()),
        format_func=lambda value: labels[value],
        key="history_selected_id",
    )
    selected_record = next(h for h in history if h["id"] == selected_id)
    _render_history_detail(current_user, selected_record, developer_mode=_is_developer(current_user))


def _render_review_center(current_user: str) -> None:
    """공개 리뷰와 개발자 전용 리뷰를 별도 탭으로 보여준다."""
    st.header("💬 리뷰")
    st.caption("AI 진단 결과에 대한 사용자 의견을 모아서 다음 피드백 개선에 활용합니다.")

    public_reviews = load_public_reviews(limit=20)
    st.subheader("🌎 모두가 볼 수 있는 공개 리뷰")
    if not public_reviews:
        st.caption("아직 공개 리뷰가 없습니다.")
    else:
        for review in public_reviews:
            st.markdown(
                f"**{review.get('username', '사용자')}** · {'⭐' * int(review.get('overall_rating', 0))} · 검사 #{review.get('record_id')}"
            )
            st.caption(
                f"도움 {review.get('usefulness_rating', 0)}/5 · 정확도 {review.get('accuracy_rating', 0)}/5 · {review.get('timestamp', '')}"
            )
            if review.get("issue_tags"):
                st.caption(" · ".join(review["issue_tags"]))
            if review.get("comment"):
                st.write(review["comment"])
            st.divider()

    if _is_developer(current_user):
        reviews = load_all_reviews(limit=100)
        st.subheader("🛠 개발자 리뷰 대시보드")
        if not reviews:
            st.caption("아직 리뷰 데이터가 없습니다.")
        else:
            avg_overall = sum(r["overall_rating"] for r in reviews) / len(reviews)
            avg_useful = sum(r["usefulness_rating"] for r in reviews) / len(reviews)
            avg_acc = sum(r["accuracy_rating"] for r in reviews) / len(reviews)
            a, b, c = st.columns(3)
            a.metric("리뷰 수", len(reviews))
            b.metric("평균 만족도", f"{avg_overall:.1f}/5")
            c.metric("평균 정확도", f"{avg_acc:.1f}/5")
            st.caption(f"평균 도움 정도: {avg_useful:.1f}/5 · 공개/개발자 전용 리뷰 모두 포함")
            for review in reviews[:30]:
                visibility = "공개" if review["visibility"] == "public" else "개발자 전용"
                st.markdown(
                    f"**검사 #{review['record_id']} · {review['username']} · {'⭐' * review['overall_rating']} · {visibility}**"
                )
                st.caption(
                    f"도움 {review['usefulness_rating']}/5 · 정확도 {review['accuracy_rating']}/5 · {review['timestamp']}"
                )
                if review.get("issue_tags"):
                    st.write("문제 태그: " + ", ".join(review["issue_tags"]))
                if review.get("comment"):
                    st.write(review["comment"])
                st.divider()


def _keywords_from_user_input(feelings: str, user_tags: list[str], limit: int = 5) -> list[str]:
    """느낌/태그 입력을 OGQ 검색용 키워드로 정리하고 중복을 제거한다."""
    raw_values: list[str] = []

    for part in (feelings or "").replace("\n", ",").split(","):
        value = " ".join(part.strip().split())
        if value:
            raw_values.append(value)

    for tag in user_tags:
        value = " ".join(str(tag or "").strip().lstrip("#").split())
        if value:
            raw_values.append(value)

    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= max(1, limit):
            break

    return result


def _generate_market_ai(
    gemini_key: str,
    market_prompt: str,
    user_image_bytes: bytes,
    user_image_mime: str,
    market_results: list[dict],
    *,
    max_output_tokens: int = 1700,
) -> tuple[dict, str | None]:
    """사용자 실제 이미지와 OGQ 참조 이미지를 함께 비교 분석한다."""
    from google import genai
    from google.genai import types
    from google.genai.errors import APIError, ServerError
    import json
    import random
    import time

    client = genai.Client(api_key=gemini_key)
    models = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
    refs = download_market_reference_images(market_results[:4])

    visual_instruction = """
[이미지 비교 규칙]
- 첫 번째 첨부 이미지는 '사용자 스티커'입니다.
- 이후 첨부 이미지는 각각 'OGQ 검색 결과 [번호]'의 실제 이미지입니다.
- 사용자가 입력한 태그는 보조 정보일 뿐이며, 이미지 자체보다 우선하지 않습니다.
- 사용자의 태그만 보고 시장과의 차이를 만들어내지 마세요.
- 사용자 이미지와 시장 참조 이미지가 실제로 같은 스티커이거나 거의 동일하면 그 사실을 명확하게 인정하고 유사성을 매우 높음으로 평가하세요.
- 검색 결과의 제목/태그가 서로 달라도 실제 이미지가 같다면 '다르다'고 쓰지 마세요.
- differences는 실제 이미지 또는 제목/설명/태그 중 확인 가능한 근거가 있을 때만 작성하세요.
- comparisons는 실제로 비교 가능한 결과만 최대 4개 작성하세요.
"""
    contents = [
        market_prompt + "\n" + visual_instruction,
        "[USER STICKER IMAGE]",
        types.Part.from_bytes(data=user_image_bytes, mime_type=user_image_mime),
    ]
    for ref in refs:
        contents.extend([
            f"[OGQ SEARCH RESULT {ref['index']}] {ref['title']}",
            types.Part.from_bytes(data=ref["bytes"], mime_type=ref["mime_type"]),
        ])

    last_error: Exception | None = None
    for model_name in models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=MARKET_SCHEMA,
                        max_output_tokens=max_output_tokens,
                        temperature=0.15,
                    ),
                )
                raw = (response.text or "").strip()
                if not raw:
                    raise RuntimeError(f"{model_name}이 빈 응답을 반환했습니다.")
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    start_json = raw.find("{")
                    end_json = raw.rfind("}")
                    if start_json < 0 or end_json <= start_json:
                        raise RuntimeError("시장 분석 결과가 JSON으로 반환되지 않았습니다.")
                    parsed = json.loads(raw[start_json:end_json + 1])
                return normalize_market_analysis(parsed), None
            except (ServerError, APIError, RuntimeError, json.JSONDecodeError) as exc:
                last_error = exc
                code = getattr(exc, "code", None)
                transient = isinstance(exc, ServerError) or code in {408, 429, 500, 502, 503, 504}
                if transient and attempt < 1:
                    time.sleep(min(6.0, 1.5 * (2 ** attempt)) + random.uniform(0, 0.4))
                    continue
                if not transient:
                    break

    return {}, (
        "Gemini 시장 비교 분석에 실패했습니다. 검색된 OGQ 콘텐츠는 정상적으로 확인할 수 있습니다. "
        f"({last_error})"
    )


def _run_ai_diagnostics(
    all_file_results: list[dict],
    selected_criteria: list[str],
    custom_rules: list[str],
    market_context: str,
    gemini_key: str,
) -> bool:
    """전체 스티커 AI 진단을 실행한다. 성공/실패와 무관하게 UI가 계속 렌더링되도록 결과를 세션에 저장한다."""
    progress = st.progress(0, text="AI가 스티커를 살펴보는 중...")
    had_success = False
    for i, file_result in enumerate(all_file_results):
        digest = hashlib.sha256(file_result["bytes"]).hexdigest()[:16]
        criteria_key = hashlib.md5(",".join(selected_criteria).encode("utf-8")).hexdigest()[:8]
        market_key = hashlib.md5(market_context.encode("utf-8")).hexdigest()[:8]
        cache_key = f"diag_v5_{file_result['name']}_{digest}_{criteria_key}_{market_key}"

        if cache_key not in st.session_state:
            try:
                detailed = diagnose_detailed(
                    file_result["bytes"],
                    file_result["mime"],
                    gemini_key,
                    selected_criteria=selected_criteria,
                    market_context=market_context,
                    custom_criteria=custom_rules,
                )
                st.session_state[cache_key] = detailed
                if detailed.get("model_used"):
                    had_success = True
            except Exception as exc:
                st.session_state[cache_key] = {
                    "summary": "이번 스티커의 AI 진단은 일시적으로 완료되지 않았습니다.",
                    "detail": "Gemini 서버가 일시적으로 바쁘거나 요청을 처리하지 못했습니다. 자동 재시도와 대체 모델을 시도했지만 응답을 받지 못했습니다. 규격 검사 결과는 계속 확인할 수 있습니다.",
                    "findings": [],
                    "strengths": [],
                    "market_note": "",
                    "custom_criteria_results": [],
                    "raw_text": "",
                    "model_used": "",
                    "diagnosis_error": str(exc),
                }
        else:
            had_success = True

        progress.progress((i + 1) / len(all_file_results), text=f"{i + 1}/{len(all_file_results)} 완료")

    progress.empty()
    return had_success


st.markdown('<div class="sd-kicker">WORKSPACE</div>', unsafe_allow_html=True)

# 사이드바에서 선택한 메뉴를 기준으로 실제 화면을 전환합니다.
# st.tabs의 브라우저 탭을 JS로 강제 클릭하는 방식 대신 Streamlit이 직접 렌더링하므로
# 메뉴 클릭 후에도 히스토리/리뷰 화면이 확실하게 표시됩니다.
active_tab = st.session_state.get("sd_active_tab", "check")

if active_tab == "history":
    _render_history_center(current_user)
elif active_tab == "reviews":
    _render_review_center(current_user)
else:
    # ---------- 0단계: 검사 기준 ----------
    st.header("검사 기준 설정")
    st.caption("OGQ 공개 가이드를 기본으로 불러오고, 원하는 검사 항목만 선택하거나 나만의 기준을 원하는 만큼 추가할 수 있어요.")

    preset_names = list(PLATFORM_PRESETS.keys()) + ["내가 직접 선택"]
    preset = st.selectbox("검사 기준 프로필", preset_names, index=0)

    default_names = [name for name, _ in DEFAULT_CRITERIA]
    if preset == "내가 직접 선택":
        selected_default = default_names
    else:
        selected_default = PLATFORM_PRESETS.get(preset, default_names)

    selected_criteria = st.multiselect(
        "검사할 심사 영역",
        options=default_names,
        default=selected_default,
    )

    if "custom_rules" not in st.session_state:
        st.session_state["custom_rules"] = []

    st.markdown("**나만의 검사 기준**")
    custom_rule_text = st.text_input(
        "새 검사 기준",
        key="custom_rule_input",
        placeholder="예: 캐릭터 얼굴이 이미지의 30% 이상 보이는지 확인",
    )
    if st.button("＋ 검사 기준 추가"):
        rule = " ".join(custom_rule_text.strip().split())
        if not rule:
            st.warning("추가할 검사 기준을 입력해주세요.")
        elif rule in st.session_state["custom_rules"]:
            st.info("이미 추가된 검사 기준입니다.")
        else:
            st.session_state["custom_rules"].append(rule)
            st.success("검사 기준이 추가됐습니다. 다음 AI 진단에 적용됩니다.")

    custom_rules = list(st.session_state["custom_rules"])
    if custom_rules:
        for idx, rule in enumerate(custom_rules):
            c1, c2 = st.columns([8, 1])
            with c1:
                st.write(f"**{idx + 1}.** {rule}")
            with c2:
                if st.button("삭제", key=f"delete_custom_rule_{idx}"):
                    st.session_state["custom_rules"].pop(idx)
                    st.rerun()
    else:
        st.caption("아직 사용자 지정 기준이 없습니다. 원하는 만큼 추가할 수 있습니다.")

    selected_criteria = build_selected_criteria("내가 직접 선택", selected_criteria, custom_rules)
    standard_selected = [item for item in selected_criteria if item not in custom_rules]
    with st.expander("이번 AI 진단에 적용되는 기준 확인", expanded=True):
        st.success(f"적용됨 · 기본/공개 기준 {len(standard_selected)}개 + 나만의 기준 {len(custom_rules)}개")
        if standard_selected:
            st.markdown("**기본/공개 기준**")
            for criterion in standard_selected:
                st.write(f"✓ {criterion}")
        if custom_rules:
            st.markdown("**나만의 기준 — 개별 결과가 별도 표시됩니다**")
            for rule in custom_rules:
                st.write(f"✓ {rule}")

    st.caption("파일 해상도·용량·형식 같은 기술 규격 검사는 기본으로 유지되고, 위에서 선택한 영역은 AI 심층 진단에 적용됩니다.")

    # ---------- 1단계: 이미지 + 사용자 설명 ----------
    st.header("1단계 · 스티커 정보 입력")
    feelings = st.text_input(
        "이 스티커는 어떤 느낌인가요?",
        placeholder="예: 귀여움, 장난스러움, 직장인 공감, 살짝 시니컬함",
    )
    tag_text = st.text_input(
        "태그를 입력해주세요",
        placeholder="쉼표로 구분해서 입력: 강아지, 직장인, 출근, 피곤",
    )
    user_tags = [t.strip().lstrip("#") for t in tag_text.split(",") if t.strip()]

    st.header("2단계 · 스티커 업로드")
    st.caption("OGQ 공개 제작 가이드 기준: 메인 240x240 · 스티커 740x640 · 탭 96x74, 각 1MB 이하, RGB, 투명 배경 · 파일마다 이미지 종류를 직접 지정할 수 있어요.")

    files = st.file_uploader(
        "스티커 이미지를 올려주세요 (여러 장 가능)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )

    if files:
        current_upload_material = "|".join(
            f"{f.name}:{hashlib.sha256(f.getvalue()).hexdigest()}" for f in files
        )
        current_upload_key = hashlib.sha256(current_upload_material.encode("utf-8")).hexdigest()
        if st.session_state.get("current_upload_key") != current_upload_key:
            st.session_state["current_upload_key"] = current_upload_key
            st.session_state.pop("current_history_run_key", None)
            st.session_state.pop("current_history_record_id", None)

        type_counts = {name: 0 for name in SPECS}
        all_file_results = []

        st.info("각 파일이 메인 이미지인지, 스티커 이미지인지, 탭 이미지인지 직접 지정해주세요.\n파일 크기가 규격과 맞는 경우에는 자동으로 해당 종류를 먼저 선택해 드립니다.")

        def _guess_image_type(filename, width=None, height=None):
            # 1순위: 실제 해상도가 OGQ 규격과 정확히 일치하면 그 종류를 자동 선택
            if width is not None and height is not None:
                detected = classify_type(width, height)
                if detected:
                    return detected

            # 2순위: 파일명에 흔한 종류 표기가 있으면 보조적으로 추정
            lowered = filename.lower()
            if any(token in lowered for token in ("tab", "탭")):
                return "탭 이미지"
            if any(token in lowered for token in ("main", "메인", "대표", "thumbnail", "thumb")):
                return "메인 이미지"
            return "스티커 이미지"

        for index, f in enumerate(files):
            file_bytes = f.getvalue()
            try:
                preview_img = Image.open(io.BytesIO(file_bytes))
                width, height = preview_img.size
            except Exception:
                width, height = None, None

            detected_type = classify_type(width, height) if width is not None and height is not None else None
            default_type = _guess_image_type(f.name, width, height)
            default_index = list(SPECS.keys()).index(default_type)
            file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]

            selected_type = st.selectbox(
                f"{f.name} · 이미지 종류",
                list(SPECS.keys()),
                index=default_index,
                key=f"image_type_{file_hash}",
                help="이 파일을 OGQ 제출 구성에서 어떤 이미지로 사용할지 지정합니다.",
            )

            img_type, results = check_image(file_bytes, f.name, expected_type=selected_type)
            if img_type:
                type_counts[img_type] += 1

            all_file_results.append(
                {
                    "name": f.name,
                    "bytes": file_bytes,
                    "mime": f.type or "image/png",
                    "img_type": img_type,
                    "expected_type": selected_type,
                    "detected_type": detected_type,
                    "results": results,
                }
            )

            detected_text = detected_type or "일치하는 규격 없음"
            st.caption(f"지정: **{selected_type}** · 실제 크기: **{width}×{height}px** · 크기만으로 추정: **{detected_text}**")

            fail_count = sum(1 for grade, _, _ in results if grade == "fail")
            icon = "❌" if fail_count else "✅"
            with st.expander(
                f"{icon} {f.name} — {selected_type} · 문제 {fail_count}건",
                expanded=fail_count > 0,
            ):
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.image(file_bytes)
                with col2:
                    for grade, item, msg in results:
                        if grade == "pass":
                            st.success(f"**{item}** — {msg}")
                        elif grade == "warn":
                            st.warning(f"**{item}** — {msg}")
                        else:
                            st.error(f"**{item}** — {msg}")

        # 시장 비교/AI 이미지 비교에는 제출용 스티커 이미지를 우선 사용한다.
        comparison_file = next(
            (item for item in all_file_results
             if item.get("expected_type") == "스티커 이미지" and item.get("img_type") == "스티커 이미지"),
            all_file_results[0] if all_file_results else None,
        )

        # ---------- 3단계: 시장 비교 ----------
        st.divider()
        st.markdown(
            '<div class="sd-stage-heading"><span class="step">3단계</span><span>OGQ 시장 비교</span></div>',
            unsafe_allow_html=True,
        )
        st.caption("입력한 느낌과 태그를 키워드로 OGQ 마켓의 관련 스티커를 찾고, AI가 공통점·차이점·장단점을 분석합니다.")

        auto_diagnose_after_market = st.checkbox(
            "시장 비교가 끝나면 바로 AI 문제 표시까지 실행",
            value=False,
            key="auto_diagnose_after_market",
            help="체크하면 시장 비교와 시장 분석이 끝난 직후 선택한 검사 기준으로 AI 진단을 자동 실행합니다.",
        )

        public_web_enabled = st.checkbox(
            "Google 공개 웹 유사성 참고 조사도 실행",
            value=False,
            key="public_web_enabled",
            help="OGQ 시장 분석과 별도로 공개 웹을 참고합니다. 추가 Gemini 요청이 발생하므로 필요할 때만 켜는 것을 권장합니다.",
        )

        if st.button("🔎 OGQ 시장과 비교하기", type="primary"):
            # 이전 결과를 먼저 비워서 검색 실패 시 오래된 결과가 보이지 않도록 한다.
            st.session_state.pop("market_results", None)
            st.session_state.pop("market_analysis", None)
            st.session_state.pop("market_context", None)
            st.session_state.pop("market_analysis_error", None)
            st.session_state.pop("public_web_check", None)
            st.session_state.pop("public_web_check_error", None)
            st.session_state.pop("auto_diag_completed_for_market_key", None)

            ogq_api_key = _get_secret("OGQ_API_KEY")
            base_url = _get_secret(
                "OGQ_API_BASE_URL",
                "https://4th-ai-ogq.competition.ogq.me",
            )

            if not ogq_api_key:
                st.error("OGQ API 키가 설정되지 않았어요. Streamlit Secrets에 OGQ_API_KEY를 추가해주세요.")
            else:
                keywords = _keywords_from_user_input(feelings, user_tags, limit=5)
                if not keywords:
                    st.warning("시장 검색에 사용할 느낌이나 태그를 하나 이상 입력해주세요.")
                else:
                    try:
                        with st.spinner("OGQ 마켓을 검색하고 있어요..."):
                            market_results = search_by_keywords(
                                ogq_api_key,
                                keywords,
                                max_keywords=5,
                                per_keyword=8,
                                max_results=12,
                                max_detail_requests=8,
                                base_url=base_url,
                                user_id=None,
                            )

                        # 업로드 이미지와 OGQ 검색 결과의 강한 시각 일치 신호를 먼저 계산
                        from market_analysis import annotate_visual_match_hints
                        market_results = annotate_visual_match_hints(
                            comparison_file["bytes"], market_results
                        )
                        # 강한 일치 신호가 있는 항목을 앞쪽으로 우선 배치
                        market_results.sort(
                            key=lambda item: float(item.get("visual_match_score") or 0.0),
                            reverse=True,
                        )
                        st.session_state["market_results"] = market_results

                        if market_results:
                            market_prompt = build_market_analysis_prompt(
                                feelings,
                                user_tags,
                                market_results[:8],
                            )

                            gemini_key = _get_secret("GEMINI_API_KEY")
                            if gemini_key:
                                with st.spinner("OGQ 시장 결과를 실제 이미지와 비교 분석하고 있어요..."):
                                    analysis, error_message = _generate_market_ai(
                                        gemini_key,
                                        market_prompt,
                                        comparison_file["bytes"],
                                        comparison_file["mime"],
                                        market_results[:8],
                                        max_output_tokens=1700,
                                    )
                                if analysis:
                                    st.session_state["market_analysis"] = analysis

                                    # 공개 웹 조사는 선택 사항으로 분리한다.
                                    # 시장 비교 자체가 추가 Gemini 검색 호출 때문에 막히지 않도록 한다.
                                    if public_web_enabled:
                                        web_check = generate_public_web_check(
                                            gemini_key,
                                            feelings,
                                            user_tags,
                                        )
                                        if web_check.get("text"):
                                            st.session_state["public_web_check"] = web_check
                                        elif web_check.get("error"):
                                            st.session_state["public_web_check_error"] = web_check["error"]
                                    else:
                                        st.session_state["public_web_check"] = {}
                                        st.session_state["public_web_check_error"] = "공개 웹 유사성 참고 조사는 선택하지 않아 실행하지 않았습니다. OGQ 시장 비교 분석에는 영향을 주지 않습니다."

                                    # 이미지 진단에는 실제 시장 분석 + (실행했다면) 공개 웹 보조 조사 결과를 전달한다.
                                    st.session_state["market_context"] = build_market_context_for_diagnosis(
                                        analysis,
                                        market_results[:8],
                                        st.session_state.get("public_web_check", {}),
                                    )
                                if error_message:
                                    st.session_state["market_analysis_error"] = error_message
                            else:
                                st.session_state["market_analysis_error"] = (
                                    "Gemini API 키가 없어 시장 검색 결과만 표시합니다."
                                )
                        else:
                            st.session_state["market_analysis_error"] = (
                                "관련 OGQ 콘텐츠를 찾지 못했습니다. 다른 느낌이나 태그를 입력해 보세요."
                            )

                    except OGQAPIError as exc:
                        st.error(f"OGQ 시장 검색에 실패했어요: {exc}")
                    else:
                        # 3단계 시장 비교가 정상적으로 끝난 시점에 완료음을 재생합니다.
                        _speak_completion("OGQ 시장 비교가 완료되었습니다.")

        # 시장 비교 완료 직후 자동 진단 옵션이 켜져 있으면 바로 AI 문제 표시까지 진행
        if auto_diagnose_after_market and st.session_state.get("market_results") and st.session_state.get("market_context"):
            if not st.session_state.get("auto_diag_completed_for_market_key"):
                auto_key = hashlib.md5(st.session_state.get("market_context", "").encode("utf-8")).hexdigest()[:12]
                gemini_key = _get_secret("GEMINI_API_KEY")
                if gemini_key:
                    with st.spinner("시장 비교가 끝났어요. 바로 AI가 문제 위치를 분석하고 있어요..."):
                        _run_ai_diagnostics(
                            all_file_results,
                            selected_criteria,
                            custom_rules,
                            st.session_state.get("market_context", ""),
                            gemini_key,
                        )
                    st.session_state["auto_diag_completed_for_market_key"] = auto_key
                    st.success("시장 비교에 이어 AI 문제 표시까지 완료했어요.")
                    _speak_completion("시장 비교와 AI 문제 진단이 모두 완료되었습니다.")

        market_results = st.session_state.get("market_results", [])
        if market_results:
            st.subheader(f"관련 콘텐츠 {len(market_results)}개")
            cols = st.columns(4)
            for i, item in enumerate(market_results[:8]):
                with cols[i % 4]:
                    if item.get("main_image_url"):
                        st.image(item["main_image_url"], use_container_width=True)
                    st.caption(item.get("title", "제목 없음"))
                    if item.get("description"):
                        st.caption(item["description"][:90])
                    if item.get("matched_keyword"):
                        st.caption(f"검색어: {item['matched_keyword']}")
                    tags = item.get("tags") or []
                    if tags:
                        st.caption("태그: " + ", ".join(f"#{tag}" for tag in tags[:6]))

            market_analysis = st.session_state.get("market_analysis")
            if isinstance(market_analysis, dict):
                st.subheader("AI 시장 비교")

                level = market_analysis.get("similarity_level", "보통")
                level_emoji = {"높음": "🔴", "보통": "🟡", "낮음": "🟢"}.get(level, "🟡")
                st.markdown(f"**시장 유사성: {level_emoji} {level}**")
                if market_analysis.get("similarity_summary"):
                    st.write(market_analysis["similarity_summary"])

                comparisons = market_analysis.get("comparisons") or []
                if comparisons:
                    st.markdown("**시장 콘텐츠별 유사성**")
                    for comp in comparisons:
                        try:
                            idx = int(comp.get("result_index", 0))
                        except (TypeError, ValueError):
                            continue
                        if not (1 <= idx <= len(market_results[:8])):
                            continue
                        source = market_results[idx - 1]
                        st.markdown(f"**[{idx}] {source.get('title', 'OGQ 콘텐츠')} — 유사성: {comp.get('similarity_level', '보통')}**")
                        if comp.get("similarity_reason"):
                            st.write(comp["similarity_reason"])
                        if comp.get("same_points"):
                            st.caption("같은 점: " + " · ".join(comp["same_points"]))
                        if comp.get("different_points"):
                            st.caption("다른 점: " + " · ".join(comp["different_points"]))

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**시장 전반의 공통 요소**")
                    similarities = market_analysis.get("similarities") or []
                    if similarities:
                        for item in similarities:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("검색 결과에서 반복적으로 확인되는 공통 요소가 없습니다.")
                with c2:
                    st.markdown("**시장과의 차이점**")
                    differences = market_analysis.get("differences") or []
                    if differences:
                        for item in differences:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("검색 데이터만으로 확인되는 뚜렷한 차이점이 없습니다.")

                st.markdown("**시장과 비교했을 때의 장점**")
                for item in (market_analysis.get("strengths") or []):
                    st.markdown(f"- {item}")
                if not market_analysis.get("strengths"):
                    st.caption("검색 결과만으로 판단할 수 있는 장점을 찾지 못했습니다.")

                st.markdown("**보완하면 좋은 점**")
                for item in (market_analysis.get("gaps") or []):
                    st.markdown(f"- {item}")
                if not market_analysis.get("gaps"):
                    st.caption("검색 결과만으로 확인되는 보완점이 없습니다.")

                priority = market_analysis.get("priority_actions") or []
                if priority:
                    st.markdown("**먼저 확인할 것**")
                    for idx, item in enumerate(priority, 1):
                        st.markdown(f"{idx}. {item}")

                evidence = market_analysis.get("evidence") or []
                if evidence:
                    with st.expander("시장 분석 근거 보기"):
                        for item in evidence:
                            idx = item.get("result_index")
                            reason = item.get("reason", "")
                            if idx and 1 <= int(idx) <= len(market_results[:8]):
                                source = market_results[int(idx) - 1]
                                st.markdown(
                                    f"**[{idx}] {source.get('title', '콘텐츠')}** — {reason}"
                                )

            elif st.session_state.get("market_analysis"):
                # 이전 버전의 문자열 결과가 세션에 남아도 화면이 깨지지 않도록 호환
                st.subheader("AI 시장 비교")
                st.markdown(str(st.session_state["market_analysis"]))

            public_web = st.session_state.get("public_web_check")
            if isinstance(public_web, dict) and public_web.get("text"):
                st.markdown("**공개 웹 대중적 유사성 참고**")
                st.caption("OGQ 마켓 밖의 공개 웹 자료를 보조적으로 확인한 결과입니다. 법적 표절·저작권 판단이 아닙니다.")
                st.markdown(public_web["text"])
                sources = public_web.get("sources") or []
                if sources:
                    with st.expander("웹 검색 근거 보기"):
                        for source in sources:
                            title = source.get("title") or source.get("uri")
                            uri = source.get("uri") or ""
                            st.markdown(f"- [{title}]({uri})")
            if st.session_state.get("public_web_check_error"):
                st.caption(st.session_state["public_web_check_error"])

            if st.session_state.get("market_analysis_error"):
                st.warning(st.session_state["market_analysis_error"])

        # ---------- 4단계: AI 진단 + 위치 표시 ----------
        st.divider()
        st.markdown(
            '<div class="sd-stage-heading"><span class="step">4단계</span><span>AI가 어디가 문제인지 표시</span></div>',
            unsafe_allow_html=True,
        )
        st.caption("선택한 검사 영역과 시장 비교 자료를 바탕으로 문제 영역을 표시하고, 무엇을/왜/어떻게 고칠지 설명합니다.")

        market_context = st.session_state.get("market_context", "")

        if st.button(f"🧠 업로드한 {len(files)}개 전체 AI 진단 받기", type="primary"):
            gemini_key = _get_secret("GEMINI_API_KEY")
            if not gemini_key:
                st.error("Gemini API 키가 설정되지 않았어요. Streamlit Secrets에 GEMINI_API_KEY를 추가해주세요.")
            else:
                completed = _run_ai_diagnostics(
                    all_file_results,
                    selected_criteria,
                    custom_rules,
                    market_context,
                    gemini_key,
                )
                if completed:
                    st.success("전체 AI 진단이 끝났어요.")
                else:
                    st.warning("AI 진단이 완료되지 않은 파일이 있습니다. 잠시 후 다시 시도해 주세요.")
                _speak_completion()


        # 결과 렌더링
        diagnosis_texts: dict[str, str] = {}
        for file_result in all_file_results:
            digest = hashlib.sha256(file_result["bytes"]).hexdigest()[:16]
            cache_prefix = f"diag_v5_{file_result['name']}_{digest}_"
            matched_keys = [
                key
                for key in st.session_state.keys()
                if isinstance(key, str) and key.startswith(cache_prefix)
            ]
            if not matched_keys:
                continue

            diagnosis = st.session_state[matched_keys[-1]]
            diagnosis_texts[file_result["name"]] = render_diagnosis_markdown(diagnosis)

            with st.expander(
                f"🧠 AI 진단 — {file_result['name']}",
                expanded=True,
            ):
                st.markdown(diagnosis_texts[file_result["name"]])

                if diagnosis.get("diagnosis_error"):
                    st.warning("⚠️ 이번 AI 진단 요청에서 일시적인 오류가 발생했습니다. 아래 진단 결과와 시장 자료가 있다면 계속 참고할 수 있습니다.")

                if custom_rules:
                    custom_results = diagnosis.get("custom_criteria_results") or []
                    st.subheader("나만의 검사 기준 결과")
                    returned = {str(item.get("criterion", "")).strip() for item in custom_results if isinstance(item, dict)}
                    st.success(f"사용자 지정 기준 {len(custom_rules)}개가 이번 AI 요청에 포함됐고, {len(returned)}/{len(custom_rules)}개 개별 평가가 반환되었습니다.")
                    status_icon = {"양호": "🟢", "주의": "🟡", "개선 필요": "🔴", "판단 어려움": "⚪"}
                    for rule in custom_rules:
                        item = next((x for x in custom_results if isinstance(x, dict) and str(x.get("criterion", "")).strip() == rule), None)
                        if not item:
                            item = {"status": "판단 어려움", "result": "개별 평가가 반환되지 않았습니다.", "evidence": "응답 누락"}
                        st.markdown(f"**{status_icon.get(item.get('status'), '⚪')} {rule} · {item.get('status', '판단 어려움')}**")
                        st.write(item.get("result", ""))
                        if item.get("evidence"):
                            st.caption(f"근거: {item['evidence']}")

                findings = diagnosis.get("findings", [])
                if findings:
                    st.subheader("문제 위치")
                    annotated = _draw_annotations(file_result["bytes"], findings)
                    st.image(
                        annotated,
                        caption="🔴 AI가 문제 위치로 판단한 영역 — 참고용 시각화",
                        use_container_width=True,
                    )

                    for idx, finding in enumerate(findings, 1):
                        severity_label = {
                            "high": "🔴 높음",
                            "medium": "🟡 중간",
                            "low": "🟢 낮음",
                        }.get(finding.get("severity"), "검토")
                        st.markdown(
                            f"**{idx}. {severity_label} · {finding.get('area', '검토 항목')}**\n\n"
                            f"- **어디가:** {finding.get('what', '')}\n"
                            f"- **왜:** {finding.get('why', '')}\n"
                            f"- **어떻게:** {finding.get('how', '')}"
                        )
                else:
                    st.info("이미지에서 위치를 특정할 수 있는 개선 항목이 없습니다.")

        # ---------- 검사 완료 직후 리뷰 ----------
        if diagnosis_texts:
            st.divider()
            st.header("💬 검사 결과 리뷰")
            st.caption("지금 받은 진단이 실제로 도움이 되었는지 바로 남겨주세요. 리뷰를 저장하면 다음 AI 피드백 개선에 활용할 수 있습니다.")
            current_record_id = st.session_state.get("current_history_record_id")
            if current_record_id:
                _render_immediate_review(current_user, int(current_record_id))
            elif st.button("📝 이 검사 결과에 리뷰 남기기", type="secondary"):
                record_id = _save_current_diagnosis_to_history(
                    current_user,
                    all_file_results,
                    selected_criteria,
                    custom_rules,
                    feelings,
                    user_tags,
                )
                if record_id:
                    st.session_state["current_history_record_id"] = int(record_id)
                    st.rerun()
                else:
                    st.error("리뷰를 저장할 진단 기록을 만들지 못했습니다.")

        # ---------- 5단계: 기존 셀프 체크리스트 ----------
        st.divider()
        st.header("5단계 · 규정 위반 셀프 체크리스트")
        st.caption("이미지만으로 확정하기 어려운 항목은 직접 확인해 주세요.")

        checklist_items = {
            "저작권 있는 폰트를 상업적으로 이용 가능한 라이선스로만 사용했다": "font_license",
            "생성형 AI 사용 여부와 관련 규정을 확인했다": "ai_rule_check",
            "다른 판매자의 기존 콘텐츠와 차별화되는 요소가 있다": "no_duplicate",
            "텍스트가 잘리지 않고 세이프존 안에 들어와 있다": "text_safezone",
            "욕설·폭력·선정성·정치/종교 관련 부적합 요소가 없다": "no_sensitive_content",
        }
        checklist_status = {}
        for label, key in checklist_items.items():
            checklist_status[label] = st.checkbox(label, key=f"chk_{key}")

        checklist_done = sum(1 for value in checklist_status.values() if value)
        checklist_total = len(checklist_items)
        st.caption(f"체크리스트 {checklist_done}/{checklist_total} 완료")

        # ---------- 6단계: 점수 + Todo ----------
        st.divider()
        st.header("6단계 · 준비도 & 개선 우선순위")
        score = compute_score(
            all_file_results,
            checklist_done,
            checklist_total,
        )
        grades = [
            grade
            for file_result in all_file_results
            for grade, _, _ in file_result.get("results", [])
        ]
        pass_count = grades.count("pass")
        warn_count = grades.count("warn")
        fail_count = grades.count("fail")
        market_hits = len(st.session_state.get("market_results", []) or [])
        custom_count = len(custom_rules)
        todo_preview_count = len(build_priority_todo(all_file_results))
        score_message = (
            "기본 검사 기준을 대부분 충족하고 있어요." if score >= 85 else
            "큰 문제는 적지만 몇 가지 개선 포인트를 확인해보세요." if score >= 70 else
            "제출 전에 우선순위가 높은 문제부터 수정하는 것을 권장해요."
        )
        st.markdown(
            f"""
            <div class="score-wrap">
              <div class="score-ring" style="--score:{score:.0f};">
                <div class="score-center">
                  <div class="num">{score:.0f}</div>
                  <div class="unit">/ 100 · 준비도</div>
                </div>
              </div>
              <div class="score-info">
                <h3>✨ OGQ 준비도 점수</h3>
                <p>{score_message}</p>
                <div class="score-badges">
                  <span class="score-badge good">🟢 정상 {pass_count}</span>
                  <span class="score-badge warn">🟡 주의 {warn_count}</span>
                  <span class="score-badge bad">🔴 실패 {fail_count}</span>
                  <span class="score-badge">📊 시장 결과 {market_hits}</span>
                  <span class="score-badge">🧩 커스텀 기준 {custom_count}</span>
                </div>
              </div>
            </div>
            <div class="sd-mini-grid">
              <div class="sd-mini"><b>{len(all_file_results)}개</b><span>검사한 파일</span></div>
              <div class="sd-mini"><b>{checklist_done}/{checklist_total}</b><span>체크리스트 완료</span></div>
              <div class="sd-mini"><b>{todo_preview_count}개</b><span>우선 수정 항목</span></div>
              <div class="sd-mini"><b>{market_hits}개</b><span>시장 참고 콘텐츠</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        todo_list = build_priority_todo(all_file_results)
        if todo_list:
            st.subheader("이것부터 고치세요")
            for i, todo in enumerate(todo_list, start=1):
                grade_label = "❌ 실패" if todo["grade"] == "fail" else "⚠️ 주의"
                css_class = "fail" if todo["grade"] == "fail" else "warn"
                st.markdown(
                    f"""
                    <div class="todo-row {css_class}">
                        <b>{i}. {grade_label} · {todo['item']}</b><br/>
                        {todo['msg']}<br/>
                        <small>영향받은 파일 {todo['affected_count']}개: {', '.join(todo['affected_files'][:5])}
                        {' 외' if len(todo['affected_files']) > 5 else ''}</small>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.success("자동 검사 기준으로 고칠 항목이 없어요!")

        # ---------- 7단계: PDF + 히스토리 ----------
        st.divider()
        st.header("7단계 · 리포트 내보내기 & 재검사 히스토리")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("📄 PDF 리포트 생성"):
                pdf_bytes = build_pdf_report(
                    all_file_results,
                    todo_list,
                    score,
                    checklist_status,
                    diagnosis_texts,
                )
                st.download_button(
                    "⬇️ PDF 다운로드",
                    data=pdf_bytes,
                    file_name="ogq_sticker_doctor_report.pdf",
                    mime="application/pdf",
                )

        with col_b:
            st.caption("저장하면 점수뿐 아니라 시장 비교, AI 문제 위치 표시, 적용된 검사 기준, 사용자 지정 기준 결과까지 함께 보관됩니다.")
            if st.button("💾 이번 결과를 히스토리에 저장"):
                record_id = _save_current_diagnosis_to_history(
                    current_user,
                    all_file_results,
                    selected_criteria,
                    custom_rules,
                    feelings,
                    user_tags,
                )
                if record_id:
                    st.success("내 계정의 진단 히스토리에 저장했어요. 상단의 '히스토리' 탭에서 언제든지 다시 볼 수 있습니다.")
                    st.rerun()
                else:
                    st.error("사용자 기록 저장에 실패했습니다.")

        # ---------- 제출 구성 요약 ----------
        st.divider()
        st.subheader("제출 구성 체크")
        st.caption("OGQ 공개 제작 가이드: 메인 1개 · 스티커 24개 · 탭 1개")
        need = {"메인 이미지": 1, "스티커 이미지": 24, "탭 이미지": 1}
        for name, required in need.items():
            have = type_counts[name]
            st.write(f"**{name}**  {have} / {required}")
            st.progress(min(have / required, 1.0))
    else:
        st.info("이미지를 올리면 OGQ 심사 기준에 맞는지 바로 검사합니다.")

    # ---------- 화면 최하단 카피라이트 ----------
    st.markdown(
    """
    <div style="text-align:center; margin:48px 0 16px; padding-top:18px; border-top:1px solid #e5e7eb; color:#98a2b3; font-size:0.82rem;">
        © 2026 OGQ Sticker Doctor. All rights reserved.
    </div>
    """,
    unsafe_allow_html=True,
    )
