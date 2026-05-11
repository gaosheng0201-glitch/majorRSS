import streamlit as st
import sys
import os
from dotenv import load_dotenv, set_key

# Ensure the root directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import get_session, create_db_and_tables
from db.models import Source, IntelReport, PipelineStatus, DailyBriefing, TrendAlert, TokenUsage
from sqlmodel import select
from ui.i18n import t, TRANSLATIONS

MAJOR_RSS_VERSION = "v1.0.0"

# Must be the first Streamlit command
st.set_page_config(page_title=f"MajorRSS Radar {MAJOR_RSS_VERSION}", page_icon="📡", layout="wide", initial_sidebar_state="expanded")

# --- Language Sniffer ---
if "lang" not in st.session_state:
    detected = "en"
    try:
        # Native backend language sniffing via HTTP headers (Streamlit 1.37+)
        # This completely avoids iframe sandbox SecurityErrors and page reloads.
        if hasattr(st, "context") and hasattr(st.context, "headers"):
            accept_lang = st.context.headers.get("Accept-Language", "en")
            if accept_lang:
                detected = accept_lang.split(',')[0][:2].lower()
    except Exception:
        pass
        
    if detected in TRANSLATIONS:
        st.session_state["lang"] = detected
    else:
        st.session_state["lang"] = "en"

# Custom CSS for Native Supabase-Style Sidebar
st.markdown("""
<style>
    /* Lock sidebar width to exactly 64px */
    [data-testid="stSidebar"] {
        min-width: 64px !important;
        max-width: 64px !important;
    }
    
    /* Hide the resizer handle to prevent dragging and breaking layout */
    [data-testid="stSidebarResizer"] {
        display: none !important;
    }
    
    /* Remove default sidebar horizontal padding for edge-to-edge component rendering */
    [data-testid="stSidebarUserContent"] {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        padding-top: 2rem !important;
        overflow-x: hidden !important;
    }
    
    /* Hide the text labels safely without breaking icons */
    span[data-testid="stPageLink-label"] {
        display: none !important;
    }
    
    /* Center the anchor links */
    [data-testid="stSidebarNavItems"] a {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        padding: 12px 0 !important;
        border-radius: 10px !important;
    }
    
    /* Ensure Material Icons are sized correctly */
    [data-testid="stSidebarNavItems"] .material-symbols-rounded {
        font-size: 24px !important;
        margin: 0 !important;
    }
    
    /* Hide the default collapse/expand controls */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

# Inject JS to add native HTML 'title' attributes for tooltips
import streamlit.components.v1 as components
components.html("""
<script>
    setTimeout(() => {
        const links = parent.document.querySelectorAll('[data-testid="stSidebarNavItems"] a');
        links.forEach(link => {
            const labelSpan = link.querySelector('span[data-testid="stPageLink-label"]');
            if (labelSpan) {
                link.title = labelSpan.textContent.trim();
            }
        });
    }, 1000);
</script>
""", height=0)

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path)

# Initialize Database
create_db_and_tables()

# -------------------------------------------------------------
# PAGE DEFINITIONS
# -------------------------------------------------------------

def page_dashboard():
    st.title(f":material/bar_chart: {t('dash_title')}")
    session = next(get_session())
    
    recent_alerts = session.exec(select(TrendAlert).order_by(TrendAlert.created_at.desc()).limit(3)).all()
    if recent_alerts:
        for alert in recent_alerts:
            st.error(f":material/warning: **{t('dash_alert')} {alert.entity_name}**\n\n{alert.alert_summary}\n\n*{t('dash_detected')} {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}*")
        st.divider()

    logs = session.exec(select(PipelineStatus).order_by(PipelineStatus.updated_at.desc()).limit(8)).all()
    with st.expander(f":material/terminal: {t('dash_logs')}", expanded=False):
        if logs:
            for log in logs:
                st.markdown(f"`[{log.updated_at.strftime('%H:%M:%S')}]` **{log.source_name}** - *{log.action_type}*: {log.detail}")
        else:
            st.caption(t('dash_no_logs'))

    st.divider()
    
    col1, col2 = st.columns([4, 1])
    with col1:
        st.subheader(t('dash_board'))
    with col2:
        if st.button(f":material/refresh: {t('dash_refresh')}", use_container_width=True):
            st.rerun()
            
    sources = session.exec(select(Source)).all()
    unique_sections = list(set([s.radar_section for s in sources if s.radar_section]))
    if not unique_sections:
        unique_sections = ["Frontier Outpost", "Geek Radar"]
    
    section_tabs = st.tabs(unique_sections)
    
    for i, section_name in enumerate(unique_sections):
        with section_tabs[i]:
            st.header(f":material/folder: {section_name}")
            
            reports = session.exec(
                select(IntelReport)
                .where(IntelReport.radar_section == section_name)
                .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
                .order_by(IntelReport.created_at.desc())
                .limit(15)
            ).all()
            
            if not reports:
                st.info(f"[{section_name}] {t('dash_no_intel')}")
            for report in reports:
                with st.expander(f"[{report.importance_score}★] {report.source_url[:80]}..."):
                    st.markdown(report.llm_summary)
                    st.caption(f"{t('dash_scraped_at')}: {report.created_at.strftime('%Y-%m-%d %H:%M:%S')} | Hash: {report.original_content_hash[:10]}...")

def page_briefing():
    st.title(f":material/article: {t('brief_title')}")
    st.markdown(t('brief_desc'))
    session = next(get_session())
    
    col_b1, col_b2 = st.columns([4, 1])
    with col_b2:
        if st.button(f":material/auto_awesome: {t('brief_generate')}", use_container_width=True):
            from llm.processor import generate_daily_briefing
            with st.spinner(t('brief_generating')):
                try:
                    res = generate_daily_briefing()
                    if "Not enough news" in res:
                        st.warning(f":material/warning: {t('brief_not_enough')}")
                    else:
                        st.success(f":material/celebration: {t('brief_success')}")
                        import time; time.sleep(1.5)
                        st.rerun()
                except Exception as e:
                    st.error(f"{t('brief_fail')} {e}")
    
    briefings = session.exec(select(DailyBriefing).order_by(DailyBriefing.created_at.desc()).limit(5)).all()
    if not briefings:
        st.info(t('brief_empty'))
    
    for b in briefings:
        with st.expander(f":material/calendar_month: {t('brief_date')}：{b.date_str}", expanded=(b == briefings[0])):
            st.markdown(b.content)

def page_billing():
    st.title(f":material/payments: {t('bill_title')}")
    st.markdown(t('bill_desc'))
    session = next(get_session())
    
    all_usages = session.exec(select(TokenUsage)).all()
    flash_tokens = sum(u.total_tokens for u in all_usages if "flash" in u.model_name)
    pro_tokens = sum(u.total_tokens for u in all_usages if "pro" in u.model_name)
    est_cost = (flash_tokens / 1000000) * 0.15 + (pro_tokens / 1000000) * 2.5
    
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        st.metric("Gemini 3 Flash Tokens", f"{flash_tokens:,}", t('bill_flash_desc'), delta_color="off")
    with col_b2:
        st.metric("Gemini 3.1 Pro Tokens", f"{pro_tokens:,}", t('bill_pro_desc'), delta_color="off")
    with col_b3:
        st.metric(t('bill_est_cost'), f"${est_cost:.4f}", t('bill_cost_desc'), delta_color="off")
        
    st.divider()
    st.subheader(f":material/receipt_long: {t('bill_recent')}")
    recent_usages = session.exec(select(TokenUsage).order_by(TokenUsage.created_at.desc()).limit(20)).all()
    if recent_usages:
        usage_data = [{t('bill_col_time'): u.created_at.strftime('%Y-%m-%d %H:%M:%S'), t('bill_col_action'): u.action_type, t('bill_col_model'): u.model_name, t('bill_col_prompt'): u.prompt_tokens, t('bill_col_comp'): u.completion_tokens, t('bill_col_total'): u.total_tokens} for u in recent_usages]
        st.dataframe(usage_data, use_container_width=True)
    else:
        st.info(t('bill_no_logs'))

def page_settings():
    st.title(f":material/settings: {t('set_title')}")
    session = next(get_session())
    
    # Language Selector
    lang_options = {"en": "English", "zh": "简体中文", "ko": "한국어", "ja": "日本語", "ru": "Русский"}
    current_lang = st.session_state.get("lang", "en")
    
    def on_lang_change():
        st.session_state["lang"] = st.session_state["lang_selector"]
    
    st.selectbox(
        t('set_lang'), 
        options=list(lang_options.keys()), 
        format_func=lambda x: lang_options[x], 
        index=list(lang_options.keys()).index(current_lang) if current_lang in lang_options else 0,
        key="lang_selector",
        on_change=on_lang_change
    )
    
    st.divider()
    
    st.header(f":material/key: {t('set_api')}")
    current_key = os.environ.get("GEMINI_API_KEY", "")
    new_key = st.text_input(t('set_api_ph'), value=current_key, type="password")
    if st.button(t('set_save_api')):
        if not os.path.exists(dotenv_path):
            open(dotenv_path, 'a').close()
        set_key(dotenv_path, "GEMINI_API_KEY", new_key)
        os.environ["GEMINI_API_KEY"] = new_key
        st.success(t('set_api_success'))
    
    st.divider()
    
    st.header(f":material/satellite_alt: {t('set_manage')}")
    
    with st.expander(f":material/add: {t('set_add')}", expanded=True):
        with st.form("add_source_form"):
            s_name = st.text_input(t('set_name'), placeholder="e.g. OpenAI Release Notes")
            s_url = st.text_input(t('set_url'), placeholder="https://...")
            s_tier = st.selectbox(t('set_tier'), [0, 1, 2, 3], format_func=lambda x: {0: t('set_tier_0'), 1: t('set_tier_1'), 2: t('set_tier_2'), 3: t('set_tier_3')}[x])
            s_section = st.text_input(t('set_section'), placeholder="e.g. Geek Radar")
            submit_source = st.form_submit_button(t('set_submit'))
            
            if submit_source and s_name and s_url and s_section:
                final_tier = s_tier
                final_url = s_url
                
                if s_tier == 0:
                    with st.spinner(t('set_sniffing')):
                        from scrapers.auto_detect import probe_url_for_tier
                        final_tier, final_url, probe_msg = probe_url_for_tier(s_url)
                        st.info(f"{t('set_report')} {probe_msg}")
                        import time; time.sleep(1)

                new_source = Source(name=s_name, url=final_url, tier=final_tier, radar_section=s_section)
                session.add(new_source)
                session.commit()
                st.success(f"{t('set_add_success')} {s_name} {t('set_to_section')} {s_section} (Tier {final_tier})")
                import time; time.sleep(1.5)
                st.rerun()

    st.subheader(t('set_current'))
    sources = session.exec(select(Source)).all()
    if sources:
        source_data = [{"ID": s.id, "Name": s.name, "URL": s.url, "Tier": s.tier, "Section": s.radar_section, "Active": s.is_active} for s in sources]
        st.dataframe(source_data, use_container_width=True)
        
        col_op1, col_op2 = st.columns([1, 1])
        with col_op1:
            del_id = st.number_input(t('set_del_id'), min_value=1, step=1)
            if st.button(f":material/close: {t('set_del_btn')}", type="secondary"):
                to_delete = session.get(Source, del_id)
                if to_delete:
                    session.delete(to_delete)
                    session.commit()
                    st.success(f"{t('set_del_success')} {del_id}")
                    st.rerun()
                else:
                    st.error(t('set_del_fail'))
        
        with col_op2:
            st.write("")
            st.write("")
            if st.button(f":material/bolt: {t('set_force')}", type="primary", use_container_width=True):
                with st.spinner(t('set_forcing')):
                    import worker
                    try:
                        worker.run_scraping_job()
                        worker.run_processing_job()
                        st.success(t('set_force_success'))
                    except Exception as e:
                        st.error(f"{t('set_force_fail')} {e}")
    else:
        st.info(t('set_no_sources'))
        
    st.divider()
    st.caption(f"MajorRSS Engine Version: **{MAJOR_RSS_VERSION}**")

# -------------------------------------------------------------
# NAVIGATION SETUP (Native SPA with CSS Icon-Only Override)
# -------------------------------------------------------------

def dashboard_page():
    page_dashboard()
def briefing_page():
    page_briefing()
def billing_page():
    page_billing()
def settings_page():
    page_settings()

pg = st.navigation([
    st.Page(dashboard_page, title=t('nav_dashboard'), icon=":material/dashboard:"),
    st.Page(briefing_page, title=t('nav_briefing'), icon=":material/article:"),
    st.Page(billing_page, title=t('nav_billing'), icon=":material/payments:"),
    st.Page(settings_page, title=t('nav_settings'), icon=":material/settings:"),
])

pg.run()
