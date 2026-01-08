import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import date

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Commander Tracker", 
    page_icon="🐉", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONEXÃO COM SUPABASE ---
# Tenta pegar dos segredos (Nuvem), senão avisa o erro
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("⚠️ Erro de Configuração: As chaves do Supabase não foram encontradas.")
    st.info("No Streamlit Cloud, adicione em 'Advanced Settings' > 'Secrets'.")
    st.stop()

@st.cache_resource
def init_connection():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Erro ao conectar no Supabase: {e}")
        return None

supabase = init_connection()

# --- CARREGAMENTO DE DADOS ---
@st.cache_data(ttl=600) # Atualiza o cache a cada 10 minutos
def get_data():
    if not supabase: return None, None, None
    
    # Busca Jogadores
    res_players = supabase.table("players").select("*").order("name").execute()
    df_players = pd.DataFrame(res_players.data)
    
    # Busca Decks (Trazendo o nome do dono junto para facilitar)
    # Precisamos fazer um join manual ou view, mas aqui vamos puxar tudo e mapar no pandas
    res_decks = supabase.table("decks").select("*").execute()
    df_decks = pd.DataFrame(res_decks.data)
    
    # Busca Histórico (View)
    res_history = supabase.table("view_full_history").select("*").order("date", desc=True).limit(10000).execute()
    df_history = pd.DataFrame(res_history.data)
    
    return df_players, df_decks, df_history

df_players, df_decks, df_history = get_data()

# Prepara lista de decks formatada: "Nome do Deck (Dono)"
# Isso ajuda a selecionar o deck certo sem precisar de filtros complexos no formulário
if not df_decks.empty and not df_players.empty:
    # Cria mapa de ID -> Nome do Jogador
    player_map = dict(zip(df_players['player_id'], df_players['name']))
    df_decks['owner_name'] = df_decks['player_id'].map(player_map)
    df_decks['display_name'] = df_decks['deck_name'] + " (" + df_decks['owner_name'].astype(str) + ")"
    df_decks = df_decks.sort_values('display_name')

# --- INTERFACE ---
st.title("🐉 Commander Tracker")

menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "📜 Histórico", "➕ Registrar Partida"])

# ==============================================================================
# ABA 1: DASHBOARD
# ==============================================================================
if menu == "📊 Dashboard":
    st.header("Estatísticas do Grupo")
    
    if df_history.empty:
        st.warning("Nenhum dado encontrado.")
    else:
        # Filtros
        col1, col2 = st.columns(2)
        with col1:
            if 'date' in df_history.columns:
                anos = sorted(pd.to_datetime(df_history['date']).dt.year.unique(), reverse=True)
                ano_sel = st.selectbox("📅 Filtrar por Ano", ["Todos"] + list(anos))
        
        # Aplica Filtro
        df_filtered = df_history.copy()
        if ano_sel != "Todos":
            df_filtered = df_filtered[pd.to_datetime(df_filtered['date']).dt.year == ano_sel]

        # KPIs
        total_jogos = df_filtered['match_id'].nunique()
        # Conta vitórias (considerando que is_winner é booleano)
        total_vitorias = df_filtered[df_filtered['is_winner'] == True].shape[0]
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Total de Partidas", total_jogos)
        k2.metric("Jogadores Ativos", df_filtered['player_name'].nunique())
        k3.metric("Decks Diferentes Usados", df_filtered['deck_name'].nunique())
        
        st.divider()
        
        # Gráficos
        c1, c2 = st.columns([1, 1])
        
        with c1:
            st.subheader("🏆 Top Win Rate (%)")
            st.caption("Mínimo de 5 jogos no período")
            
            stats = df_filtered.groupby('player_name').agg(
                jogos=('match_id', 'nunique'),
                vitorias=('is_winner', 'sum')
            ).reset_index()
            
            stats = stats[stats['jogos'] >= 5]
            stats['win_rate'] = (stats['vitorias'] / stats['jogos']) * 100
            stats = stats.sort_values('win_rate', ascending=False).head(10)
            
            fig_wr = px.bar(stats, x='win_rate', y='player_name', orientation='h',
                            text_auto='.1f', color='win_rate', color_continuous_scale='RdYlGn')
            fig_wr.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title="Win Rate %")
            st.plotly_chart(fig_wr, use_container_width=True)
            
        with c2:
            st.subheader("🎨 Cores Mais Jogadas")
            if 'color_identity' in df_filtered.columns:
                cores = df_filtered['color_identity'].replace('', 'Incolor').value_counts().head(10).reset_index()
                cores.columns = ['Identity', 'Count']
                fig_pie = px.pie(cores, values='Count', names='Identity', hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)

# ==============================================================================
# ABA 2: HISTÓRICO
# ==============================================================================
elif menu == "📜 Histórico":
    st.header("Histórico de Partidas")
    
    search = st.text_input("🔍 Buscar (Jogador, Deck ou Data)", placeholder="Ex: Atraxa")
    
    view_df = df_history.copy()
    
    # Filtro de busca simples
    if search:
        mask = view_df.astype(str).apply(lambda x: x.str.contains(search, case=False)).any(axis=1)
        view_df = view_df[mask]
    
    # Seleção de colunas para ficar bonito
    cols_show = ['match_id', 'date', 'player_name', 'deck_name', 'is_winner', 'turn_eliminated', 'eliminated_by']
    # Renomear para português na exibição
    view_df_show = view_df[cols_show].rename(columns={
        'match_id': 'ID', 'date': 'Data', 'player_name': 'Jogador', 
        'deck_name': 'Deck', 'is_winner': 'Venceu?', 
        'turn_eliminated': 'Turno', 'eliminated_by': 'Eliminado Por'
    })
    
    st.dataframe(view_df_show, use_container_width=True, hide_index=True, height=600)

# ==============================================================================
# ABA 3: REGISTRO (COM SENHA)
# ==============================================================================
elif menu == "➕ Registrar Partida":
    st.header("Registrar Novo Jogo")
    
    # --- TRAVA DE SEGURANÇA ---
    # Defina a senha do seu grupo aqui. 
    # Para ser ultra seguro, poderia estar em st.secrets, mas hardcoded aqui funciona para grupos pequenos.
    SENHA_GRUPO = "mtg2026" 
    
    senha_input = st.text_input("🔑 Senha do Grupo", type="password")
    
    if senha_input == SENHA_GRUPO:
        st.success("Acesso Liberado!")
        
        with st.form("form_registro"):
            c1, c2 = st.columns(2)
            data_jogo = c1.date_input("Data do Jogo", date.today())
            notas = c2.text_input("Notas / Observações", "")
            
            st.subheader("Participantes (Mesa de 4)")
            
            # Listas para os Selectbox
            lista_jogadores = [""] + df_players['name'].tolist()
            lista_decks_formatada = [""] + df_decks['display_name'].tolist()
            
            participantes = []
            
            # Loop para criar 4 linhas de entrada
            for i in range(4):
                col_p, col_d, col_v, col_t = st.columns([1.5, 2, 0.5, 0.8])
                
                # Seleção
                p_nome = col_p.selectbox(f"Jogador {i+1}", lista_jogadores, key=f"p_{i}")
                d_display = col_d.selectbox(f"Deck {i+1}", lista_decks_formatada, key=f"d_{i}")
                venceu = col_v.checkbox("👑", key=f"win_{i}", help="Marque se venceu")
                turno = col_t.number_input(f"Turno", min_value=0, value=0, key=f"turn_{i}", help="Turno da eliminação")
                
                participantes.append({
                    'nome': p_nome,
                    'deck_display': d_display,
                    'venceu': venceu,
                    'turno': turno
                })
            
            submit = st.form_submit_button("💾 Salvar Partida no Banco")
            
            if submit:
                # 1. Validação
                validos = [p for p in participantes if p['nome'] != "" and p['deck_display'] != ""]
                
                if len(validos) < 2:
                    st.error("❌ Selecione pelo menos 2 jogadores e seus decks.")
                else:
                    try:
                        # 2. Inserir Partida (Matches)
                        # O ID será gerado automaticamente pelo banco (auto-incremento)
                        dados_partida = {
                            "date": str(data_jogo),
                            "notes": notas
                        }
                        res_match = supabase.table("matches").insert(dados_partida).execute()
                        
                        # Recupera o ID gerado
                        novo_match_id = res_match.data[0]['match_id']
                        
                        # 3. Preparar Participantes
                        dados_participantes = []
                        ranking_count = 1
                        
                        for p in validos:
                            # Recuperar IDs reais baseado nos nomes
                            pid = df_players[df_players['name'] == p['nome']]['player_id'].values[0]
                            did = df_decks[df_decks['display_name'] == p['deck_display']]['deck_id'].values[0]
                            
                            dados_participantes.append({
                                "match_id": novo_match_id,
                                "player_id": pid,
                                "deck_id": did,
                                "is_winner": p['venceu'],
                                "turn_eliminated": int(p['turno']),
                                "rank": 1 if p['venceu'] else 0 # Lógica simples de rank
                            })
                            
                        # 4. Inserir Participantes
                        supabase.table("match_participants").insert(dados_participantes).execute()
                        
                        st.balloons()
                        st.success(f"✅ Partida registrada com sucesso! ID: {novo_match_id}")
                        st.cache_data.clear() # Limpa cache para atualizar gráficos
                        
                    except Exception as e:
                        st.error(f"Erro ao gravar no banco: {e}")
    
    elif senha_input != "":
        st.warning("Senha incorreta.")
    else:
        st.info("Digite a senha para habilitar o formulário.")

# Rodapé
st.markdown("---")

st.caption("Desenvolvido com Python, Streamlit e Supabase 🚀")
