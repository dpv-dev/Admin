import streamlit as st
from streamlit_gsheets import GSheetsConnection

# --- Configuration de la page ---
st.set_page_config(page_title="ë — Data Test", page_icon="ë")

st.title("🔍 Test de Connexion Google Sheets")

# 1. Création de la connexion
# L'app va chercher les accès dans Settings > Secrets
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # 2. Lecture de l'onglet "Contrats"
    # Assure-toi que le nom 'Contrats' correspond exactement au nom de l'onglet en bas de ton Google Sheet
    df_contrats = conn.read(worksheet="Contrats")

    st.success("✅ Connexion réussie ! L'application lit ton Google Sheet.")
    
    # 3. Affichage des données
    st.subheader("Données trouvées dans l'onglet 'Contrats' :")
    st.dataframe(df_contrats, use_container_width=True)

except Exception as e:
    st.error("❌ La connexion a échoué.")
    st.info("Vérifie les points suivants :")
    st.write(f"**Erreur technique :** {e}")
    st.markdown("""
    * As-tu bien partagé le Sheet avec l'e-mail du compte de service ?
    * Le contenu du JSON est-il bien collé dans les 'Secrets' sur Streamlit Cloud ?
    * L'URL du Spreadsheet dans les secrets est-elle la bonne ?
    """)

st.divider()
st.info("💡 Si tu vois tes contrats ci-dessus, nous pouvons passer à l'étape suivante : la création de l'interface Admin.")
