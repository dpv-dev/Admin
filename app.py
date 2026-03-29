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

# --- CONFIGURATION DE LA PAGE ---
LOGO_PATH = "e_logo_black.png"
st.set_page_config(page_title="ë — Admin Royalties Portal", layout="wide", page_icon="ë")

# --- 1. FONCTIONS DE FORMATTAGE ---
def fmt_money(amount):
    """ Formate les montants : 10 500.00 """
    if amount is None or np.isnan(amount): return "0.00"
    return f"{amount:,.2f}".replace(",", " ")

st.markdown("""
    <style>
    .report-card { background-color: white; padding: 20px; border-radius: 10px; border: 1px solid #e1e4e8; box-shadow: 0 2px 4px rgba(0,0,0,0.02); margin-bottom: 20px; }
    .metric-label { color: #586069; font-size: 12px; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }
    .metric-value { color: #24292e; font-size: 24px; font-weight: 700; margin-top: 5px; }
    .negative { color: #dc2626 !important; }
    .positive { color: #059669 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. LOGIQUE TECHNIQUE ---
def simplify(text):
    if not isinstance(text, str) or text.lower() == 'nan': return ""
    text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
    text = text.upper()
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text.strip()

def clean_sales(df, dist):
    """ Nettoyage des fichiers distributeurs (Kontor/RouteNote) """
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
    """ Charge les contrats, frais et paiements depuis Google Sheets """
    # ttl="0" permet de forcer la lecture de la donnée fraîche à chaque rafraîchissement
    contracts = conn.read(worksheet="Contrats", ttl="0")
    expenses = conn.read(worksheet="Depenses", ttl="0")
    payouts = conn.read(worksheet="Paiements", ttl="0")
    
    # Pré-traitement pour le matching
    contracts['key_title'] = contracts['Title'].astype(str).apply(simplify)
    contracts['key_payee'] = contracts['Payee'].astype(str).apply(simplify)
    expenses['key_title'] = expenses['Title'].astype(str).apply(simplify)
    return contracts, expenses, payouts

# --- 4. CHARGEMENT DES VENTES (LOCALE DANS /data) ---
all_sales = []
for p, n in {"data/kontor": "KONTOR", "data/routenote": "ROUTENOTE"}.items():
    if os.path.exists(p):
        for f in os.listdir(p):
            if f.endswith(('.csv', '.xlsx')):
                path_f = os.path.join(p, f)
                df_raw = pd.read_excel(path_f) if f.endswith('.xlsx') else pd.read_csv(path_f, sep=None, engine='python')
                tmp = clean_sales(df_raw, n)
                if tmp is not None: all_sales.append(tmp)
df_sales = pd.concat(all_sales, ignore_index=True) if all_sales else None

# --- 5. INTERFACE ET NAVIGATION ---
if os.path.exists(LOGO_PATH): st.sidebar.image(LOGO_PATH, width=150)
else: st.sidebar.title("ë - MUSIC")

menu = st.sidebar.radio("Menu Principal", ["📊 Dashboard & Rapports", "⚙️ Gestion Master Data (Admin)"])

# Chargement initial des données Cloud
df_contracts, df_expenses, df_payouts = load_master_data()

# --- MODE DASHBOARD ---
if menu == "📊 Dashboard & Rapports":
    if df_sales is not None:
        df_sales['Year'] = df_sales['Date'].apply(lambda x: str(x).split('-')[0])
        years_list = sorted([y for y in df_sales['Year'].dropna().unique() if y != '0000'], reverse=True)
        
        st.sidebar.subheader("🎯 Filtres de Période")
        sel_years = st.sidebar.multiselect("Années", years_list, default=years_list)
        target_payee = st.sidebar.selectbox("👤 Sélectionner un Artiste", ["-- Vue Globale Label --"] + sorted(df_contracts['Payee'].unique().tolist()))

        df_f = df_sales[df_sales['Year'].isin(sel_years)]

        if target_payee != "-- Vue Globale Label --":
            # --- CALCULS ARTISTE (LOGIQUE CATALOGUE COMPLET) ---
            rel_contracts = df_contracts[df_contracts['Payee'] == target_payee].copy()
            
            # Filtre ventes (Flex-Match)
            df_f_artist = df_f[df_f.apply(lambda r: simplify(target_payee) in r['key_artist'], axis=1)]
            sales_summary = df_f_artist.groupby('key_title')['Revenue'].sum().reset_index()
            
            # Jointure pour catalogue complet (affiche les titres à 0€)
            df_merged = rel_contracts.merge(sales_summary, on='key_title', how='left').fillna({'Revenue': 0})
            df_merged['Artist_Gross'] = df_merged['Revenue'] * df_merged['Split_Share']
            
            total_earnings = df_merged['Artist_Gross'].sum()
            total_paid = pd.to_numeric(df_payouts[df_payouts['Payee'] == target_payee]['Amount'], errors='coerce').sum()
            
            # Calcul des frais au prorata du split
            track_exp = df_expenses.groupby('key_title')['Amount'].sum().reset_index()
            costs_calc = df_merged[['key_title', 'Split_Share']].drop_duplicates().merge(track_exp, on='key_title')
            total_costs = (costs_calc['Amount'] * costs_calc['Split_Share']).sum()
            
            balance = total_earnings - total_costs - total_paid

            st.title(f"Statement: {target_payee}")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.markdown(f'<div class="report-card"><p class="metric-label">Gross Share</p><p class="metric-value">€ {fmt_money(total_earnings)}</p></div>', unsafe_allow_html=True)
            with c2: st.markdown(f'<div class="report-card"><p class="metric-label">Costs (Prorata)</p><p class="metric-value negative">-€ {fmt_money(total_costs)}</p></div>', unsafe_allow_html=True)
            with c3: st.markdown(f'<div class="report-card"><p class="metric-label">Payouts</p><p class="metric-value" style="color:#2563eb">-€ {fmt_money(total_paid)}</p></div>', unsafe_allow_html=True)
            with c4: st.markdown(f'<div class="report-card"><p class="metric-label">Balance Due</p><p class="metric-value {"positive" if balance >= 0 else "negative"}">€ {fmt_money(balance)}</p></div>', unsafe_allow_html=True)

            t1, t2, t3 = st.tabs(["📊 Ledger (Catalogue)", "📉 Plateformes", "🏦 Historique Paiements"])
            with t1:
                df_display = df_merged[['Title', 'Split_Share', 'Revenue', 'Artist_Gross']].copy()
                df_display['Split %'] = (df_display['Split_Share'] * 100).astype(int).astype(str) + "%"
                st.dataframe(df_display[['Title', 'Split %', 'Revenue', 'Artist_Gross']].style.format({'Revenue': '{:,.2f}', 'Artist_Gross': '{:,.2f}'}), use_container_width=True)
            with t2:
                if total_earnings > 0:
                    fig = px.pie(df_f_artist, values='Revenue', names='Platform', hole=0.4)
                    fig.update_traces(textinfo='label+percent', textposition='outside')
                    st.plotly_chart(fig, use_container_width=True)
                else: st.info("Aucun revenu pour les graphiques.")
            with t3:
                p = df_payouts[df_payouts['Payee'] == target_payee]
                if not p.empty: st.table(p.style.format({'Amount': '{:,.2f}'}))
                else: st.info("Aucun paiement enregistré.")

        else:
            # --- VUE GLOBALE LABEL ---
            st.title("Label Executive Dashboard")
            st.metric("Total Label Revenue", f"€ {fmt_money(df_f['Revenue'].sum())}")
            col1, col2 = st.columns(2)
            with col1:
                dist_data = df_f.groupby('Distributor')['Revenue'].sum().reset_index()
                st.table(dist_data.style.format({'Revenue': '{:,.2f}'}))
            with col2:
                fig_glob = px.pie(df_f, values='Revenue', names='Platform', hole=0.4)
                fig_glob.update_traces(textinfo='label+percent', textposition='outside')
                st.plotly_chart(fig_glob, use_container_width=True)
    else:
        st.info("👋 Chargez vos fichiers CSV dans le dossier data/ pour commencer.")

# --- MODE ADMIN (ÉDITION GOOGLE SHEETS) ---
elif menu == "⚙️ Gestion Master Data (Admin)":
    st.title("⚙️ Administration ë - MUSIC GROUP")
    st.write("Modifiez vos données ici. Cliquez sur **Sauvegarder** pour mettre à jour Google Sheets.")
    
    # Mot de passe simple pour protéger l'accès
    pwd = st.sidebar.text_input("Clé Admin", type="password")
    if pwd == "EMUSIC2024":
        tab_c, tab_e, tab_p = st.tabs(["📝 Base Contrats", "💸 Frais & Dépenses", "🏦 Paiements Effectués"])
        
        with tab_c:
            st.subheader("Catalogue & Splits")
            # st.data_editor permet de modifier le tableau comme dans Excel
            edited_c = st.data_editor(df_contracts[['Title', 'Payee', 'Split_Share']], num_rows="dynamic", use_container_width=True, key="edit_c")
            if st.button("💾 Sauvegarder les Contrats"):
                conn.update(worksheet="Contrats", data=edited_c)
                st.success("Google Sheets mis à jour avec succès !")
                st.cache_data.clear()

        with tab_e:
            st.subheader("Dépenses par Titre")
            edited_e = st.data_editor(df_expenses[['Title', 'Amount', 'Category']], num_rows="dynamic", use_container_width=True, key="edit_e")
            if st.button("💾 Sauvegarder les Dépenses"):
                conn.update(worksheet="Depenses", data=edited_e)
                st.success("Dépenses enregistrées !")
                st.cache_data.clear()

        with tab_p:
            st.subheader("Historique des Versements")
            edited_p = st.data_editor(df_payouts[['Payee', 'Amount', 'Date']], num_rows="dynamic", use_container_width=True, key="edit_p")
            if st.button("💾 Sauvegarder les Paiements"):
                conn.update(worksheet="Paiements", data=edited_p)
                st.success("Historique des paiements synchronisé !")
                st.cache_data.clear()
    else:
        st.error("Veuillez entrer la clé Admin correcte pour modifier les données.")
