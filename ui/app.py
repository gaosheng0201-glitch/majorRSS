import streamlit as st
import sys
import os
from dotenv import load_dotenv, set_key

# Ensure the root directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import get_session, create_db_and_tables
from db.models import Tracker, IntelReport, PipelineStatus, DailyBriefing, TrendAlert, TokenUsage
from sqlmodel import select
from ui.i18n import t, TRANSLATIONS

MAJOR_RSS_VERSION = "v1.2.0"

# Must be the first Streamlit command
st.set_page_config(page_title=f"MajorRSS Radar {MAJOR_RSS_VERSION}", page_icon=":material/satellite_alt: ", layout="wide", initial_sidebar_state="expanded")

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
    session = get_session()
    
    recent_alerts = session.exec(select(TrendAlert).order_by(TrendAlert.created_at.desc()).limit(3)).all()
    if recent_alerts:
        for alert in recent_alerts:
            st.error(f":material/warning: **{t('dash_alert')} {alert.entity_name}**\n\n{alert.alert_summary}\n\n*{t('dash_detected')} {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}*")
        st.divider()

    logs = session.exec(select(PipelineStatus).order_by(PipelineStatus.updated_at.desc()).limit(8)).all()
    with st.expander(f":material/terminal: {t('dash_logs')}", expanded=False):
        if logs:
            for log in logs:
                st.markdown(f"`[{log.updated_at.strftime('%H:%M:%S')}]` **{log.tracker_name}** - *{log.action_type}*: {log.detail}")
        else:
            st.caption(t('dash_no_logs'))

    # Added Pending AI Processing Metric
    from db.models import RawArticle
    from sqlmodel import func
    pending_count = session.exec(select(func.count()).where(RawArticle.processed == False)).one()
    st.metric(t('dashboard_pending_ai'), pending_count)

    st.divider()
    
    col1, col2 = st.columns([4, 1])
    with col1:
        st.subheader(t('dash_board'))
    with col2:
        if st.button(f":material/refresh: {t('dash_refresh')}", use_container_width=True):
            st.rerun()
            
    trackers = session.exec(select(Tracker)).all()
    unique_sections = list(set([t.radar_section for t in trackers if t.radar_section]))
    if not unique_sections:
        unique_sections = ["Frontier Outpost", "Geek Radar"]
    
    section_tabs = st.tabs(unique_sections)
    
    for i, section_name in enumerate(unique_sections):
        with section_tabs[i]:
            reports = session.exec(
                select(IntelReport)
                .where(IntelReport.radar_section == section_name)
                .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
                .order_by(IntelReport.event_timestamp.desc(), IntelReport.created_at.desc())
                .limit(15)
            ).all()
            
            if not reports:
                st.info(f"[{section_name}] {t('dash_no_intel')}")
            for report in reports:
                time_str = report.event_timestamp if report.event_timestamp else report.created_at.strftime('%Y-%m-%d %H:%M:%S')
                raw_article = session.get(RawArticle, report.raw_article_id)
                title = raw_article.title if raw_article else "Untitled Intelligence"
                
                with st.container(border=True):
                    st.markdown(f"#### {title}")
                    st.caption(f"⭐ **{report.importance_score}★** · 🕒 {t('dash_published_at')}: {time_str}")
                    
                    summary_text = report.llm_summary
                    evidence_text = ""
                    if "**:material/menu_book: Source Evidence:**" in summary_text:
                        parts = summary_text.split("**:material/menu_book: Source Evidence:**")
                        summary_text = parts[0].replace("---\n", "").strip()
                        evidence_text = parts[1].strip()
                        
                    st.markdown(summary_text)
                    
                    with st.expander("来源与详情 (Sources & Details)"):
                        if evidence_text:
                            st.markdown("**:material/menu_book: 融合来源追踪 (Fused Sources):**")
                            st.markdown(evidence_text)
                        st.markdown(f"**原始 URL**: {report.source_url}")
                        st.caption(f"{t('dash_scraped_at')}: {report.created_at.strftime('%Y-%m-%d %H:%M:%S')} | Hash: {report.original_content_hash[:15]}")

def page_briefing():
    st.title(f":material/article: {t('brief_title')}")
    st.markdown(t('brief_desc'))
    session = get_session()
    
    trackers = session.exec(select(Tracker)).all()
    all_sections = list(set([t.radar_section for t in trackers if t.radar_section]))
    selected_sections = st.multiselect(t('brief_select_sections'), all_sections, default=[])
    
    col_b1, col_b2 = st.columns([4, 1])
    with col_b2:
        if st.button(f":material/auto_awesome: {t('brief_generate')}", use_container_width=True):
            from llm.processor import generate_daily_briefing
            with st.spinner(t('brief_generating')):
                try:
                    res = generate_daily_briefing(target_sections=selected_sections if selected_sections else None)
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
        with st.expander(f":material/calendar_month: {t('brief_date')}：{b.date_str} [{b.section_name}]", expanded=(b == briefings[0])):
            st.markdown(b.content)

def page_billing():
    st.title(f":material/payments: {t('bill_title')}")
    st.markdown(t('bill_desc'))
    session = get_session()
    
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
    
    # --- Daily Consumption Bar Chart ---
    st.subheader(f":material/bar_chart: {t('bill_daily_trend')}")
    import pandas as pd
    if all_usages:
        df = pd.DataFrame([{"date": u.created_at.strftime('%Y-%m-%d'), "tokens": u.total_tokens} for u in all_usages])
        daily_tokens = df.groupby("date").sum().reset_index()
        st.bar_chart(daily_tokens.set_index("date"))
    else:
        st.info(t('bill_daily_empty'))
        
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
    session = get_session()
    
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
    
    st.header(f":material/key: {t('set_auth_title')}")
    st.markdown(t('set_auth_desc'))
    st.info("💡 **架构提示**: 社交媒体(B站/推特/微博等)的主页追踪现已全面由底层 RSSHub 隐形代理，**免登录永不封号**。此处的强制授权仅为情报溯源系统 (Fact-Checker) 提供底层的单篇深度穿透能力。")
    
    from scrapers.auth_helper import AUTH_PLATFORMS, interactive_login, check_cookie_health
    import time
    
    cols = st.columns(4)
    for idx, (platform_key, platform_info) in enumerate(AUTH_PLATFORMS.items()):
        cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", platform_info["cookie_file"])
        has_cookie = os.path.exists(cookie_path)
        is_healthy = check_cookie_health(platform_key, cookie_path) if has_cookie else False
        
        with cols[idx % 4]:
            with st.container(border=True):
                st.markdown(f"**{platform_info['name']}**")
                if has_cookie and is_healthy:
                    mtime = os.path.getmtime(cookie_path)
                    st.caption(f":material/check_circle: {t('set_auth_status_ok')}\n({time.strftime('%m-%d %H:%M', time.localtime(mtime))})")
                    btn_text = t('set_auth_relogin')
                    btn_type = "secondary"
                elif has_cookie and not is_healthy:
                    mtime = os.path.getmtime(cookie_path)
                    st.caption(f":material/warning: {t('set_auth_status_expired', '凭证已失效')}\n({time.strftime('%m-%d %H:%M', time.localtime(mtime))})")
                    btn_text = t('set_auth_relogin')
                    btn_type = "primary"
                else:
                    st.caption(f":material/cancel: {t('set_auth_status_none')}")
                    btn_text = t('set_auth_login')
                    btn_type = "primary"
                
                if st.button(btn_text, key=f"auth_btn_{platform_key}", type=btn_type, use_container_width=True):
                    with st.spinner(f"{t('set_auth_waiting')} {platform_info['name']} ..."):
                        success, msg = interactive_login(platform_key)
                        if success:
                            st.success(msg)
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error(msg)
    
    st.divider()
    st.caption(f"MajorRSS Engine Version: **{MAJOR_RSS_VERSION}**")

def page_trackers():
    st.title(f":material/satellite_alt: {t('nav_trackers')}")
    session = get_session()
    
    with st.expander(f":material/add: {t('set_add_tracker')}", expanded=True):
        with st.form("add_tracker_form"):
            t_name = st.text_input(f"{t('set_tracker_name')} *", placeholder=t('set_tracker_name_ph'))
            t_section = st.text_input(f"{t('set_section')} *", placeholder="e.g. Geek Radar")
            
            # --- HYBRID Mixed Target Panel ---
            col_t1, col_t2, col_t3 = st.columns(3)
            with col_t1:
                t_urls = st.text_area(t('set_tracker_urls'), placeholder=t('set_tracker_urls_ph'), height=100)
            with col_t2:
                t_keywords = st.text_area(t('set_tracker_keywords'), placeholder=t('set_tracker_keywords_ph'), height=100)
            with col_t3:
                t_accounts = st.text_area(t('set_tracker_accounts'), placeholder=t('set_tracker_accounts_ph'), height=100)
                
            col_o1, col_o2, col_o3 = st.columns(3)
            with col_o1:
                t_use_osint = st.checkbox(t('set_tracker_use_osint'), value=True)
            with col_o2:
                t_max_days = st.number_input(t('set_tracker_max_days'), min_value=0, value=7, help=t('set_tracker_max_days_help'))
            with col_o3:
                t_interval = st.number_input(t('set_tracker_interval'), min_value=1, value=30, help=t('set_tracker_interval_help'))
            # ---------------------------------
            
            with st.expander(t('set_tracker_adv')):
                t_prompt = st.text_area(t('set_tracker_prompt'), placeholder=t('set_tracker_prompt_ph'))
                t_cookie = st.text_input(t('set_tracker_cookie'), placeholder=t('set_tracker_cookie_ph'), type="password")
            
            submit_tracker = st.form_submit_button(t('set_tracker_deploy'))
            
            if submit_tracker:
                if not t_name:
                    st.error(":material/warning: 请填写探测器名称 (Tracker Name is required).")
                elif not t_section:
                    st.error(":material/warning: 请填写所属板块 (Section is required).")
                else:
                    import json
                    from scrapers.url_normalizer import auto_route
                    urls_list = [auto_route(u.strip()) for u in t_urls.split('\n') if u.strip()]
                    keywords_list = [k.strip() for k in t_keywords.split('\n') if k.strip()]
                    accounts_list = [a.strip().replace('@', '') for a in t_accounts.split('\n') if a.strip()]
                    
                    if not (urls_list or keywords_list or accounts_list):
                        st.error("⚠️ 请至少提供一种探测目标 (Please provide at least one URL, Keyword, or Account).")
                    else:
                        hybrid_target = {
                            "urls": urls_list,
                            "keywords": keywords_list,
                            "accounts": accounts_list,
                            "use_default_osint": t_use_osint,
                            "max_days": t_max_days
                        }
                        new_tracker = Tracker(
                            name=t_name,
                            tracker_type="HYBRID",
                            target=json.dumps(hybrid_target),
                            tier=1 if urls_list and not (keywords_list or accounts_list) else 0,
                            radar_section=t_section,
                            fetch_interval_minutes=t_interval,
                            prompt_override=t_prompt if t_prompt else None,
                            cookie_string=t_cookie if t_cookie else None
                        )
                        session.add(new_tracker)
                        session.commit()
                        st.success(f"{t('set_tracker_deploy_success')} {t_name}")
                        import time; time.sleep(1.5)
                        st.rerun()

    st.subheader(t('set_tracker_active'))
    trackers = session.exec(select(Tracker)).all()
    if trackers:
        def format_target(target_json):
            try:
                import json
                d = json.loads(target_json)
                parts = []
                if d.get("urls"): parts.append(f"{len(d['urls'])} URLs")
                if d.get("keywords"): parts.append(f"{len(d['keywords'])} KWs")
                if d.get("accounts"): parts.append(f"{len(d['accounts'])} Accs")
                return ", ".join(parts) if parts else "Empty"
            except:
                return target_json[:30] + "..."
                
        def get_pending_count(tracker_id):
            from db.models import RawArticle
            from sqlmodel import func
            return session.exec(select(func.count()).where(RawArticle.tracker_id == tracker_id, RawArticle.processed == False)).one()
            
        import pandas as pd
        tracker_data = [{"Select": False, "ID": t.id, "Name": t.name, "Targets": format_target(t.target), "Interval": t.fetch_interval_minutes, "Pending": get_pending_count(t.id), "Section": t.radar_section, "Active": t.is_active} for t in trackers]
        df_trackers = pd.DataFrame(tracker_data)
        edited_trackers = st.data_editor(
            df_trackers, 
            hide_index=True, 
            use_container_width=True, 
            column_config={
                "Select": st.column_config.CheckboxColumn(required=True),
                "ID": st.column_config.NumberColumn(disabled=True),
                "Targets": st.column_config.TextColumn(disabled=True),
                "Pending": st.column_config.NumberColumn(disabled=True)
            }
        )
        
        selected_tracker_ids = edited_trackers[edited_trackers["Select"] == True]["ID"].tolist()
        
        col_op1, col_op2, col_op3, col_op4 = st.columns([1, 1, 1, 1])
        with col_op1:
            st.write("")
            if st.button("💾 保存修改", type="primary", use_container_width=True):
                changes = 0
                for index, row in edited_trackers.iterrows():
                    db_t = session.get(Tracker, row["ID"])
                    if db_t:
                        # Check if anything changed
                        if (db_t.name != row["Name"] or 
                            db_t.fetch_interval_minutes != row["Interval"] or 
                            db_t.radar_section != row["Section"] or 
                            db_t.is_active != row["Active"]):
                            
                            db_t.name = row["Name"]
                            db_t.fetch_interval_minutes = int(row["Interval"])
                            db_t.radar_section = row["Section"]
                            db_t.is_active = bool(row["Active"])
                            session.add(db_t)
                            changes += 1
                if changes > 0:
                    session.commit()
                    st.success(f"已成功保存 {changes} 个修改的追踪器。")
                    import time; time.sleep(1.0)
                    st.rerun()
                else:
                    st.info("没有检测到任何修改。")

        with col_op2:
            st.write("") # Alignment
            if st.button(t('set_tracker_del_btn'), type="secondary", use_container_width=True):
                if selected_tracker_ids:
                    for tid in selected_tracker_ids:
                        to_delete = session.get(Tracker, tid)
                        if to_delete:
                            session.delete(to_delete)
                    session.commit()
                    st.success(f"Deleted {len(selected_tracker_ids)} trackers.")
                    import time; time.sleep(1.0)
                    st.rerun()
                else:
                    st.warning("Please check at least one tracker to delete.")
        
        with col_op3:
            st.write("")
            if st.button("单独执行选中项", type="secondary", use_container_width=True):
                if selected_tracker_ids:
                    with st.spinner("Submitting tasks for selected trackers..."):
                        from db.models import TaskRequest
                        try:
                            for tid in selected_tracker_ids:
                                req1 = TaskRequest(job_type="SCRAPE", target_type="TRACKER", target_id=str(tid))
                                req2 = TaskRequest(job_type="PROCESS", target_type="TRACKER", target_id=str(tid))
                                session.add(req1)
                                session.add(req2)
                            session.commit()
                            st.success(f"Successfully queued {len(selected_tracker_ids) * 2} tasks.")
                            import time; time.sleep(1.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Queueing failed: {e}")
                else:
                    st.warning("Please check at least one tracker to run.")

        with col_op4:
            st.write("")
            if st.button(t('set_force'), type="primary", use_container_width=True):
                with st.spinner(t('set_forcing')):
                    from db.models import TaskRequest
                    try:
                        active_trackers = session.exec(select(Tracker).where(Tracker.is_active == True)).all()
                        for tk in active_trackers:
                            session.add(TaskRequest(job_type="SCRAPE", target_type="TRACKER", target_id=str(tk.id)))
                            session.add(TaskRequest(job_type="PROCESS", target_type="TRACKER", target_id=str(tk.id)))
                        session.commit()
                        st.success(t('set_force_success'))
                    except Exception as e:
                        st.error(f"{t('set_force_fail')} {e}")
                        
        st.divider()
        st.subheader(f":material/inbox: {t('manage_queue')}")
        from db.models import RawArticle
        import pandas as pd
        import urllib.parse
        import json
        import hashlib
        
        q_trackers = {t.id: f"[{t.id}] {t.name}" for t in trackers if get_pending_count(t.id) > 0}
        if q_trackers:
            q_sel = st.selectbox("Select Tracker to Manage Queue", options=list(q_trackers.keys()), format_func=lambda x: q_trackers[x])
            if q_sel:
                raws = session.exec(select(RawArticle).where(RawArticle.tracker_id == q_sel, RawArticle.processed == False).order_by(RawArticle.created_at.desc())).all()
                if raws:
                    df_raw = pd.DataFrame([{"Select": False, "ID": r.id, "Title": r.title, "URL": r.url, "Date": r.published_at or r.created_at} for r in raws])
                    edited_df = st.data_editor(df_raw, hide_index=True, use_container_width=True, column_config={
                        "Select": st.column_config.CheckboxColumn(required=True),
                        "URL": st.column_config.LinkColumn("Source Link", display_text="Open Original")
                    })
                    
                    selected_ids = edited_df[edited_df["Select"] == True]["ID"].tolist()
                    
                    col_q1, col_q2 = st.columns(2)
                    with col_q1:
                        if st.button(t('discard_selected'), type="secondary", use_container_width=True) and selected_ids:
                            for rid in selected_ids:
                                r = session.get(RawArticle, rid)
                                if r:
                                    r.processed = True
                                    session.add(r)
                            session.commit()
                            st.success(f"Discarded {len(selected_ids)} articles.")
                            import time; time.sleep(1.0)
                            st.rerun()
                    with col_q2:
                        if st.button(t('fuse_selected'), type="primary", use_container_width=True) and selected_ids:
                            bundled_text = f"=== FORCED MANUAL FUSION ===\n\n"
                            tracker_obj = session.get(Tracker, q_sel)
                            for idx, rid in enumerate(selected_ids):
                                r = session.get(RawArticle, rid)
                                if r:
                                    bundled_text += f"Source {idx+1}: {r.url}\nTitle: {r.title}\nContent:\n{r.content}\n\n"
                                    r.processed = True
                                    session.add(r)
                            
                            from llm.processor import process_article
                            with st.spinner("Fusing selected..."):
                                result = process_article(bundled_text, tracker_obj.radar_section, prompt_override=tracker_obj.prompt_override, tracker_name=tracker_obj.name)
                                source_links = "\n".join([f"- [{session.get(RawArticle, rid).title}]({session.get(RawArticle, rid).url})" for rid in selected_ids if session.get(RawArticle, rid)])
                                final_summary = f"{result.llm_summary}\n\n---\n**:material/menu_book: Source Evidence:**\n{source_links}"
                                
                                report = IntelReport(
                                    raw_article_id=selected_ids[0],
                                    source_url=f"Manually fused from {len(selected_ids)} sources",
                                    validity_category=result.validity_category,
                                    radar_section=tracker_obj.radar_section,
                                    llm_summary=final_summary,
                                    importance_score=result.importance_score,
                                    original_content_hash=hashlib.sha256(bundled_text.encode('utf-8')).hexdigest(),
                                    key_entities=json.dumps(result.key_entities),
                                    event_timestamp=result.event_timestamp
                                )
                                session.add(report)
                                session.commit()
                                st.success("Fusion complete! Check the Dashboard.")
                                import time; time.sleep(1.5)
                                st.rerun()
        else:
            st.info("No pending queues. All caught up!")
            
    else:
        st.info(t('set_tracker_no'))
        

# -------------------------------------------------------------
# MONITORS & SUBSCRIPTIONS PAGE
# -------------------------------------------------------------

@st.dialog(t('monitors_dialog_title') if 'monitors_dialog_title' in t.__globals__.get('LANG_DICT', {}).get(st.session_state.lang, {}) else "Update Details", width="large")
def show_update_dialog(update_id: int):
    session = get_session()
    from db.models import SubscriptionUpdate
    update = session.get(SubscriptionUpdate, update_id)
    if not update:
        return
        
    st.markdown(f"### {t('monitors_diff_title')}")
    st.code(update.diff_text, language="diff")
    
    if update.llm_summary:
        st.info(f"**{t('monitors_ai_summary_title')}**\n\n{update.llm_summary}")
    else:
        if st.button(t('monitors_ai_summarize'), type="primary"):
            with st.spinner(t('monitors_summarizing')):
                from llm.processor import summarize_diff
                try:
                    summary = summarize_diff(update.diff_text)
                    update.llm_summary = summary
                    session.add(update)
                    session.commit()
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
                    
    if st.button("Mark as Read"):
        update.is_read = True
        session.add(update)
        session.commit()
        st.rerun()

def page_monitors():
    st.title(t('monitors_title'))
    st.markdown(t('monitors_desc'))
    
    session = get_session()
    
    with st.expander(t('monitors_add'), expanded=True):
        col1, col2, col3, col4 = st.columns([2, 3, 1, 1])
        with col1:
            new_name = st.text_input(t('monitors_add_name'))
        with col2:
            new_url = st.text_input(t('monitors_add_url'))
        with col3:
            new_interval = st.number_input(t('monitors_add_interval'), min_value=1, value=60, step=10)
        with col4:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(t('monitors_add_btn'), type="primary", use_container_width=True):
                if new_name and new_url:
                    from db.models import Subscription
                    from scrapers.url_normalizer import auto_route
                    sub = Subscription(name=new_name, target_url=auto_route(new_url), fetch_interval_minutes=new_interval)
                    session.add(sub)
                    session.commit()
                    st.success(f"{t('monitors_add_success')} {new_name}")
                    import time; time.sleep(1)
                    st.rerun()
                    
    st.header(t('monitors_feed'))
    from db.models import Subscription, SubscriptionUpdate
    subs = session.exec(select(Subscription).where(Subscription.is_active == True).order_by(Subscription.created_at.desc())).all()
    
    if not subs:
        st.info(t('monitors_no_feed'))
    else:
        cols = st.columns(3)
        for idx, sub in enumerate(subs):
            latest_update = session.exec(select(SubscriptionUpdate).where(SubscriptionUpdate.subscription_id == sub.id).order_by(SubscriptionUpdate.created_at.desc())).first()
            has_update = latest_update and not latest_update.is_read
            
            with cols[idx % 3]:
                container = st.container(border=True)
                container.markdown(f"### {sub.name}")
                container.caption(f"{sub.target_url[:40]}...")
                
                if has_update:
                    container.error(f"🔴 {sub.last_status}")
                else:
                    container.success(f"🟢 {sub.last_status}")
                    
                checked_time = sub.last_scraped_at.strftime('%Y-%m-%d %H:%M') if sub.last_scraped_at else "Never"
                container.caption(f"{t('monitors_last_check')} {checked_time}")
                container.caption(t('monitors_interval_display').format(sub.fetch_interval_minutes))
                
                # Bottom action row
                act_col1, act_col2 = container.columns([3, 1])
                with act_col1:
                    if has_update:
                        if st.button(t('monitors_view_update'), key=f"btn_update_{sub.id}", type="primary", use_container_width=True):
                            show_update_dialog(latest_update.id)
                with act_col2:
                    with st.popover("⚙️"):
                        edit_int = st.number_input("频率(分钟)", min_value=1, value=sub.fetch_interval_minutes, key=f"edit_int_{sub.id}", step=10)
                        if st.button("💾 保存", key=f"save_int_{sub.id}", use_container_width=True):
                            sub.fetch_interval_minutes = edit_int
                            session.add(sub)
                            session.commit()
                            st.rerun()
                        if st.button("🗑️ 删除", key=f"del_{sub.id}", use_container_width=True):
                            sub.is_active = False
                            session.add(sub)
                            session.commit()
                            st.rerun()

# -------------------------------------------------------------
# NAVIGATION SETUP (Native SPA with CSS Icon-Only Override)
# -------------------------------------------------------------

def dashboard_page():
    page_dashboard()
def briefing_page():
    page_briefing()
def billing_page():
    page_billing()
def trackers_page():
    page_trackers()
def monitors_page():
    page_monitors()
def settings_page():
    page_settings()


def page_factcheck():
    st.header(t("factcheck_title"))
    st.markdown(t("factcheck_desc"))
    
    query = st.text_area(t("factcheck_input"), height=100)
    
    if st.button(t("factcheck_btn"), type="primary"):
        if not query:
            st.warning("Please enter a query.")
            return
            
        st.divider()
        col1, col2 = st.columns(2)
        
        native_res = ""
        funnel_res = ""
        
        with col1:
            st.subheader(t("factcheck_native_title"))
            with st.spinner("Calling Google Grounding..."):
                try:
                    from llm.investigator import run_native_grounding
                    native_res = run_native_grounding(query)
                    st.markdown(native_res)
                except Exception as e:
                    native_res = f"Error: {e}"
                    st.error(native_res)
                
        with col2:
            st.subheader(t("factcheck_funnel_title"))
            with st.status("Agent Pipeline Running...", expanded=True) as status:
                def cb(msg):
                    st.write(msg)
                try:
                    from llm.investigator import run_major_funnel
                    funnel_res = run_major_funnel(query, status_callback=cb)
                    status.update(label="Agent Pipeline Completed!", state="complete", expanded=False)
                except Exception as e:
                    funnel_res = f"Error: {e}"
                    status.update(label="Agent Pipeline Failed!", state="error", expanded=False)
            st.markdown(funnel_res)
            
        # Save to DB
        from db.database import get_session
        from db.models import InvestigationRecord
        with get_session() as session:
            record = InvestigationRecord(
                query=query,
                native_result=native_res,
                funnel_result=funnel_res
            )
            session.add(record)
            session.commit()
            st.success("Results saved to Archives.")

    st.divider()
    st.subheader(t("factcheck_history"))
    from db.database import get_session
    from db.models import InvestigationRecord
    from sqlmodel import select
    with get_session() as session:
        records = session.exec(select(InvestigationRecord).order_by(InvestigationRecord.created_at.desc())).all()
        if not records:
            st.info("No archives yet.")
        else:
            for r in records:
                with st.expander(f"[{r.created_at.strftime('%Y-%m-%d %H:%M')}] {r.query[:50]}..."):
                    st.write(f"**Query:** {r.query}")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**Native:**\n{r.native_result}")
                    with col_b:
                        st.markdown(f"**Funnel:**\n{r.funnel_result}")
                    
                    if st.button(t("factcheck_destroy"), key=f"del_inv_{r.id}"):
                        session.delete(r)
                        session.commit()
                        st.success(t("factcheck_destroyed"))
                        st.rerun()

def factcheck_page():
    page_factcheck()


pg = st.navigation([
    st.Page(dashboard_page, title=t('nav_dashboard'), icon=":material/dashboard:"),
    st.Page(factcheck_page, title=t('nav_factcheck'), icon=":material/policy:"),

    st.Page(briefing_page, title=t('nav_briefing'), icon=":material/article:"),
    st.Page(billing_page, title=t('nav_billing'), icon=":material/payments:"),
    st.Page(trackers_page, title=t('nav_trackers'), icon=":material/satellite_alt:"),
    st.Page(monitors_page, title=t('nav_monitors'), icon=":material/rss_feed:"),
    st.Page(settings_page, title=t('nav_settings'), icon=":material/settings:"),
])

pg.run()
