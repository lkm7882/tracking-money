import streamlit as st
import pandas as pd
import requests
import json
import time
import plotly.express as px
import plotly.graph_objects as go
import FinanceDataReader as fdr
from datetime import datetime, timedelta

# --- 1. 백엔드 엔진 ---
@st.cache_data(ttl=86400)
def get_kis_token(app_key, app_secret):
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    body = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
    res = requests.post(url, headers={"content-type": "application/json"}, data=json.dumps(body))
    if res.status_code == 200:
        return res.json().get('access_token')
    return None

@st.cache_data(ttl=600)
def get_ranking_data(token, app_key, app_secret, investor_type, action_type):
    time.sleep(0.6) # 🚨 방어막: 초당 1건 제한(Rate Limit) 회피
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/foreign-institution-total"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": app_secret, "tr_id": "FHKST03120000", "custtype": "P"
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "V", "FID_COND_SCR_DIV_CODE": "20169", "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0", "FID_RANK_SORT_CLS_CODE": action_type, "FID_ETC_CLS_CODE": "0"
    }
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200:
        data = res.json()
        if data.get('rt_cd') == '0':
            df = pd.DataFrame(data.get('output', []))
            if not df.empty:
                df = df[['hts_kor_isnm', 'ntby_qty']]
                df.columns = ['종목명', '수량']
                df['수량'] = pd.to_numeric(df['수량'])
                return df, ""
        # 🚨 에러 시 증권사의 원본 거절 메시지를 리턴
        return pd.DataFrame(), data.get('msg1', '조회된 데이터가 없습니다.')
    return pd.DataFrame(), f"HTTP 에러: {res.status_code}"

@st.cache_data(ttl=600)
def get_dual_macro_data(token, app_key, app_secret, start_date, end_date):
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": app_secret, "tr_id": "FHKST01010900", "custtype": "P"
    }
    def fetch_stock(code, name):
        time.sleep(0.6) # 🚨 방어막: 0.6초 대기
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200 and res.json().get('rt_cd') == '0':
            df = pd.DataFrame(res.json().get('output', []))
            if not df.empty:
                df = df[['stck_bsop_date', 'frgn_ntby_qty', 'orgn_ntby_qty', 'prsn_ntby_qty']]
                df.columns = ['날짜', f'{name}_외국인', f'{name}_기관', f'{name}_개인']
                df['날짜'] = pd.to_datetime(df['날짜'])
                df[f'{name}_외국인'] = pd.to_numeric(df[f'{name}_외국인'])
                df[f'{name}_기관'] = pd.to_numeric(df[f'{name}_기관'])
                df[f'{name}_개인'] = pd.to_numeric(df[f'{name}_개인'])
                return df.set_index('날짜')
        return pd.DataFrame()

    df_sam = fetch_stock("005930", "삼성전자")
    df_hy = fetch_stock("000660", "하이닉스")
    
    df_usd = fdr.DataReader('USD/KRW', start_date, end_date)[['Close']]
    df_usd.columns = ['원달러환율']
    df_usd.index = pd.to_datetime(df_usd.index)
    
    df_kospi = fdr.DataReader('KS11', start_date, end_date)[['Close']]
    df_kospi.columns = ['코스피']
    df_kospi.index = pd.to_datetime(df_kospi.index)
    
    df_merged = pd.merge(df_sam, df_hy, left_index=True, right_index=True, how='outer')
    df_merged = pd.merge(df_merged, df_usd, left_index=True, right_index=True, how='left')
    df_merged = pd.merge(df_merged, df_kospi, left_index=True, right_index=True, how='left')
    
    df_merged['원달러환율'] = df_merged['원달러환율'].ffill().bfill()
    df_merged['코스피'] = df_merged['코스피'].ffill().bfill()
    df_merged = df_merged.sort_index()
    df_merged['환율변동'] = df_merged['원달러환율'].diff()
    return df_merged

@st.cache_data(ttl=60)
def get_intraday_data(token, app_key, app_secret, stock_code):
    time.sleep(0.6) # 🚨 방어막: 초당 1건 제한(Rate Limit) 회피
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": app_secret,
        "tr_id": "FHKST01010300",
        "custtype": "P"
    }
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        if data.get('rt_cd') == '0':
            out = data.get('output', [])
            if out:
                df = pd.DataFrame(out)
                df = df[['stck_cntg_hour', 'frgn_ntby_qty', 'orgn_ntby_qty']]
                df.columns = ['시간', '외국인', '기관']
                df = df[df['시간'] != ""]
                df['시간'] = pd.to_datetime(df['시간'], format='%H%M%S').dt.strftime('%H:%M')
                df['외국인'] = pd.to_numeric(df['외국인'])
                df['기관'] = pd.to_numeric(df['기관'])
                df = df.sort_values('시간').reset_index(drop=True)
                return df, ""
        # 🚨 에러 시 증권사의 원본 거절 메시지를 리턴
        return pd.DataFrame(), data.get('msg1', '데이터 없음')
    return pd.DataFrame(), f"HTTP 에러: {res.status_code}"


# --- 2. 프론트엔드 UI ---
st.set_page_config(page_title="KOSPI Security Dashboard", layout="wide")
st.title("🐳 KOSPI 올인원 관제 센터 v14.3")

if 'saved_key' not in st.session_state: st.session_state.saved_key = ""
if 'saved_secret' not in st.session_state: st.session_state.saved_secret = ""
if 'is_saved' not in st.session_state: st.session_state.is_saved = False

st.sidebar.header("🔑 한국투자증권 인증")
user_app_key = st.sidebar.text_input("App Key 입력", type="password", value=st.session_state.saved_key)
user_app_secret = st.sidebar.text_input("App Secret 입력", type="password", value=st.session_state.saved_secret)

save_keys = st.sidebar.checkbox("이 브라우저 탭에 키 기억하기", value=st.session_state.is_saved)
if save_keys:
    st.session_state.saved_key = user_app_key; st.session_state.saved_secret = user_app_secret; st.session_state.is_saved = True
else:
    st.session_state.saved_key = ""; st.session_state.saved_secret = ""; st.session_state.is_saved = False

st.sidebar.markdown("---")

if st.sidebar.button("🔄 최신 데이터 강제 새로고침 (클릭 시 3초 소요)"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")

if not user_app_key or not user_app_secret:
    st.warning("🔒 좌측 사이드바에 한국투자증권 **App Key**와 **App Secret**을 입력하시면 대시보드가 활성화됩니다.")
else:
    token = get_kis_token(user_app_key, user_app_secret)
    if not token:
        st.sidebar.error("❌ 토큰 발급 실패")
    else:
        st.sidebar.success("✅ 한투 API 서버 연결 성공")
        
        tab_macro, tab_ranking, tab_intraday = st.tabs(["🚨 자본 이탈 (30일 누적)", "🏆 큰손 섹터 랭킹", "⏱️ 장중 실시간(잠정) 레이더"])

        # ==========================================
        # 탭 1: 자본 이탈 감지 (30일 누적 베이스)
        # ==========================================
        with tab_macro:
            st.markdown("단가 차이를 보정한 투톱 수급과 코스피 지수, 환율을 종합적으로 분석합니다.")
            
            st.markdown("##### 👀 매크로 추적 주체 선택 (복수 선택 가능)")
            col_inv1, col_inv2, col_inv3 = st.columns(3)
            with col_inv1: check_fore = st.checkbox("외국인", value=True)
            with col_inv2: check_inst = st.checkbox("기관", value=True)
            with col_inv3: check_pers = st.checkbox("개인", value=True)
            
            selected_investors = [inv for inv, chk in zip(["외국인", "기관", "개인"], [check_fore, check_inst, check_pers]) if chk]
            st.markdown("---")
            
            today = datetime.today()
            min_selectable_date = today - timedelta(days=30)
            col_d1, col_d2 = st.columns(2)
            with col_d1: start_date = st.date_input("시작일", value=min_selectable_date, min_value=min_selectable_date, max_value=today)
            with col_d2: end_date = st.date_input("종료일", value=today, min_value=min_selectable_date, max_value=today)
            
            st.markdown("##### 🎛️ 경보 및 가중치(치환율) 설정")
            col_t1, col_t2, col_t3 = st.columns(3)
            with col_t1: sell_threshold = st.number_input(f"🔴 매도 경보 기준 (주)", value=-2000000, step=500000)
            with col_t2: fx_threshold = st.number_input("📈 환율 상승 경보 기준 (원)", value=5.0, step=1.0)
            with col_t3: hynix_ratio = st.number_input("⚖️ SK하이닉스 가중치 (기본 1.0)", value=1.0, step=0.1)

            df_macro = get_dual_macro_data(token, user_app_key, user_app_secret, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
            
            if not df_macro.empty and selected_investors:
                if '하이닉스_외국인' not in df_macro.columns or '삼성전자_외국인' not in df_macro.columns:
                    st.error("⚠️ 증권사 서버 트래픽 제한(Rate Limit)으로 일부 종목이 누락되었습니다. 좌측 [강제 새로고침]을 다시 눌러주세요.")
                else:
                    for inv in ["외국인", "기관", "개인"]:
                        df_macro[f'하이닉스_환산_{inv}'] = df_macro[f'하이닉스_{inv}'] * hynix_ratio
                        df_macro[f'투톱합산_{inv}'] = df_macro[f'삼성전자_{inv}'] + df_macro[f'하이닉스_환산_{inv}']

                    latest = df_macro.iloc[-1]
                    is_fx_spiking = latest['환율변동'] >= fx_threshold
                    
                    st.markdown(f"##### 📊 선택 구간 누적 수급 순계 (삼성전자 + 하이닉스x{hynix_ratio} 환산 총합)")
                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric("🛒 외국인 누적", f"{df_macro['투톱합산_외국인'].sum():,.0f} 주")
                    col_m2.metric("🛡️ 기관(연기금) 누적", f"{df_macro['투톱합산_기관'].sum():,.0f} 주")
                    col_m3.metric("🐜 개인 누적", f"{df_macro['투톱합산_개인'].sum():,.0f} 주")
                    st.markdown("---")
                    
                    st.markdown("##### 🚨 실시간 수급 경보 상태")
                    for inv in selected_investors:
                        col_sam = f'삼성전자_{inv}'; col_hy_adj = f'하이닉스_환산_{inv}'
                        is_selling = (latest[col_sam] <= sell_threshold) or (latest[col_hy_adj] <= sell_threshold)
                        if is_selling:
                            if inv == "외국인" and is_fx_spiking: st.error(f"🚨 **[{inv}] 자본 이탈 경보:** 대장주 매도 및 환율 급등!")
                            else: st.warning(f"⚠️ **[{inv}] 대량 매도:** 대장주 매도세 진행 중")
                        else: st.info(f"🟢 **[{inv}] 안전/관망:** 뚜렷한 리스크 시그널 없음")
                    
                    fig_macro = go.Figure()
                    color_map = {"외국인": ('#4169E1', '#CD5C5C'), "기관": ('#2E8B57', '#8A2BE2'), "개인": ('#FF8C00', '#DAA520')}
                    for inv in selected_investors:
                        c_sam, c_hy = color_map[inv]
                        fig_macro.add_trace(go.Bar(x=df_macro.index, y=df_macro[f'삼성전자_{inv}'], name=f"삼성전자 ({inv})", marker_color=c_sam, yaxis="y1"))
                        fig_macro.add_trace(go.Bar(x=df_macro.index, y=df_macro[f'하이닉스_환산_{inv}'], name=f"SK하이닉스 환산 ({inv})", marker_color=c_hy, yaxis="y1"))
                    
                    fig_macro.add_trace(go.Scatter(x=df_macro.index, y=df_macro['원달러환율'], name="환율", mode="lines+markers", line=dict(color="orange", width=2), yaxis="y2"))
                    fig_macro.add_trace(go.Scatter(x=df_macro.index, y=df_macro['코스피'], name="코스피 지수", mode="lines", line=dict(color="gray", width=3, dash="dot"), yaxis="y3"))
                    
                    fig_macro.update_layout(
                        xaxis=dict(domain=[0, 0.9]), yaxis=dict(title="수량(주)"),
                        yaxis2=dict(title="환율(원)", side="right", overlaying="y", showgrid=False),
                        yaxis3=dict(title="코스피", side="right", overlaying="y", anchor="free", position=1.0, showgrid=False),
                        hovermode="x unified", barmode='group', legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_macro, use_container_width=True)
            elif not selected_investors:
                st.warning("👀 위쪽에서 추적할 주체를 최소 1개 이상 선택해 주세요.")

        # ==========================================
        # 탭 2: 큰손 섹터 랭킹 (듀얼 뷰)
        # ==========================================
        with tab_ranking:
            st.markdown("선택한 주체의 당일 매수 상위 종목과 매도 상위 종목을 동시에 비교 분석합니다.")
            inv_sel = st.radio("👀 분석 주체 선택", ("외국인", "기관투자자"), horizontal=True)
            inv_code = "9000" if inv_sel == "외국인" else "9001"
            
            st.markdown("---")
            col_buy, col_sell = st.columns(2)
            
            with col_buy:
                st.markdown(f"#### 🔥 {inv_sel} 순매수 TOP 10")
                # 🚨 엔진 수정 반영: 에러 원인 메시지까지 리턴받기
                df_buy, msg_buy = get_ranking_data(token, user_app_key, user_app_secret, inv_code, "0")
                if not df_buy.empty:
                    fig_buy = px.bar(df_buy, x='수량', y='종목명', orientation='h', text='수량')
                    fig_buy.update_layout(yaxis={'categoryorder': 'total ascending'}, plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=30, b=0))
                    fig_buy.update_traces(marker_color='#FF4B4B', texttemplate='%{text:,.0f} 주', textposition='outside')
                    st.plotly_chart(fig_buy, use_container_width=True)
                else:
                    st.warning(f"⚠️ 데이터 없음 (사유: {msg_buy})")
                    
            with col_sell:
                st.markdown(f"#### 🧊 {inv_sel} 순매도 TOP 10")
                df_sell, msg_sell = get_ranking_data(token, user_app_key, user_app_secret, inv_code, "1")
                if not df_sell.empty:
                    fig_sell = px.bar(df_sell, x='수량', y='종목명', orientation='h', text='수량')
                    fig_sell.update_layout(yaxis={'categoryorder': 'total ascending'}, plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=30, b=0))
                    fig_sell.update_traces(marker_color='#1F77B4', texttemplate='%{text:,.0f} 주', textposition='outside')
                    st.plotly_chart(fig_sell, use_container_width=True)
                else:
                    st.warning(f"⚠️ 데이터 없음 (사유: {msg_sell})")

        # ==========================================
        # 탭 3: 장중 실시간(잠정) 레이더
        # ==========================================
        with tab_intraday:
            st.markdown("오늘 하루 동안의 코스피 투톱(대장주)에 대한 외국인과 기관의 장중 잠정 수급 흐름을 추적합니다.")
            st.info("💡 **안내:** 한국거래소(KRX) 규정상 장중 수급은 09:30부터 약 4~5회 (가집계 잠정치)만 제공됩니다. 초단위 실시간 틱 데이터가 아님을 유의하세요.")
            
            target_stock = st.radio("🎯 장중 추적 타겟 종목", ["삼성전자 (005930)", "SK하이닉스 (000660)"], horizontal=True)
            stock_code = "005930" if "삼성전자" in target_stock else "000660"
            
            if st.button("📡 현재 시간 기준 레이더 재스캔 (수동 새로고침)"):
                st.cache_data.clear()
                st.rerun()
            
            df_intra, msg_intra = get_intraday_data(token, user_app_key, user_app_secret, stock_code)
            
            if df_intra.empty:
                st.warning(f"⚠️ 장중 데이터가 없습니다. (사유: {msg_intra})")
            else:
                st.markdown(f"#### 📊 {target_stock.split(' ')[0]} 당일 시간대별 누적 순매수 (잠정치)")
                
                fig_intra = go.Figure()
                fig_intra.add_trace(go.Scatter(
                    x=df_intra['시간'], y=df_intra['외국인'], 
                    name="외국인 잠정 순매수", mode="lines+markers+text", 
                    line=dict(color="#4169E1", width=4), fill='tozeroy', text=df_intra['외국인'], textposition="top center"
                ))
                fig_intra.add_trace(go.Scatter(
                    x=df_intra['시간'], y=df_intra['기관'], 
                    name="기관 잠정 순매수", mode="lines+markers+text", 
                    line=dict(color="#2E8B57", width=4), fill='tozeroy', text=df_intra['기관'], textposition="bottom center"
                ))
                
                fig_intra.update_layout(
                    xaxis_title="집계 시간", yaxis_title="누적 순매수 수량 (주)",
                    hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                fig_intra.update_traces(texttemplate='%{text:,.0f}')
                st.plotly_chart(fig_intra, use_container_width=True)