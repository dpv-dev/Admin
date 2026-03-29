import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import unicodedata
import re
from fpdf import FPDF
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- Configuration ---
LOGO_PATH = "e_logo_black.png"
st.set_page_config(page_title="ë — Admin Portal", layout="wide", page_icon="ë")

# --- 1. FORMATTAGE ---
def fmt_money(amount):
    return f"{amount:,.2f}".replace(",", " ")

st.markdown("""
    <style>
    .report-card { background-color: white; padding: 20px; border-radius: 10px; border: 1px solid #e1e4e8; box-shadow: 0 2px 4px rgba(0,0,0,0.02); margin-bottom: 20px; }
    .metric-label { color: #586069; font-size: 12px; text-transform: uppercase; font-weight: 600; }
    .metric-value { color: #24292e; font-size: 24px; font-weight: 700; }
    .negative { color: #dc2626 !important; }
    .positive { color: #059669 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FONCTIONS TECHNIQUES ---
def simplify(text):
    if not isinstance(text, str) or text.lower() == 'nan': return ""
    text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
    text = text.upper()
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text.strip()

def clean_sales(df, dist):
    df_c = pd.DataFrame()
    cols = df.columns.tolist()
    try:
        if dist == "KONTOR":
            df_c['Raw_Artist'] = df['Artist'].astype(str)
            df_c['Raw_Title'] = df['Title'].astype(str)
            rev = df['Royalties'].astype(str).str.replace(r'[^-0-9,.]', '', regex=True).str.replace(',', '.')
            df_c['Revenue'] = pd.to_numeric(rev, errors='coerce').fillna(0)
            df_c['Platform'] = df['Store']
            df_c['Date'] = df['Sales period'].astype(str).apply(lambda x: f"{x[:4]}-{x[4:6]}" if len(str(x))>=6 else "0000-00")
        else: # ROUTENOTE
            art_col = next((c for c in cols if c in ['Artist', 'Artist Name', 'Track Artist']), 'Artist')
            tit_col = next((c for c in cols if c in ['Track Title', 'Title']), 'Title')
            rev_col = next((c for c in cols if c in ['Earnings($)', 'Net Amount']), 'Earnings')
            df_c['Raw_Artist'] = df[art_col].astype(str)
            df_c['Raw_Title'] = df[tit_col].astype(str)
            rev = df[rev_col].astype(str).str.replace(r'[^-0-9,.]', '', regex=True).str.replace(',', '.')
            df_c['Revenue'] = pd.to_numeric(rev, errors='coerce').fillna(0)
            df_c['Platform'] = df['Retailer'] if 'Retailer' in cols else "Unknown"
            m_map = {'JAN':'01','FEB':'02','MAR':'03','APR':'04','MAY':'05','JUN':'06','JUL':'07','AUG':'08','SEP':'09','OCT':'10','NOV':'11','DEC':'12'}
            df_c['Date'] = df.apply(lambda r: f"{r['Year']}-{m_map.get(str(r['Month']).split('-')[-1].upper()[:3], '01')}", axis=1)
        
        df_c['key_title'] = df_c['Raw_Title'].apply(simplify)
        df_c['key_artist'] = df_c['Raw_Artist'].apply(simplify)
        df_c['Distributor'] = dist
        return df_c
    except: return None

# --- 3. CONNEXION GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_master_data():
    contracts = conn.read(worksheet="Contrats", ttl="5m")
    expenses = conn.read(worksheet="Depenses", ttl="5m")
    payouts = conn.read(worksheet="Paiements", ttl="5m")
    
    # Préparation des clés pour le matching
    contracts['key_title'] = contracts['Title'].astype(str).apply(simplify)
    contracts['key_payee'] = contracts['Payee'].astype(str).apply(simplify)
    expenses['key_title'] = expenses['Title'].astype(str).apply(simplify)
    return contracts, expenses, payouts

# --- 4. CHARGEMENT VENTES (LOCALE) ---
all_s = []
for p, n in {"data/kontor": "KONTOR", "data/routenote": "ROUTENOTE"}.items():
    if os.path.exists(p):
        for f in os.listdir(p):
            if f.endswith(('.csv', '.xlsx')):
                df_raw = pd.read_excel(os.path.join(p, f)) if f.endswith('.xlsx') else pd.read_csv(os.path.join(p, f), sep=None, engine='python')
                tmp = clean_sales(df_raw, n)
                if tmp is not None: all_s.append(tmp)
df_sales = pd.concat(all_s, ignore_index=True) if all_s else None

# --- 5. INTERFACE ---
st.sidebar.image(LOGO_PATH, width=150) if os.path.exists(LOGO_PATH) else st.sidebar.title("ë")

# NAVIGATION
menu = st.sidebar.radio("Navigation", ["📊 Dashboard & Rapports", "⚙️ Administration (Éditer)"])

df_contracts, df_expenses, df_payouts = load_master_data()

if menu == "📊 Dashboard & Rapports":
    if df_sales is not None:
        df_sales['Year'] = df_sales['Date'].apply(lambda x: str(x).split('-')[0])
        years_list = sorted([y for y in df_sales['Year'].dropna().unique() if y != '0000'], reverse=True)
        
        st.sidebar.subheader("🎯 Filtres")
        sel_years = st.sidebar.multiselect("Années", years_list, default=years_list)
        target_payee = st.sidebar.selectbox("👤 Sélectionner un Artiste", ["-- Tous les Artistes --"] + sorted(df_contracts['Payee'].unique().tolist()))

        df_f = df_sales[df_sales['Year'].isin(sel_years)]

        if target_payee != "-- Tous les Artistes --":
            # --- VUE ARTISTE ---
            rel_contracts = df_contracts[df_contracts['Payee'] == target_payee].copy()
            df_f_artist = df_f[df_f.apply(lambda r: simplify(target_payee) in r['key_artist'], axis=1)]
            sales_summary = df_f_artist.groupby('key_title')['Revenue'].sum().reset_index()
            
            df_merged = rel_contracts.merge(sales_summary, on='key_title', how='left').fillna({'Revenue': 0})
            df_merged['Artist_Gross'] = df_merged['Revenue'] * df_merged['Split_Share']
            
            total_earnings = df_merged['Artist_Gross'].sum()
            total_paid = df_payouts[df_payouts['Payee'] == target_payee]['Amount'].sum()
            
            # Frais
            track_exp = df_expenses.groupby('key_title')['Amount'].sum().reset_index()
            costs_calc = df_merged[['key_title', 'Split_Share']].drop_duplicates().merge(track_exp, on='key_title')
            total_costs = (costs_calc['Amount'] * costs_calc['Split_Share']).sum()
            
            balance = total_earnings - total_costs - total_paid

            st.title(f"Statement: {target_payee}")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.markdown(f'<div class="report-card"><p class="metric-label">Earnings</p><p class="metric-value">€ {fmt_money(total_earnings)}</p></div>', unsafe_allow_html=True)
            with c2: st.markdown(f'<div class="report-card"><p class="metric-label">Costs</p><p class="metric-value negative">-€ {fmt_money(total_costs)}</p></div>', unsafe_allow_html=True)
            with c3: st.markdown(f'<div class="report-card"><p class="metric-label">Payouts</p><p class="metric-value" style="color:#2563eb">-€ {fmt_money(total_paid)}</p></div>', unsafe_allow_html=True)
            with c4: st.markdown(f'<div class="report-card"><p class="metric-label">Balance</p><p class="metric-value {"positive" if balance >= 0 else "negative"}">€ {fmt_money(balance)}</p></div>', unsafe_allow_html=True)

            t1, t2 = st.tabs(["📊 Ledger", "📉 Plateformes"])
            with t1:
                df_merged['Split %'] = (df_merged['Split_Share'] * 100).astype(int).astype(str) + "%"
                st.dataframe(df_merged[['Title', 'Split %', 'Revenue', 'Artist_Gross']].style.format({'Revenue': '{:,.2f}', 'Artist_Gross': '{:,.2f}'}), use_container_width=True)
            with t2:
                if total_earnings > 0:
                    fig = px.pie(df_f_artist, values='Revenue', names='Platform', hole=0.4)
                    fig.update_traces(textinfo='label+percent', textposition='outside')
                    st.plotly_chart(fig, use_container_width=True)

        else:
            # --- DASHBOARD GLOBAL ---
            st.title("Label Dashboard")
            st.metric("Total Revenue", f"€ {fmt_money(df_f['Revenue'].sum())}")
            st.plotly_chart(px.bar(df_f.groupby('Platform')['Revenue'].sum().reset_index(), x='Platform', y='Revenue', color='Platform'))

    else: st.info("Chargez des fichiers dans le dossier data/")

elif menu == "⚙️ Administration (Éditer)":
    st.title("⚙️ Mode Gestion Master Data")
    st.warning("Toute modification ici sera enregistrée directement dans Google Sheets.")
    
    pwd = st.sidebar.text_input("Mot de passe Admin", type="password")
    if pwd == "EMUSIC2024": # Change ton mot de passe ici
        tab_c, tab_e, tab_p = st.tabs(["📝 Contrats & Splits", "💸 Dépenses", "🏦 Paiements"])
        
        with tab_c:
            st.subheader("Modifier les Contrats")
            # L'éditeur de données magique
            edited_contracts = st.data_editor(df_contracts[['Title', 'Payee', 'Split_Share']], num_rows="dynamic", use_container_width=True)
            if st.button("💾 Sauvegarder Contrats"):
                conn.update(worksheet="Contrats", data=edited_contracts)
                st.success("Google Sheets mis à jour !")

        with tab_e:
            st.subheader("Gérer les Dépenses")
            edited_expenses = st.data_editor(df_expenses[['Title', 'Amount', 'Category']], num_rows="dynamic", use_container_width=True)
            if st.button("💾 Sauvegarder Dépenses"):
                conn.update(worksheet="Depenses", data=edited_expenses)
                st.success("Dépenses mises à jour !")

        with tab_p:
            st.subheader("Enregistrer des Paiements")
            edited_payouts = st.data_editor(df_payouts[['Payee', 'Amount', 'Date']], num_rows="dynamic", use_container_width=True)
            if st.button("💾 Sauvegarder Paiements"):
                conn.update(worksheet="Paiements", data=edited_payouts)
                st.success("Paiements mis à jour !")
    else:
        st.error("Veuillez entrer le mot de passe Admin dans la barre latérale.")
