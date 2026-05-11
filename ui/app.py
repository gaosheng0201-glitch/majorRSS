import streamlit as st
import sys
import os
from dotenv import load_dotenv, set_key

# Ensure the root directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import get_session, create_db_and_tables
from db.models import Source, IntelReport, PipelineStatus, DailyBriefing, TrendAlert, TokenUsage
from sqlmodel import select

# Must be the first Streamlit command
st.set_page_config(page_title="MajorRSS Radar", page_icon="📡", layout="wide", initial_sidebar_state="expanded")

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path)

# Initialize Database
create_db_and_tables()

# -------------------------------------------------------------
# PAGE DEFINITIONS
# -------------------------------------------------------------

def page_dashboard():
    st.title("📊 情报大屏 (Dashboard)")
    session = next(get_session())
    
    # 1. Trend Alerts (Top priority)
    recent_alerts = session.exec(select(TrendAlert).order_by(TrendAlert.created_at.desc()).limit(3)).all()
    if recent_alerts:
        for alert in recent_alerts:
            st.error(f"🚨 **异动预警 (Trend Alert) | 高频实体爆发: {alert.entity_name}**\n\n{alert.alert_summary}\n\n*检测时间: {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}*")
        st.divider()

    # 2. Pipeline Status Tracker
    logs = session.exec(select(PipelineStatus).order_by(PipelineStatus.updated_at.desc()).limit(8)).all()
    with st.expander("⚙️ 后台引擎运行日志 (Engine Live Log)", expanded=False):
        if logs:
            for log in logs:
                st.markdown(f"`[{log.updated_at.strftime('%H:%M:%S')}]` **{log.source_name}** - *{log.action_type}*: {log.detail}")
        else:
            st.caption("暂无运行日志 (No recent activity).")

    st.divider()
    
    # 3. Main Dashboard Content
    col1, col2 = st.columns([4, 1])
    with col1:
        st.subheader("动态情报看板")
    with col2:
        if st.button("🔄 刷新大屏", use_container_width=True):
            st.rerun()
            
    sources = session.exec(select(Source)).all()
    unique_sections = list(set([s.radar_section for s in sources if s.radar_section]))
    if not unique_sections:
        unique_sections = ["Frontier Outpost", "Geek Radar"]
    
    section_tabs = st.tabs(unique_sections)
    
    for i, section_name in enumerate(unique_sections):
        with section_tabs[i]:
            st.header(f"🗂️ {section_name}")
            
            reports = session.exec(
                select(IntelReport)
                .where(IntelReport.radar_section == section_name)
                .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
                .order_by(IntelReport.created_at.desc())
                .limit(15)
            ).all()
            
            if not reports:
                st.info(f"[{section_name}] 尚无高价值情报 (No intelligence available yet).")
            for report in reports:
                with st.expander(f"[{report.importance_score}⭐] {report.source_url[:80]}..."):
                    st.markdown(report.llm_summary)
                    st.caption(f"Scraped at: {report.created_at.strftime('%Y-%m-%d %H:%M:%S')} | Hash: {report.original_content_hash[:10]}...")

def page_briefing():
    st.title("📻 每日深度简报 (Daily Briefing)")
    st.markdown("基于 Gemini 超大上下文提炼的全局资讯串联。")
    session = next(get_session())
    
    col_b1, col_b2 = st.columns([4, 1])
    with col_b2:
        if st.button("✨ 立即生成简报", use_container_width=True):
            from llm.processor import generate_daily_briefing
            with st.spinner("Gemini 正在通读过去 24 小时的情报并撰写简报..."):
                try:
                    res = generate_daily_briefing()
                    if "Not enough news" in res:
                        st.warning("⚠️ 过去 24 小时内有效情报不足，无法生成。")
                    else:
                        st.success("🎉 简报生成成功！")
                        import time; time.sleep(1.5)
                        st.rerun()
                except Exception as e:
                    st.error(f"生成失败: {e}")
    
    briefings = session.exec(select(DailyBriefing).order_by(DailyBriefing.created_at.desc()).limit(5)).all()
    if not briefings:
        st.info("尚无生成的每日简报。可以通过命令行或 Worker 自动生成。")
    
    for b in briefings:
        with st.expander(f"📅 简报日期：{b.date_str}", expanded=(b == briefings[0])):
            st.markdown(b.content)

def page_billing():
    st.title("💳 AI 计费与消耗审计 (Billing)")
    st.markdown("本地追踪每次大模型调用的确切 Token 数量，杜绝未知账单。")
    session = next(get_session())
    
    all_usages = session.exec(select(TokenUsage)).all()
    flash_tokens = sum(u.total_tokens for u in all_usages if "flash" in u.model_name)
    pro_tokens = sum(u.total_tokens for u in all_usages if "pro" in u.model_name)
    est_cost = (flash_tokens / 1000000) * 0.15 + (pro_tokens / 1000000) * 2.5
    
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        st.metric("⚡ Gemini 3 Flash Tokens", f"{flash_tokens:,}", "日常网页分析高频调用", delta_color="off")
    with col_b2:
        st.metric("🧠 Gemini 3.1 Pro Tokens", f"{pro_tokens:,}", "深度简报生成低频调用", delta_color="off")
    with col_b3:
        st.metric("💰 预估总成本 (Est. Cost)", f"${est_cost:.4f}", "基于官方参考定价", delta_color="off")
        
    st.divider()
    st.subheader("📝 近期消耗明细 (Recent Transactions)")
    recent_usages = session.exec(select(TokenUsage).order_by(TokenUsage.created_at.desc()).limit(20)).all()
    if recent_usages:
        usage_data = [{"时间": u.created_at.strftime('%Y-%m-%d %H:%M:%S'), "动作": u.action_type, "模型": u.model_name, "Prompt": u.prompt_tokens, "Completion": u.completion_tokens, "总计": u.total_tokens} for u in recent_usages]
        st.dataframe(usage_data, use_container_width=True)
    else:
        st.info("尚无大模型调用记录。")

def page_settings():
    st.title("⚙️ 设置与数据源 (Settings & Sources)")
    session = next(get_session())
    
    st.header("🔑 API 密钥配置 (API Configuration)")
    current_key = os.environ.get("GEMINI_API_KEY", "")
    new_key = st.text_input("Gemini API Key (用于启动 AI 审查与去噪)", value=current_key, type="password")
    if st.button("保存密钥 (Save API Key)"):
        if not os.path.exists(dotenv_path):
            open(dotenv_path, 'a').close()
        set_key(dotenv_path, "GEMINI_API_KEY", new_key)
        os.environ["GEMINI_API_KEY"] = new_key
        st.success("API Key 已保存至 .env 文件中。后台 Worker 进程将自动读取该配置。")
    
    st.divider()
    
    st.header("📡 信息源管理 (Manage Sources)")
    
    with st.expander("➕ 添加新信息源 (Add New Source)", expanded=True):
        with st.form("add_source_form"):
            s_name = st.text_input("名称 (Name)", placeholder="e.g. OpenAI Release Notes")
            s_url = st.text_input("目标网址 (URL)", placeholder="https://...")
            s_tier = st.selectbox("抓取等级 (Scraper Tier)", [0, 1, 2, 3], format_func=lambda x: {0: "0 - 🤖 智能探测最佳路径 (Auto-Detect)", 1: "1 - 基础直连 (Basic RSS)", 2: "2 - 替代前端 (Mirror/API)", 3: "3 - 智能体无头浏览器 (Agentic Scraper)"}[x])
            s_section = st.text_input("所属自定义板块 (Radar Section)", placeholder="例如：前沿哨所, 量化交易, AI绘画")
            submit_source = st.form_submit_button("添加源 (Add Source)")
            
            if submit_source and s_name and s_url and s_section:
                final_tier = s_tier
                final_url = s_url
                
                if s_tier == 0:
                    with st.spinner("🤖 正在嗅探目标网站特征，为您寻找最优抓取路径..."):
                        from scrapers.auto_detect import probe_url_for_tier
                        final_tier, final_url, probe_msg = probe_url_for_tier(s_url)
                        st.info(f"探测报告：{probe_msg}")
                        import time; time.sleep(1)

                new_source = Source(name=s_name, url=final_url, tier=final_tier, radar_section=s_section)
                session.add(new_source)
                session.commit()
                st.success(f"已成功添加源: {s_name} 到板块 {s_section} (应用等级: Tier {final_tier})")
                import time; time.sleep(1.5)
                st.rerun()

    st.subheader("当前活跃信息源列表 (Current Sources)")
    sources = session.exec(select(Source)).all()
    if sources:
        source_data = [{"ID": s.id, "Name": s.name, "URL": s.url, "Tier": s.tier, "Section": s.radar_section, "Active": s.is_active} for s in sources]
        st.dataframe(source_data, use_container_width=True)
        
        col_op1, col_op2 = st.columns([1, 1])
        with col_op1:
            del_id = st.number_input("输入要删除的 Source ID", min_value=1, step=1)
            if st.button("❌ 删除该源 (Delete)", type="secondary"):
                to_delete = session.get(Source, del_id)
                if to_delete:
                    session.delete(to_delete)
                    session.commit()
                    st.success(f"已删除 ID {del_id}")
                    st.rerun()
                else:
                    st.error("找不到对应的 ID。")
        
        with col_op2:
            st.write("")
            st.write("")
            if st.button("🚀 强制立刻抓取所有源 (Force Scrape Now)", type="primary", use_container_width=True):
                with st.spinner("系统正在紧急抓取并调用大模型分析，这可能需要 1-2 分钟，请不要关闭网页..."):
                    import worker
                    try:
                        worker.run_scraping_job()
                        worker.run_processing_job()
                        st.success("强制抓取完成！请切换回【情报大屏】查看结果。")
                    except Exception as e:
                        st.error(f"抓取过程发生错误: {e}")
    else:
        st.info("尚无配置的抓取源。请在上方添加。")

# -------------------------------------------------------------
# NAVIGATION SETUP (Native SPA)
# -------------------------------------------------------------

# Custom styling for the standard sidebar
st.sidebar.markdown("### 📡 MajorRSS")
st.sidebar.caption("Enterprise AI Information Radar")
st.sidebar.divider()

# Setup native routing
pg = st.navigation([
    st.Page(page_dashboard, title="情报大屏", icon="📊"),
    st.Page(page_briefing, title="每日简报", icon="📻"),
    st.Page(page_billing, title="计费看板", icon="💳"),
    st.Page(page_settings, title="设置与数据源", icon="⚙️"),
])

# Sidebar Footer
st.sidebar.divider()
st.sidebar.caption("v1.0.1 | Core Engine Active")

# Run the selected page
pg.run()
