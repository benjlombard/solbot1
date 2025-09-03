import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# Database connection
def connect_to_db(db_path):
    """Connect to the SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        st.error(f"Database connection error: {e}")
        raise

# Fetch all tokens from creator_token_history
def get_tokens(conn):
    query = """
    SELECT 
        id, creator_address, token_address, token_name, token_symbol, 
        launch_date, outcome_type, roi_24h, peak_market_cap, 
        survival_time_hours, is_success, contributed_to_blacklist, 
        notes, created_at, current_market_cap, last_updated_from_api,
        is_complete, bonding_curve_completed_timestamp
    FROM creator_token_history
    ORDER BY id ASC
    """
    try:
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# Fetch creator stats for indicators
def get_creator_stats(conn):
    query = """
    SELECT 
        creator_address,
        COUNT(*) as token_count,
        MIN(launch_date) as first_launch,
        MAX(launch_date) as last_launch
    FROM creator_token_history
    GROUP BY creator_address
    """
    try:
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        st.error(f"Error fetching creator stats: {e}")
        return pd.DataFrame()

def format_timestamp(timestamp):
    """Convert timestamp to readable date format"""
    if pd.isna(timestamp) or timestamp == 0:
        return "N/A"
    try:
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return "N/A"

def create_survival_time_charts(df_tokens):
    """Create charts for survival time distribution"""
    if df_tokens.empty or df_tokens['survival_time_hours'].isna().all():
        st.warning("Aucune donnée de temps de survie disponible pour les graphiques.")
        return
    
    # Filter out invalid data
    valid_survival = df_tokens[df_tokens['survival_time_hours'].notna() & (df_tokens['survival_time_hours'] > 0)].copy()
    
    if valid_survival.empty:
        st.warning("Aucune donnée valide de temps de survie pour les graphiques.")
        return
    
    st.header("📈 Distribution du Temps de Survie")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Histogramme - Temps de Survie (Heures)")
        
        # Create histogram
        fig_hist = px.histogram(
            valid_survival, 
            x='survival_time_hours',
            nbins=20,
            title="Distribution du Temps de Survie",
            labels={
                'survival_time_hours': 'Temps de Survie (Heures)',
                'count': 'Nombre de Tokens'
            },
            color_discrete_sequence=['#1f77b4']
        )
        fig_hist.update_layout(
            xaxis_title="Temps de Survie (Heures)",
            yaxis_title="Nombre de Tokens",
            showlegend=False
        )
        st.plotly_chart(fig_hist, use_container_width=True)
    
    with col2:
        st.subheader("Répartition par Tranches de Temps")
        
        # Create survival time categories
        def categorize_survival_time(hours):
            if hours < 1:
                return "< 1 heure"
            elif hours < 6:
                return "1-6 heures"
            elif hours < 24:
                return "6-24 heures"
            elif hours < 72:
                return "1-3 jours"
            elif hours < 168:  # 7 days
                return "3-7 jours"
            else:
                return "> 7 jours"
        
        valid_survival['survival_category'] = valid_survival['survival_time_hours'].apply(categorize_survival_time)
        
        # Create pie chart
        survival_counts = valid_survival['survival_category'].value_counts()
        
        # Define color palette
        colors = ['#ff9999', '#66b3ff', '#99ff99', '#ffcc99', '#ff99cc', '#c2c2f0']
        
        fig_pie = go.Figure(data=[go.Pie(
            labels=survival_counts.index,
            values=survival_counts.values,
            hole=0.3,
            marker_colors=colors[:len(survival_counts)]
        )])
        
        fig_pie.update_traces(
            textposition='inside', 
            textinfo='percent+label',
            hovertemplate='<b>%{label}</b><br>Tokens: %{value}<br>Pourcentage: %{percent}<extra></extra>'
        )
        
        fig_pie.update_layout(
            title="Répartition par Tranches de Temps de Survie",
            annotations=[dict(text='Tokens', x=0.5, y=0.5, font_size=16, showarrow=False)]
        )
        
        st.plotly_chart(fig_pie, use_container_width=True)
    
    # Summary statistics
    st.subheader("📊 Statistiques de Temps de Survie")
    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
    
    with col_stat1:
        st.metric("Médiane", f"{valid_survival['survival_time_hours'].median():.2f}h")
    with col_stat2:
        st.metric("Moyenne", f"{valid_survival['survival_time_hours'].mean():.2f}h")
    with col_stat3:
        st.metric("Min", f"{valid_survival['survival_time_hours'].min():.2f}h")
    with col_stat4:
        st.metric("Max", f"{valid_survival['survival_time_hours'].max():.2f}h")
    
    # Show category breakdown table
    st.subheader("Détail par Catégorie")
    category_df = survival_counts.reset_index()
    category_df.columns = ['Catégorie de Temps', 'Nombre de Tokens']
    category_df['Pourcentage'] = (category_df['Nombre de Tokens'] / category_df['Nombre de Tokens'].sum() * 100).round(1)
    category_df['Pourcentage'] = category_df['Pourcentage'].astype(str) + '%'
    
    st.dataframe(category_df, use_container_width=True, hide_index=True)

def create_creator_analysis_table(df_tokens):
    """Create analysis table for creators with multiple tokens"""
    if df_tokens.empty:
        st.warning("Aucune donnée disponible pour l'analyse des créateurs.")
        return
    
    # Filter out tokens without valid survival time
    valid_tokens = df_tokens[df_tokens['survival_time_hours'].notna() & (df_tokens['survival_time_hours'] >= 0)].copy()
    
    if valid_tokens.empty:
        st.warning("Aucune donnée valide de temps de survie pour l'analyse des créateurs.")
        return
    
    st.header("👥 Analyse des Créateurs Multi-Tokens")
    
    # Group by creator and calculate metrics
    creator_stats = valid_tokens.groupby('creator_address').agg({
        'token_address': 'count',  # nombre de tokens
        'survival_time_hours': ['min', 'max', 'mean', 'median'],
        'is_complete': ['sum', 'count']  # sum = nombre migrés, count = total
    }).round(2)
    
    # Flatten column names
    creator_stats.columns = [
        'nb_tokens', 
        'survival_min', 'survival_max', 'survival_mean', 'survival_median',
        'tokens_migrated', 'total_tokens_check'
    ]
    
    # Calculate migration info
    creator_stats['migration_rate'] = (creator_stats['tokens_migrated'] / creator_stats['nb_tokens'] * 100).round(1)
    creator_stats['has_migrated'] = creator_stats['tokens_migrated'] > 0
    creator_stats['migrated_status'] = creator_stats['has_migrated'].map({True: 'Oui', False: 'Non'})
    
    # Reset index to make creator_address a column
    creator_stats = creator_stats.reset_index()
    
    # Filter for creators with at least 2 tokens
    multi_token_creators = creator_stats[creator_stats['nb_tokens'] >= 2].copy()
    
    if multi_token_creators.empty:
        st.info("Aucun créateur n'a lancé au moins 2 tokens.")
        return
    
    # Display filter controls
    st.subheader("Filtres")
    col_filter1, col_filter2, col_filter3 = st.columns(3)
    
    with col_filter1:
        min_tokens = int(multi_token_creators['nb_tokens'].min())
        max_tokens = int(multi_token_creators['nb_tokens'].max())
        tokens_range = st.slider(
            "Nombre minimum de tokens créés",
            min_value=min_tokens,
            max_value=max_tokens,
            value=min_tokens,
            step=1,
            key="creator_tokens_filter"
        )
    
    with col_filter2:
        migration_filter = st.selectbox(
            "Filtre migration",
            options=['Tous', 'Au moins 1 migré', 'Aucun migré'],
            key="creator_migration_filter"
        )
    
    with col_filter3:
        min_survival_mean = multi_token_creators['survival_mean'].min()
        max_survival_mean = multi_token_creators['survival_mean'].max()
        if min_survival_mean < max_survival_mean:
            survival_mean_range = st.slider(
                "Temps de survie moyen minimum (h)",
                min_value=float(min_survival_mean),
                max_value=float(max_survival_mean),
                value=float(min_survival_mean),
                step=0.1,
                key="creator_survival_filter"
            )
        else:
            survival_mean_range = min_survival_mean
    
    # Apply filters
    filtered_creators = multi_token_creators[multi_token_creators['nb_tokens'] >= tokens_range].copy()
    
    if migration_filter == 'Au moins 1 migré':
        filtered_creators = filtered_creators[filtered_creators['has_migrated'] == True]
    elif migration_filter == 'Aucun migré':
        filtered_creators = filtered_creators[filtered_creators['has_migrated'] == False]
    
    if min_survival_mean < max_survival_mean:
        filtered_creators = filtered_creators[filtered_creators['survival_mean'] >= survival_mean_range]
    
    # Sort by number of tokens (descending) then by average survival time
    filtered_creators = filtered_creators.sort_values(['nb_tokens', 'survival_mean'], ascending=[False, False])
    
    # Prepare display dataframe
    display_creators = filtered_creators.copy()
    display_creators['creator_address_short'] = display_creators['creator_address'].apply(lambda x: x[:8] + "..." + x[-8:])
    
    # Select and rename columns for display
    display_columns = [
        'creator_address_short', 'nb_tokens', 'survival_min', 'survival_max', 
        'survival_mean', 'survival_median', 'tokens_migrated', 'migration_rate', 'migrated_status'
    ]
    
    column_names = {
        'creator_address_short': 'Adresse Créateur',
        'nb_tokens': 'Nb Tokens',
        'survival_min': 'Survie Min (h)',
        'survival_max': 'Survie Max (h)',
        'survival_mean': 'Survie Moyenne (h)',
        'survival_median': 'Survie Médiane (h)',
        'tokens_migrated': 'Tokens Migrés',
        'migration_rate': 'Taux Migration (%)',
        'migrated_status': 'A Migré'
    }
    
    # Display the table
    st.dataframe(
        display_creators[display_columns].rename(columns=column_names),
        use_container_width=True,
        hide_index=True
    )
    
    # Display summary statistics
    st.subheader("📊 Résumé")
    col_sum1, col_sum2, col_sum3, col_sum4 = st.columns(4)
    
    with col_sum1:
        st.metric("Créateurs Multi-Tokens", len(filtered_creators))
    with col_sum2:
        creators_with_migration = len(filtered_creators[filtered_creators['has_migrated'] == True])
        st.metric("Créateurs avec ≥1 Migration", creators_with_migration)
    with col_sum3:
        avg_tokens_per_creator = filtered_creators['nb_tokens'].mean()
        st.metric("Moyenne Tokens/Créateur", f"{avg_tokens_per_creator:.1f}")
    with col_sum4:
        top_creator_tokens = filtered_creators['nb_tokens'].max() if not filtered_creators.empty else 0
        st.metric("Max Tokens (1 créateur)", top_creator_tokens)
    
    # Show top performers
    if not filtered_creators.empty:
        st.subheader("🏆 Top Créateurs")
        
        col_top1, col_top2 = st.columns(2)
        
        with col_top1:
            st.write("**Plus productifs (nb tokens):**")
            top_productive = filtered_creators.head(5)[['creator_address', 'nb_tokens', 'migration_rate']].copy()
            top_productive['creator_address'] = top_productive['creator_address'].apply(lambda x: x[:12] + "...")
            top_productive.columns = ['Créateur', 'Tokens', 'Taux Migration (%)']
            st.dataframe(top_productive, hide_index=True)
        
        with col_top2:
            st.write("**Meilleure survie moyenne:**")
            top_survival = filtered_creators.nlargest(5, 'survival_mean')[['creator_address', 'nb_tokens', 'survival_mean']].copy()
            top_survival['creator_address'] = top_survival['creator_address'].apply(lambda x: x[:12] + "...")
            top_survival.columns = ['Créateur', 'Tokens', 'Survie Moy (h)']
            st.dataframe(top_survival, hide_index=True)
    
    # Download button
    csv_creators = filtered_creators.to_csv(index=False)
    st.download_button(
        label="Télécharger l'analyse des créateurs (CSV)",
        data=csv_creators,
        file_name="creator_analysis.csv",
        mime="text/csv",
        key="creator_analysis_download"
    )

def display_token_table(df_tokens, title, show_completion_timestamp=False):
    """Display a token table with filters"""
    st.header(f"📋 {title}")
    
    if df_tokens.empty:
        st.info(f"Aucun token trouvé pour la catégorie: {title}")
        return
    
    # Prepare DataFrame for display
    df_display = df_tokens.copy()
    df_display['launch_date'] = df_display['launch_date'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df_display['created_at'] = df_display['created_at'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df_display['last_updated_from_api'] = df_display['last_updated_from_api'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df_display['current_market_cap'] = df_display['current_market_cap'].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) else "N/A")
    df_display['peak_market_cap'] = df_display['peak_market_cap'].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) else "N/A")
    df_display['survival_time_hours'] = df_display['survival_time_hours'].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) else "N/A")
    
    # Add completion timestamp if needed
    if show_completion_timestamp:
        df_display['bonding_curve_completed_timestamp_formatted'] = df_display['bonding_curve_completed_timestamp'].apply(format_timestamp)
    
    # Calculate market cap percentage change
    df_display['market_cap_change_pct'] = df_tokens.apply(
        lambda row: ((row['current_market_cap'] - row['peak_market_cap']) / row['peak_market_cap'] * 100)
        if pd.notnull(row['peak_market_cap']) and row['peak_market_cap'] != 0 else 0.0, axis=1
    )
    df_display['market_cap_change_pct'] = df_display['market_cap_change_pct'].apply(lambda x: f"{x:,.2f}%" if pd.notnull(x) else "N/A")

    # Filters
    st.subheader("Filtres")
    col_f1, col_f2, col_f3 = st.columns(3)
    col_f4, col_f5, col_f6 = st.columns(3)
    
    filter_key = f"{title.replace(' ', '_')}_"
    
    with col_f1:
        creator_filter = st.multiselect(
            "Filtrer par Adresse Créateur",
            options=df_display['creator_address'].unique(),
            default=[],
            key=f"{filter_key}creator"
        )
    with col_f2:
        symbol_filter = st.multiselect(
            "Filtrer par Symbole Token",
            options=df_display['token_symbol'].unique(),
            default=[],
            key=f"{filter_key}symbol"
        )
    with col_f3:
        earliest_date = pd.to_datetime(df_display['launch_date'], errors='coerce').min().date()
        default_start = earliest_date if earliest_date else (datetime(2025, 9, 2).date() - timedelta(days=30))
        date_range = st.date_input(
            "Filtrer par Date de Lancement",
            value=(default_start, datetime(2025, 9, 2).date()),
            min_value=earliest_date if earliest_date else datetime(2024, 1, 1).date(),
            max_value=datetime(2025, 9, 2).date(),
            key=f"{filter_key}date"
        )
    with col_f4:
        peak_market_cap_float = df_display['peak_market_cap'].str.replace('$', '').str.replace(',', '').replace('N/A', None).astype(float)
        min_peak = peak_market_cap_float.min() if not peak_market_cap_float.isna().all() else 0.0
        max_peak = peak_market_cap_float.max() if not peak_market_cap_float.isna().all() else 0.0
        if min_peak == max_peak or pd.isna(min_peak) or pd.isna(max_peak):
            st.write(f"Peak Market Cap: Toutes les valeurs valides sont identiques ({min_peak:,.2f})")
            peak_market_cap_range = (min_peak, max_peak)
        else:
            peak_market_cap_range = st.slider(
                "Filtrer par Peak Market Cap ($)",
                min_value=float(min_peak),
                max_value=float(max_peak),
                value=(float(min_peak), float(max_peak)),
                step=100.0,
                key=f"{filter_key}peak"
            )
    with col_f5:
        survival_time_float = df_display['survival_time_hours'].str.replace(',', '').replace('N/A', None).astype(float)
        min_survival = survival_time_float.min() if not survival_time_float.isna().all() else 0.0
        max_survival = survival_time_float.max() if not survival_time_float.isna().all() else 0.0
        if min_survival == max_survival or pd.isna(min_survival) or pd.isna(max_survival):
            st.write(f"Temps de Survie: Toutes les valeurs valides sont identiques ({min_survival:,.2f} heures)")
            survival_time_range = (min_survival, max_survival)
        else:
            survival_time_range = st.slider(
                "Filtrer par Temps de Survie (Heures)",
                min_value=float(min_survival),
                max_value=float(max_survival),
                value=(float(min_survival), float(max_survival)),
                step=0.1,
                key=f"{filter_key}survival"
            )
    with col_f6:
        market_cap_change_float = df_display['market_cap_change_pct'].str.replace('%', '').str.replace(',', '').replace('N/A', None).astype(float)
        min_change = market_cap_change_float.min() if not market_cap_change_float.isna().all() else 0.0
        max_change = market_cap_change_float.max() if not market_cap_change_float.isna().all() else 0.0
        if min_change == max_change or pd.isna(min_change) or pd.isna(max_change):
            st.write(f"Changement Market Cap: Toutes les valeurs valides sont identiques ({min_change:,.2f}%)")
            market_cap_change_range = (min_change, max_change)
        else:
            market_cap_change_range = st.slider(
                "Filtrer par Changement Market Cap (%)",
                min_value=float(min_change),
                max_value=float(max_change),
                value=(float(min_change), float(max_change)),
                step=1.0,
                key=f"{filter_key}change"
            )

    # Apply filters
    filtered_df = df_display
    if creator_filter:
        filtered_df = filtered_df[filtered_df['creator_address'].isin(creator_filter)]
    if symbol_filter:
        filtered_df = filtered_df[filtered_df['token_symbol'].isin(symbol_filter)]
    if len(date_range) == 2:
        start_date, end_date = date_range
        filtered_df = filtered_df[
            (pd.to_datetime(filtered_df['launch_date'], errors='coerce') >= pd.Timestamp(start_date)) &
            (pd.to_datetime(filtered_df['launch_date'], errors='coerce') <= pd.Timestamp(end_date) + pd.Timedelta(days=1))
        ]
    if not (min_peak == max_peak or pd.isna(min_peak) or pd.isna(max_peak)):
        filtered_df = filtered_df[
            (filtered_df['peak_market_cap'].str.replace('$', '').str.replace(',', '').replace('N/A', None).astype(float) >= peak_market_cap_range[0]) &
            (filtered_df['peak_market_cap'].str.replace('$', '').str.replace(',', '').replace('N/A', None).astype(float) <= peak_market_cap_range[1])
        ]
    if not (min_survival == max_survival or pd.isna(min_survival) or pd.isna(max_survival)):
        filtered_df = filtered_df[
            (filtered_df['survival_time_hours'].str.replace(',', '').replace('N/A', None).astype(float) >= survival_time_range[0]) &
            (filtered_df['survival_time_hours'].str.replace(',', '').replace('N/A', None).astype(float) <= survival_time_range[1])
        ]
    if not (min_change == max_change or pd.isna(min_change) or pd.isna(max_change)):
        filtered_df = filtered_df[
            (filtered_df['market_cap_change_pct'].str.replace('%', '').str.replace(',', '').replace('N/A', None).astype(float) >= market_cap_change_range[0]) &
            (filtered_df['market_cap_change_pct'].str.replace('%', '').str.replace(',', '').replace('N/A', None).astype(float) <= market_cap_change_range[1])
        ]

    # Select columns for display
    base_columns = [
        'token_address', 'token_name', 'token_symbol', 'creator_address',
        'launch_date', 'outcome_type', 'current_market_cap', 'peak_market_cap',
        'survival_time_hours', 'market_cap_change_pct'
    ]
    
    if show_completion_timestamp:
        display_columns = base_columns + ['bonding_curve_completed_timestamp_formatted']
        column_names = {
            'token_address': 'Adresse Token',
            'token_name': 'Nom',
            'token_symbol': 'Symbole',
            'creator_address': 'Adresse Créateur',
            'launch_date': 'Date de Lancement',
            'outcome_type': 'Résultat',
            'current_market_cap': 'Market Cap Actuelle',
            'peak_market_cap': 'Peak Market Cap',
            'survival_time_hours': 'Temps de Survie (Heures)',
            'market_cap_change_pct': 'Changement Market Cap (%)',
            'bonding_curve_completed_timestamp_formatted': 'Date de Migration'
        }
    else:
        display_columns = base_columns + ['last_updated_from_api']
        column_names = {
            'token_address': 'Adresse Token',
            'token_name': 'Nom',
            'token_symbol': 'Symbole',
            'creator_address': 'Adresse Créateur',
            'launch_date': 'Date de Lancement',
            'outcome_type': 'Résultat',
            'current_market_cap': 'Market Cap Actuelle',
            'peak_market_cap': 'Peak Market Cap',
            'survival_time_hours': 'Temps de Survie (Heures)',
            'market_cap_change_pct': 'Changement Market Cap (%)',
            'last_updated_from_api': 'Dernière MAJ API'
        }
    
    st.dataframe(
        filtered_df[display_columns].rename(columns=column_names),
        use_container_width=True
    )

    # Display count
    st.info(f"Nombre de tokens affichés: {len(filtered_df)} sur {len(df_tokens)} total")

    # Download button
    csv = filtered_df[display_columns].to_csv(index=False)
    st.download_button(
        label=f"Télécharger les données filtrées - {title}",
        data=csv,
        file_name=f"tokens_report_{title.lower().replace(' ', '_')}.csv",
        mime="text/csv",
        key=f"{filter_key}download"
    )

def main():
    st.set_page_config(page_title="Analyse des Tokens - Rapport", layout="wide")
    st.title("📊 Analyse des Tokens - Rapport")
    st.write(f"Dernière actualisation: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CEST")

    # Database path
    db_path = "early_adopter.db"
    conn = connect_to_db(db_path)

    # --- Key Indicators ---
    st.header("🔑 Indicateurs Clés")
    df_tokens = get_tokens(conn)
    df_creators = get_creator_stats(conn)

    if df_tokens.empty:
        st.warning("Aucun token trouvé dans creator_token_history.")
    else:
        # Convert datetime columns
        df_tokens['launch_date'] = pd.to_datetime(df_tokens['launch_date'], format='mixed', errors='coerce')
        df_tokens['created_at'] = pd.to_datetime(df_tokens['created_at'], format='mixed', errors='coerce')
        df_tokens['last_updated_from_api'] = pd.to_datetime(df_tokens['last_updated_from_api'], format='mixed', errors='coerce')

        # Check for unparseable dates
        if df_tokens['launch_date'].isna().any():
            st.warning("Certaines valeurs launch_date n'ont pas pu être analysées et sont définies à NaT.")

        # Separate tokens by completion status
        tokens_not_complete = df_tokens[df_tokens['is_complete'] == 0].copy()
        tokens_complete = df_tokens[df_tokens['is_complete'] == 1].copy()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Tokens", len(df_tokens))
        with col2:
            st.metric("Tokens Non Migrés", len(tokens_not_complete))
        with col3:
            st.metric("Tokens Migrés", len(tokens_complete))
        with col4:
            migration_rate = (len(tokens_complete) / len(df_tokens) * 100) if len(df_tokens) > 0 else 0
            st.metric("Taux de Migration", f"{migration_rate:.1f}%")

        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("Créateurs Uniques", len(df_creators))
        with col6:
            recent_tokens = len(df_tokens[df_tokens['launch_date'] > datetime.now() - timedelta(days=7)])
            st.metric("Tokens Lancés (7 derniers jours)", recent_tokens)
        with col7:
            top_creator = df_creators.loc[df_creators['token_count'].idxmax(), 'creator_address'] if not df_creators.empty else "N/A"
            st.metric("Top Créateur (Plus de Tokens)", top_creator[:8] + "..." if top_creator != "N/A" else "N/A")
        with col8:
            avg_survival = df_tokens['survival_time_hours'].mean() if not df_tokens['survival_time_hours'].isna().all() else 0
            st.metric("Temps de Survie Moyen", f"{avg_survival:.1f}h")

        # Display survival time charts
        st.markdown("---")
        create_survival_time_charts(df_tokens)
        
        # Display creator analysis
        st.markdown("---")
        create_creator_analysis_table(df_tokens)
        
        # Display the two tables
        st.markdown("---")
        
        # Table 1: Non-migrated tokens (is_complete = 0)
        display_token_table(tokens_not_complete, "Tokens Non Migrés", show_completion_timestamp=False)
        
        st.markdown("---")
        
        # Table 2: Migrated tokens (is_complete = 1)  
        display_token_table(tokens_complete, "Tokens Migrés", show_completion_timestamp=True)

    # Close database connection
    conn.close()

if __name__ == "__main__":
    main()