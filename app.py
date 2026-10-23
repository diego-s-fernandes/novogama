"""
Painel eleitoral de Novo Gama (GO) — Vereadores 2024.

Interface em Streamlit com foco em leitura rápida, comparação honesta e
transparência da geolocalização. A base inclui todos os candidatos do registro
do TSE (eleitos, suplentes e não eleitos), não apenas os vencedores.
"""
from __future__ import annotations

import html
import math
from typing import Dict, Optional

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from branca.colormap import LinearColormap
from folium.plugins import Fullscreen, MeasureControl
from streamlit_folium import st_folium

from src.analytics import (
    aggregate_candidate_by_bairro,
    aggregate_candidate_by_local,
    aggregate_candidate_by_section,
    approximate_locations,
    build_party_summary,
    build_quality_report,
    coordinate_provenance,
    csv_bytes,
    filter_candidates,
    format_int,
    format_pct,
    get_benchmarks,
    get_totals,
)
from src.config import (
    DEFAULT_CANDIDATO_NR,
    DEFAULT_ZOOM,
    GRID_COLOR,
    PRIMARY_COLOR,
    SECONDARY_COLOR,
    STATUS_COLORS,
    STATUS_ICONS,
    TEXT_COLOR,
    TILE_OPTIONS,
)
from src.data_loader import (
    ElectionData,
    build_pipeline_from_files,
    download_and_process_tse_data,
    load_or_init_dataset,
)

# ---------------------------------------------------------------------------
# Configuração da página e estilo
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Vereadores de Novo Gama — 2024",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #0f172a;
            --muted: #475569;
            --line: #e2e8f0;
            --blue: #1d4ed8;
            --surface: #ffffff;
            --bg: #f8fafc;
        }
        html, body, [class*="css"] {
            font-family: "Segoe UI", "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
            -webkit-font-smoothing: antialiased;
        }
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2.5rem;
            max-width: 1440px;
        }
        h1 { font-size: clamp(1.4rem, 4vw, 2.1rem); color: var(--ink); letter-spacing: -0.02em; margin-bottom: 0.2rem; }
        h2 { font-size: clamp(1.2rem, 3.2vw, 1.7rem); color: var(--ink); letter-spacing: -0.02em; }
        h3 { font-size: clamp(1.05rem, 2.6vw, 1.35rem); color: var(--ink); }
        h4 { font-size: clamp(0.95rem, 2.2vw, 1.15rem); color: var(--ink); }

        [data-testid="stMetric"] {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 12px 14px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, .04);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        [data-testid="stMetric"]:hover {
            box-shadow: 0 3px 8px rgba(15, 23, 42, .08);
        }
        [data-testid="stMetricLabel"] p {
            font-size: .75rem;
            color: var(--muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: .03em;
        }
        [data-testid="stMetricValue"] {
            color: var(--ink);
            font-size: clamp(1.25rem, 2.8vw, 1.6rem);
            font-weight: 700;
        }
        .status-banner {
            background: var(--surface);
            border: 1px solid var(--line);
            border-left: 5px solid var(--blue);
            border-radius: 12px;
            padding: 12px 16px;
            margin: 6px 0 14px 0;
            color: var(--ink);
            font-size: .94rem;
            line-height: 1.45;
            box-shadow: 0 1px 2px rgba(15, 23, 42, .03);
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 3px 9px;
            border-radius: 999px;
            font-size: .76rem;
            font-weight: 700;
            letter-spacing: .02em;
            text-transform: uppercase;
        }
        .insight-box {
            background: var(--bg);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 11px 14px;
            color: var(--muted);
            font-size: .90rem;
            line-height: 1.5;
        }
        .insight-box b { color: var(--ink); }
        .small-note {
            color: #64748b;
            font-size: .82rem;
            line-height: 1.45;
        }

        /* Abas com scroll horizontal suave e responsivo no mobile */
        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
            overflow-x: auto;
            flex-wrap: nowrap;
            scrollbar-width: thin;
            -webkit-overflow-scrolling: touch;
            padding-bottom: 2px;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 8px 13px;
            border-radius: 8px 8px 0 0;
            font-weight: 600;
            font-size: 0.90rem;
            white-space: nowrap;
            flex-shrink: 0;
        }

        /* Tabelas e DataFrames responsivos */
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--line);
            border-radius: 10px;
            width: 100% !important;
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }

        /* Gráficos Plotly fluidos */
        .js-plotly-plot, .plot-container {
            width: 100% !important;
            max-width: 100% !important;
        }

        /* Iframe do mapa */
        iframe[title="streamlit_folium.st_folium"] {
            width: 100% !important;
            max-width: 100% !important;
            border-radius: 12px !important;
            border: 1px solid var(--line) !important;
        }

        /* -------------------------------------------------------------------
           Adaptações responsivas específicas para Mobile / Tablet (< 768px)
           ------------------------------------------------------------------- */
        @media (max-width: 768px) {
            .block-container {
                padding-top: 0.8rem !important;
                padding-bottom: 2rem !important;
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
            }

            /* Transforma os 4 cards de KPIs em grade 2x2 no celular */
            [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                gap: 8px !important;
            }
            [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="column"] {
                width: 100% !important;
                min-width: 0 !important;
                flex: unset !important;
            }

            /* Colunas normais empilham verticalmente no celular */
            [data-testid="stHorizontalBlock"]:not(:has([data-testid="stMetric"])) {
                flex-direction: column !important;
                gap: 12px !important;
            }
            [data-testid="stHorizontalBlock"]:not(:has([data-testid="stMetric"])) > [data-testid="column"] {
                width: 100% !important;
                min-width: 100% !important;
                flex: 1 1 100% !important;
            }

            [data-testid="stMetric"] {
                padding: 9px 11px !important;
                border-radius: 10px !important;
            }
            [data-testid="stMetricValue"] {
                font-size: 1.25rem !important;
            }

            .status-banner {
                padding: 10px 12px !important;
                font-size: 0.86rem !important;
                margin-bottom: 10px !important;
            }
            .insight-box {
                padding: 9px 12px !important;
                font-size: 0.84rem !important;
            }

            /* Altura do mapa adaptada no celular para rolagem natural */
            iframe[title="streamlit_folium.st_folium"] {
                height: 420px !important;
                min-height: 380px !important;
            }

            .stTabs [data-baseweb="tab"] {
                font-size: 0.82rem !important;
                padding: 6px 10px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_data() -> ElectionData:
    return load_or_init_dataset()


def reload_data() -> None:
    st.cache_data.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Formatação e componentes visuais
# ---------------------------------------------------------------------------
def status_pill(status: str) -> str:
    color = STATUS_COLORS.get(status, "#64748b")
    icon = STATUS_ICONS.get(status, "·")
    return (
        f'<span class="status-pill" style="background:{color}14;color:{color};'
        f'border:1px solid {color}33;">{icon} {html.escape(status)}</span>'
    )


def candidate_status_text(cand: pd.Series, benchmarks: Dict[str, object]) -> str:
    status = str(cand["SITUACAO"])
    party = html.escape(str(cand["SG_PARTIDO"]))
    nome = html.escape(str(cand["NM_URNA_CANDIDATO"]))
    if status == "Eleito":
        return (
            f"<b>{nome}</b> foi <b>eleito</b> pelo {party} "
            f"({html.escape(str(cand.get('ELEITO_POR', '—')))}). "
            f"Ocupa uma das <b>{format_int(benchmarks.get('vagas', 0))} vagas</b> "
            "da Câmara Municipal."
        )
    if status == "Suplente":
        return (
            f"<b>{nome}</b> ficou como <b>suplente</b> pelo {party}. "
            "Não ocupa vaga na legislatura, mas pode ser convocado."
        )
    if status == "Não eleito":
        return (
            f"<b>{nome}</b> <b>não foi eleito</b> em 2024. "
            "O painel mantém o resultado e a distribuição espacial dos votos para "
            "comparação com os candidatos eleitos."
        )
    return (
        f"<b>{nome}</b> aparece no registro do TSE, mas a situação eleitoral não "
        "foi informada (por exemplo, candidatura com número nulo)."
    )


def status_banner(cand: pd.Series, benchmarks: Dict[str, object]) -> None:
    color = STATUS_COLORS.get(str(cand["SITUACAO"]), "#64748b")
    st.markdown(
        f"""
        <div class="status-banner" style="border-left-color:{color};">
            <div style="margin-bottom:6px;">{status_pill(str(cand['SITUACAO']))}</div>
            {candidate_status_text(cand, benchmarks)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def insight_box(text: str) -> None:
    st.markdown(f'<div class="insight-box">{text}</div>', unsafe_allow_html=True)


def style_figure(fig: go.Figure, height: int = 380, showlegend: bool = False) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=16, t=24, b=16),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Segoe UI, Inter, -apple-system, sans-serif", color=TEXT_COLOR, size=11),
        showlegend=showlegend,
        hoverlabel=dict(bgcolor="white", font_size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        autosize=True,
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID_COLOR, zeroline=False, automargin=True)
    fig.update_yaxes(showgrid=False, zeroline=False, automargin=True)
    return fig


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
def render_data_management(data: ElectionData) -> None:
    st.markdown("### 🗳️ Painel eleitoral")
    st.caption("Novo Gama · GO · Vereadores · 2024")

    with st.container(border=True):
        st.markdown(f"**Base:** {data.status}")
        if data.metadata.get("gerado_em"):
            st.caption(f"Processada em {data.metadata['gerado_em'][:19].replace('T', ' ')}")
        if not data.empty:
            st.caption(
                f"{format_int(len(data.resumo))} candidatos · "
                f"{format_int(data.locais['LOCAL_KEY'].nunique())} locais · "
                f"{format_int(data.votacao[['NR_ZONA', 'NR_SECAO']].drop_duplicates().shape[0])} seções"
            )

    with st.expander("📥 Atualizar base oficial do TSE", expanded=data.empty):
        st.caption(
            "Baixa os três pacotes oficiais de 2024 (votação, locais e candidaturas). "
            "O download completo tem cerca de 170 MB."
        )
        allow_osm = st.checkbox(
            "Permitir geocodificação online para locais sem coordenada",
            value=False,
            help="Só é usada quando o TSE não traz coordenada válida para o local.",
        )
        if st.button(
            "Baixar e processar dados do TSE",
            type="primary",
            width="stretch",
        ):
            progress = st.progress(0.0, text="Iniciando download...")

            def _progress(pct: float, message: str) -> None:
                progress.progress(min(max(pct, 0.0), 1.0), text=message)

            try:
                download_and_process_tse_data(
                    progress_callback=_progress,
                    allow_network_geocode=allow_osm,
                )
                progress.progress(1.0, text="Base atualizada.")
                st.success("Dados oficiais processados com sucesso.")
                reload_data()
            except Exception as exc:  # noqa: BLE001 - feedback para o usuário
                st.error(f"Falha ao baixar/processar: {exc}")

        st.divider()
        st.markdown("**Ou envie os arquivos oficiais (.zip ou .csv):**")
        upload_vot = st.file_uploader(
            "1. Votação por seção (votacao_secao_2024_GO)",
            type=["zip", "csv"],
            key="upload_votacao",
        )
        upload_loc = st.file_uploader(
            "2. Locais de votação (eleitorado_local_votacao_2024)",
            type=["zip", "csv"],
            key="upload_locais",
        )
        upload_cand = st.file_uploader(
            "3. Candidaturas (consulta_cand_2024)",
            type=["zip", "csv"],
            key="upload_candidatos",
            help="Necessário para identificar eleitos, suplentes e não eleitos.",
        )
        if st.button(
            "Processar arquivos enviados",
            width="stretch",
            disabled=not (upload_vot and upload_loc),
        ):
            from src.config import RAW_DIR

            vot_path = RAW_DIR / upload_vot.name
            vot_path.write_bytes(upload_vot.getvalue())
            loc_path = RAW_DIR / upload_loc.name
            loc_path.write_bytes(upload_loc.getvalue())
            cand_path = None
            if upload_cand is not None:
                cand_path = RAW_DIR / upload_cand.name
                cand_path.write_bytes(upload_cand.getvalue())
            try:
                with st.spinner(
                    "Filtrando Novo Gama, validando coordenadas e cruzando as bases..."
                ):
                    build_pipeline_from_files(
                        vot_path,
                        loc_path,
                        cand_path,
                        allow_network_geocode=allow_osm,
                    )
                st.success("Arquivos processados com sucesso.")
                reload_data()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Falha ao processar os arquivos: {exc}")

    if data.empty:
        return

    st.divider()
    st.markdown("### 🔎 Filtros")

    status_options = ["Eleito", "Suplente", "Não eleito", "Sem situação"]
    status_filter = st.multiselect(
        "Situação eleitoral",
        options=status_options,
        default=status_options,
        help="Por padrão, eleitos, suplentes e não eleitos aparecem juntos.",
    )
    partidos = sorted(data.resumo["SG_PARTIDO"].dropna().unique().tolist())
    party_filter = st.multiselect(
        "Partido",
        options=partidos,
        default=[],
        help="Deixe vazio para todos os partidos.",
    )
    search = st.text_input(
        "Buscar candidato",
        placeholder="Nome de urna, nome completo ou número",
    )
    only_with_votes = st.toggle(
        "Ocultar candidatos com 0 voto",
        value=False,
        help="Mesmo com 0 voto, o candidato faz parte do registro oficial.",
    )

    filtered = filter_candidates(
        data.resumo,
        statuses=status_filter,
        partidos=party_filter,
        search=search,
    )
    if only_with_votes:
        filtered = filtered[filtered["QT_VOTOS"] > 0]

    if filtered.empty:
        st.warning("Nenhum candidato corresponde aos filtros. Exibindo todos.")
        filtered = data.resumo.copy()

    filtered = filtered.sort_values(
        ["QT_VOTOS", "NM_URNA_CANDIDATO"], ascending=[False, True]
    )
    labels = {
        str(row["NR_VOTAVEL"]): (
            f"{row['NM_URNA_CANDIDATO']} · {row['SG_PARTIDO']} · "
            f"{format_int(row['QT_VOTOS'])} votos · {row['SITUACAO']}"
        )
        for _, row in filtered.iterrows()
    }
    options_list = [str(nr) for nr in filtered["NR_VOTAVEL"].tolist()]
    default_index = 0
    target_nr = str(
        st.session_state.get("selected_candidate")
        or st.session_state.get("selected_nr")
        or DEFAULT_CANDIDATO_NR
    )
    if target_nr in options_list:
        default_index = options_list.index(target_nr)
    elif DEFAULT_CANDIDATO_NR in options_list:
        default_index = options_list.index(DEFAULT_CANDIDATO_NR)

    selected_nr = st.selectbox(
        "Candidato",
        options=options_list,
        index=default_index,
        format_func=lambda value: labels.get(value, value),
        filter_mode="contains",
        key="selected_candidate",
        help="A lista inclui candidatos eleitos, suplentes e não eleitos.",
    )
    st.caption(
        f"{format_int(len(filtered))} candidatos no filtro · "
        f"{format_int(int((filtered['SITUACAO'] == 'Não eleito').sum()))} não eleitos · "
        f"{format_int(int((filtered['SITUACAO'] == 'Eleito').sum()))} eleitos"
    )

    st.divider()
    st.markdown("### 🗺️ Mapa")
    tile_label = st.selectbox("Estilo do mapa", options=list(TILE_OPTIONS.keys()), index=0)
    show_approx = st.checkbox(
        "Mostrar locais com coordenada aproximada",
        value=True,
        help="Aparecem com contorno tracejado e são listados na aba de qualidade.",
    )
    show_zero = st.checkbox(
        "Mostrar locais onde o candidato teve 0 voto",
        value=True,
    )

    with st.expander("ℹ️ Como ler este painel"):
        st.markdown(
            """
            - **Votos válidos** = votos nominais + votos de legenda. Brancos e nulos ficam fora.
            - **Eleito** segue a situação oficial do TSE (`DS_SIT_TOT_TURNO`), que considera
              quociente partidário e média. Não é uma simples lista dos mais votados.
            - **Um ponto no mapa = um local de votação.** Diversas seções (urnas) podem
              funcionar no mesmo prédio; o detalhamento por seção fica na aba
              *Locais e seções*.
            - **Cor do ponto** = participação do candidato nos votos válidos do local.
              **Tamanho** = volume de votos. **Contorno tracejado** = coordenada aproximada.
            """
        )

    st.session_state["map_options"] = {
        "tile_label": tile_label,
        "show_approx": show_approx,
        "show_zero": show_zero,
    }
    st.session_state["selected_nr"] = selected_nr


# ---------------------------------------------------------------------------
# Cabeçalho e KPIs
# ---------------------------------------------------------------------------
def render_header(
    data: ElectionData, cand: pd.Series, totals: Dict, benchmarks: Dict
) -> None:
    st.title("Vereadores de Novo Gama — 2024")
    st.caption(
        "Votação nominal por seção e local de votação · 1º turno · "
        "Fonte: Repositório de Dados Abertos do TSE. "
        "A base inclui eleitos, suplentes e não eleitos."
    )

    status_banner(cand, benchmarks)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Votos do candidato",
        format_int(cand["QT_VOTOS"]),
        help="Total de votos nominais recebidos em Novo Gama no 1º turno.",
    )
    col2.metric(
        "Posição na votação",
        f"{format_int(cand['RANKING'])}º",
        help=f"Entre {format_int(benchmarks.get('n_candidatos', 0))} candidatos do registro do TSE.",
    )
    col3.metric(
        "% dos votos válidos",
        format_pct(cand["PCT_VALIDOS"], 2),
        help="Votos do candidato ÷ (votos nominais + votos de legenda).",
    )
    col4.metric(
        "Locais com voto",
        f"{format_int(cand['QTD_LOCAIS_COM_VOTO'])} / {format_int(totals['n_locais'])}",
        help="Locais de votação em que o candidato recebeu ao menos 1 voto.",
    )

    st.caption(
        f"Situação: **{cand['SITUACAO']}** · Partido: **{cand['SG_PARTIDO']}** · "
        f"{format_int(cand['QTD_SECOES_COM_VOTO'])} de {format_int(totals['n_secoes'])} seções com voto · "
        f"Melhor local: **{cand['MELHOR_LOCAL'] or '—'}** "
        f"({format_int(cand['MELHOR_LOCAL_VOTOS'])} votos)."
    )


def render_insight(cand: pd.Series, benchmarks: Dict) -> None:
    corte = int(benchmarks.get("corte_eleitos", 0))
    maior_nao = int(benchmarks.get("maior_nao_eleito", 0))
    votos = int(cand["QT_VOTOS"])
    if cand["SITUACAO"] == "Eleito":
        if votos < maior_nao:
            text = (
                f"<b>Eleito com {format_int(votos)} votos</b>, abaixo da maior votação "
                f"de um candidato não eleito ({format_int(maior_nao)}). Isso é possível "
                "porque a eleição proporcional distribui as vagas pelo quociente "
                "partidário, e não apenas pela ordem geral de votos."
            )
        else:
            text = (
                f"<b>Eleito com {format_int(votos)} votos.</b> O menor votos entre os "
                f"eleitos foi {format_int(corte)}; a média dos eleitos foi "
                f"{format_int(round(benchmarks.get('media_eleitos', 0)))}."
            )
    elif cand["SITUACAO"] == "Não eleito":
        if votos >= corte:
            text = (
                f"<b>{format_int(votos)} votos</b>, acima do menor votos entre os "
                f"eleitos ({format_int(corte)}), mas o candidato <b>não foi eleito</b>. "
                "O quociente partidário pode favorecer candidatos de partidos com "
                "mais votos válidos no conjunto."
            )
        else:
            text = (
                f"<b>{format_int(votos)} votos.</b> O menor votos entre os eleitos foi "
                f"{format_int(corte)} e a maior votação entre os não eleitos foi "
                f"{format_int(maior_nao)}. A distância para o corte foi de "
                f"{format_int(max(corte - votos, 0))} votos."
            )
    elif cand["SITUACAO"] == "Suplente":
        text = (
            f"<b>Suplente com {format_int(votos)} votos.</b> A posição na lista do "
            "partido importa: suplentes podem assumir em caso de vacância."
        )
    else:
        text = (
            f"<b>{format_int(votos)} votos.</b> A situação eleitoral não foi informada "
            "no registro do TSE para este número."
        )
    insight_box(text)


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def chart_top_locais(locais: pd.DataFrame, top_n: int = 15) -> go.Figure:
    plot = locais.head(top_n).copy().sort_values("VOTOS_CANDIDATO", ascending=True)
    plot["TEXTO"] = plot["VOTOS_CANDIDATO"].map(format_int)
    plot["HOVER_BAIRRO"] = plot["NM_BAIRRO"].fillna("—")
    plot["HOVER_LOCAL"] = plot["PCT_CANDIDATO_NO_LOCAL"].map(lambda v: format_pct(v, 1))
    plot["HOVER_CAND"] = plot["PCT_DO_TOTAL_CANDIDATO"].map(lambda v: format_pct(v, 1))
    plot["HOVER_VALIDOS"] = plot["VOTOS_VALIDOS_LOCAL"].map(format_int)
    plot["HOVER_SECOES"] = plot["QTD_SECOES"].map(format_int)
    plot["HOVER_ELEITORADO"] = plot["ELEITORADO"].map(format_int)

    fig = px.bar(
        plot,
        x="VOTOS_CANDIDATO",
        y="NM_LOCVOT",
        orientation="h",
        text="TEXTO",
        custom_data=[
            "HOVER_BAIRRO",
            "HOVER_LOCAL",
            "HOVER_CAND",
            "HOVER_VALIDOS",
            "HOVER_SECOES",
            "HOVER_ELEITORADO",
        ],
    )
    fig.update_traces(
        marker_color=PRIMARY_COLOR,
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Bairro: %{customdata[0]}<br>"
            "Votos no local: <b>%{x}</b><br>"
            "% dos válidos no local: %{customdata[1]}<br>"
            "% do total do candidato: %{customdata[2]}<br>"
            "Votos válidos no local: %{customdata[3]}<br>"
            "Seções: %{customdata[4]} · Eleitorado: %{customdata[5]}"
            "<extra></extra>"
        ),
    )
    fig.update_layout(xaxis_title=None, yaxis_title=None, bargap=0.28)
    fig.update_yaxes(
        categoryorder="array",
        categoryarray=plot["NM_LOCVOT"].tolist(),
        tickfont=dict(size=11),
    )
    fig.update_xaxes(title=None, rangemode="tozero")
    return style_figure(fig, height=max(380, len(plot) * 27))


def chart_benchmark(cand: pd.Series, benchmarks: Dict) -> go.Figure:
    rows = pd.DataFrame(
        [
            ["Candidato", int(cand["QT_VOTOS"]), PRIMARY_COLOR],
            ["Menor votação entre eleitos", int(benchmarks.get("corte_eleitos", 0)), "#cbd5e1"],
            ["Maior votação entre não eleitos", int(benchmarks.get("maior_nao_eleito", 0)), "#e2e8f0"],
            ["Média dos eleitos", int(round(benchmarks.get("media_eleitos", 0))), "#cbd5e1"],
        ],
        columns=["ROTULO", "VOTOS", "COR"],
    )
    rows["TEXTO"] = rows["VOTOS"].map(format_int)
    rows = rows.iloc[::-1].reset_index(drop=True)

    fig = go.Figure(
        go.Bar(
            x=rows["VOTOS"],
            y=rows["ROTULO"],
            orientation="h",
            marker_color=rows["COR"],
            text=rows["TEXTO"],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x} votos<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis_title=None,
        yaxis_title=None,
        bargap=0.35,
        xaxis=dict(range=[0, max(rows["VOTOS"].max() * 1.22, 10)]),
    )
    fig.update_yaxes(tickfont=dict(size=11))
    return style_figure(fig, height=300)


def chart_bairros(bairros: pd.DataFrame, top_n: int = 10) -> go.Figure:
    plot = bairros.head(top_n).copy().sort_values("VOTOS_CANDIDATO", ascending=True)
    plot["TEXTO"] = plot["VOTOS_CANDIDATO"].map(format_int)
    plot["HOVER_PCT"] = plot["PCT_LOCAL"].map(lambda v: format_pct(v, 1))
    plot["HOVER_LOCAIS"] = plot["LOCAIS"].map(format_int)
    fig = px.bar(
        plot,
        x="VOTOS_CANDIDATO",
        y="NM_BAIRRO",
        orientation="h",
        text="TEXTO",
        custom_data=["HOVER_PCT", "HOVER_LOCAIS"],
    )
    fig.update_traces(
        marker_color=SECONDARY_COLOR,
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "<b>%{y}</b><br>Votos: <b>%{x}</b><br>"
            "% dos válidos no bairro: %{customdata[0]}<br>"
            "Locais: %{customdata[1]}<extra></extra>"
        ),
    )
    fig.update_layout(xaxis_title=None, yaxis_title=None, bargap=0.3)
    fig.update_yaxes(
        categoryorder="array",
        categoryarray=plot["NM_BAIRRO"].tolist(),
        tickfont=dict(size=11),
    )
    fig.update_xaxes(title=None, rangemode="tozero")
    return style_figure(fig, height=max(320, len(plot) * 28))


def chart_status_distribution(resumo: pd.DataFrame, cand: pd.Series) -> go.Figure:
    order = ["Eleito", "Suplente", "Não eleito", "Sem situação"]
    plot = resumo.copy()
    fig = px.strip(
        plot,
        x="QT_VOTOS",
        y="SITUACAO",
        color="SITUACAO",
        color_discrete_map=STATUS_COLORS,
        category_orders={"SITUACAO": order},
        hover_name="NM_URNA_CANDIDATO",
        hover_data={"SG_PARTIDO": True, "QT_VOTOS": True, "SITUACAO": False},
        height=320,
    )
    fig.update_traces(marker=dict(size=7, opacity=0.6, line=dict(width=0)))
    fig.add_vline(
        x=int(cand["QT_VOTOS"]),
        line_width=1.5,
        line_dash="dash",
        line_color="#dc2626",
        annotation_text="Candidato",
        annotation_position="top",
        annotation_font_color="#dc2626",
    )
    fig.add_trace(
        go.Scatter(
            x=[int(cand["QT_VOTOS"])],
            y=[cand["SITUACAO"]],
            mode="markers",
            marker=dict(
                symbol="star", size=18, color="#dc2626", line=dict(width=1, color="white")
            ),
            hovertemplate="<b>Candidato selecionado</b><br>%{x} votos<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(xaxis_title="Votos nominais", yaxis_title=None, showlegend=False)
    fig.update_yaxes(tickfont=dict(size=11))
    return style_figure(fig, height=330)


def chart_party_seats(resumo: pd.DataFrame) -> go.Figure:
    party = build_party_summary(resumo)
    party = party[party["ELEITOS"] > 0].sort_values("ELEITOS", ascending=True)
    party["TEXTO"] = party["ELEITOS"].map(format_int)
    fig = px.bar(
        party,
        x="ELEITOS",
        y="SG_PARTIDO",
        orientation="h",
        text="TEXTO",
        custom_data=["NM_PARTIDO", "VOTOS"],
    )
    fig.update_traces(
        marker_color=PRIMARY_COLOR,
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "<b>%{y}</b> — %{customdata[0]}<br>"
            "Eleitos: <b>%{x}</b><br>Votos totais: %{customdata[1]:,}<extra></extra>"
        ),
    )
    fig.update_layout(xaxis_title=None, yaxis_title=None, bargap=0.35)
    fig.update_xaxes(title=None, rangemode="tozero", dtick=1)
    return style_figure(fig, height=max(280, len(party) * 30))


# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------
TILE_ATTR = {
    "Ruas (OpenStreetMap)": "© OpenStreetMap contributors",
    "Relevo (OpenTopoMap)": "© OpenStreetMap contributors, SRTM · © OpenTopoMap (CC-BY-SA)",
    "Satélite (Esri World Imagery)": "Esri, Maxar, Earthstar Geographics",
}


def _popup_html(
    row: pd.Series,
    sections: pd.DataFrame,
    candidate_label: str,
    candidate_total: int,
) -> str:
    section_rows = sections[
        sections["LOCAL_KEY"].eq(row["LOCAL_KEY"])
    ].sort_values("NR_SECAO")
    rows_html = "".join(
        f"<tr>"
        f"<td style='padding:2px 6px;'>{int(sec['NR_SECAO'])}</td>"
        f"<td style='padding:2px 6px;text-align:right;'>{format_int(sec['VOTOS_CANDIDATO'])}</td>"
        f"<td style='padding:2px 6px;text-align:right;'>{format_pct(sec['PCT_CANDIDATO_NO_SECAO'], 1)}</td>"
        f"<td style='padding:2px 6px;text-align:right;'>{format_int(sec['QT_ELEITOR_SECAO'])}</td>"
        f"</tr>"
        for _, sec in section_rows.iterrows()
    )
    if not rows_html:
        rows_html = (
            "<tr><td colspan='4' style='padding:6px;'>Sem seções identificadas.</td></tr>"
        )

    pct_total = (
        row["VOTOS_CANDIDATO"] / candidate_total * 100.0 if candidate_total else 0.0
    )
    approx = (
        "Sim — contorno tracejado"
        if bool(row["COORD_APROXIMADA"])
        else "Não — coordenada oficial do TSE"
    )
    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;width:min(340px, 82vw);max-width:100%;color:#0f172a;">
        <div style="font-size:14px;font-weight:700;margin-bottom:2px;">🏫 {html.escape(str(row['NM_LOCVOT']))}</div>
        <div style="color:#64748b;font-size:11px;margin-bottom:8px;">
            {html.escape(str(row['DS_ENDERECO']))}<br>
            {html.escape(str(row['NM_BAIRRO']))} · Zona {int(row['NR_ZONA'])}
        </div>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px;margin-bottom:8px;">
            <div><b>{html.escape(candidate_label)}</b></div>
            <div>Votos no local: <b style="color:#dc2626;">{format_int(row['VOTOS_CANDIDATO'])}</b>
                ({format_pct(row['PCT_CANDIDATO_NO_LOCAL'], 1)} dos válidos)</div>
            <div>{format_pct(pct_total, 1)} do total do candidato</div>
        </div>
        <div style="font-size:11px;color:#475569;margin-bottom:4px;">
            <b>{format_int(row['QTD_SECOES'])} seção(ões)</b> · Eleitorado: {format_int(row['ELEITORADO'])} ·
            Coordenada: {float(row['NR_LATITUDE']):.5f}, {float(row['NR_LONGITUDE']):.5f}
        </div>
        <div style="font-size:11px;color:#475569;margin-bottom:6px;">
            <b>Precisão:</b> {html.escape(str(row['PRECISAO']))} — {html.escape(approx)}
        </div>
        <div style="font-size:10px;color:#64748b;margin-bottom:3px;">Votos por seção (urna):</div>
        <div style="max-height:130px;overflow-y:auto;border:1px solid #cbd5e1;border-radius:6px;">
            <table style="width:100%;border-collapse:collapse;font-size:11px;">
                <thead>
                    <tr style="background:#f1f5f9;color:#475569;">
                        <th style="padding:3px 6px;text-align:left;">Seção</th>
                        <th style="padding:3px 6px;text-align:right;">Votos</th>
                        <th style="padding:3px 6px;text-align:right;">% local</th>
                        <th style="padding:3px 6px;text-align:right;">Eleitorado</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
    </div>
    """


def _tooltip_html(row: pd.Series, candidate_total: int) -> str:
    pct_total = (
        row["VOTOS_CANDIDATO"] / candidate_total * 100.0 if candidate_total else 0.0
    )
    approx = " · ≈ aproximado" if bool(row["COORD_APROXIMADA"]) else ""
    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;max-width:320px;">
        <b style="font-size:13px;">🏫 {html.escape(str(row['NM_LOCVOT']))}</b><br>
        <span style="color:#64748b;">{html.escape(str(row['NM_BAIRRO']))}</span><br>
        <b>{format_int(row['VOTOS_CANDIDATO'])} votos</b> · {format_pct(row['PCT_CANDIDATO_NO_LOCAL'], 1)} dos válidos<br>
        {format_pct(pct_total, 1)} do total do candidato · {format_int(row['QTD_SECOES'])} seções<br>
        <span style="color:#64748b;">{html.escape(str(row['PRECISAO']))}{approx}</span>
    </div>
    """


def _map_legend(max_votos: int, max_share: float) -> str:
    base_dot = (
        "display:inline-block;border-radius:50%;background:#93c5fd;"
        "border:1px solid #1e3a8a;vertical-align:middle;margin-right:5px;"
    )
    return f"""
    <style>
    .map-legend-box {{
        position: fixed;
        right: 14px;
        bottom: 20px;
        z-index: 9999;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid #cbd5e1;
        border-radius: 10px;
        padding: 8px 11px;
        font-family: 'Segoe UI', -apple-system, sans-serif;
        font-size: 11px;
        color: #0f172a;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.16);
        line-height: 1.4;
        max-width: 220px;
        backdrop-filter: blur(4px);
    }}
    @media (max-width: 600px) {{
        .map-legend-box {{
            right: 6px;
            bottom: 8px;
            padding: 5px 8px;
            font-size: 10px;
            max-width: 155px;
            background: rgba(255, 255, 255, 0.94);
        }}
        .map-legend-box .legend-bar {{
            width: 130px !important;
        }}
    }}
    </style>
    <div class="map-legend-box">
        <div style="font-weight:700;font-size:11px;margin-bottom:2px;">Legenda do mapa</div>
        <div style="font-size:10px;color:#475569;">Tamanho = votos</div>
        <div style="margin:2px 0;">
            <span style="{base_dot}width:6px;height:6px;"></span>
            <span style="font-size:10px;">poucos</span>
            <span style="{base_dot}width:14px;height:14px;margin-left:6px;"></span>
            <span style="font-size:10px;">{format_int(max_votos)}</span>
        </div>
        <div style="font-size:10px;color:#475569;margin-top:4px;">Cor = % dos válidos</div>
        <div class="legend-bar" style="height:7px;width:170px;border-radius:999px;
                    background:linear-gradient(90deg,#eff6ff,#93c5fd,#1d4ed8);
                    margin:3px 0 2px 0;"></div>
        <div class="legend-bar" style="display:flex;justify-content:space-between;font-size:9px;width:170px;color:#64748b;">
            <span>0%</span><span>{format_pct(max_share, 0)}</span>
        </div>
        <div style="margin-top:4px;font-size:9px;color:#475569;">
            <span style="display:inline-block;width:9px;height:9px;
                         border:2px dashed #b45309;border-radius:50%;
                         margin-right:4px;vertical-align:middle;"></span>
            tracejado = aproximado
        </div>
    </div>
    """


def create_map(
    locais: pd.DataFrame,
    sections: pd.DataFrame,
    candidate_label: str,
    candidate_total: int,
    tile_label: str,
    show_approx: bool,
    show_zero: bool,
) -> Optional[folium.Map]:
    plot = locais[locais["USAR_NO_MAPA"]].copy()
    if not show_zero:
        plot = plot[plot["VOTOS_CANDIDATO"] > 0]
    if not show_approx:
        plot = plot[~plot["COORD_APROXIMADA"]]
    if plot.empty:
        return None

    max_votos = max(int(plot["VOTOS_CANDIDATO"].max()), 1)
    max_share = max(float(plot["PCT_CANDIDATO_NO_LOCAL"].max()), 1.0)
    cmap = LinearColormap(
        ["#eff6ff", "#93c5fd", "#1d4ed8"],
        vmin=0,
        vmax=max_share,
        caption="% dos votos válidos no local",
    )

    center = [float(plot["NR_LATITUDE"].mean()), float(plot["NR_LONGITUDE"].mean())]
    m = folium.Map(
        location=center,
        zoom_start=DEFAULT_ZOOM,
        tiles=TILE_OPTIONS.get(tile_label, "OpenStreetMap"),
        attr=TILE_ATTR.get(tile_label, ""),
        control_scale=True,
        prefer_canvas=True,
    )
    Fullscreen(position="topleft", title="Tela cheia", title_cancel="Sair").add_to(m)
    MeasureControl(
        position="bottomleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
    ).add_to(m)

    fg_exact = folium.FeatureGroup(name="Locais — coordenada oficial", show=True)
    fg_approx = folium.FeatureGroup(name="Locais — coordenada aproximada", show=True)

    for _, row in plot.iterrows():
        votos = int(row["VOTOS_CANDIDATO"])
        share = float(row["PCT_CANDIDATO_NO_LOCAL"])
        radius = 4.5 if votos == 0 else 6.0 + 24.0 * math.sqrt(votos / max_votos)
        fill_color = "#e2e8f0" if votos == 0 else cmap(min(share, max_share))
        is_approx = bool(row["COORD_APROXIMADA"])
        border_color = "#b45309" if is_approx else "#1e3a8a"
        kwargs = {
            "location": [float(row["NR_LATITUDE"]), float(row["NR_LONGITUDE"])],
            "radius": radius,
            "color": border_color,
            "weight": 2.4 if is_approx else 1.6,
            "fill": True,
            "fill_color": fill_color,
            "fill_opacity": 0.78,
            "tooltip": folium.Tooltip(
                _tooltip_html(row, candidate_total), sticky=True
            ),
            "popup": folium.Popup(
                _popup_html(row, sections, candidate_label, candidate_total),
                max_width=400,
            ),
        }
        if is_approx:
            kwargs["dash_array"] = "5,4"
        folium.CircleMarker(**kwargs).add_to(fg_approx if is_approx else fg_exact)

    fg_exact.add_to(m)
    fg_approx.add_to(m)
    folium.LayerControl(collapsed=True, position="topright").add_to(m)

    m.get_root().html.add_child(folium.Element(_map_legend(max_votos, max_share)))

    lat_min, lat_max = plot["NR_LATITUDE"].min(), plot["NR_LATITUDE"].max()
    lon_min, lon_max = plot["NR_LONGITUDE"].min(), plot["NR_LONGITUDE"].max()
    m.fit_bounds(
        [
            [float(lat_min) - 0.008, float(lon_min) - 0.008],
            [float(lat_max) + 0.008, float(lon_max) + 0.008],
        ]
    )
    return m


# ---------------------------------------------------------------------------
# Abas
# ---------------------------------------------------------------------------
def tab_overview(
    data: ElectionData,
    cand: pd.Series,
    totals: Dict,
    benchmarks: Dict,
    locais: pd.DataFrame,
    bairros: pd.DataFrame,
) -> None:
    col_left, col_right = st.columns([3, 2], gap="large")
    with col_left:
        st.markdown("#### Votação por local de votação")
        st.caption(
            "Os 15 locais com mais votos do candidato. Passe o mouse para ver os detalhes."
        )
        st.plotly_chart(chart_top_locais(locais, top_n=15), width="stretch")
    with col_right:
        st.markdown("#### Onde o candidato está no páreo")
        st.caption(
            "Comparação com o menor votos entre eleitos e a maior votação entre não eleitos."
        )
        st.plotly_chart(chart_benchmark(cand, benchmarks), width="stretch")
        render_insight(cand, benchmarks)

    st.divider()
    col_a, col_b = st.columns([1, 1], gap="large")
    with col_a:
        st.markdown("#### Votos por bairro")
        st.caption("Concentração territorial da votação do candidato.")
        st.plotly_chart(chart_bairros(bairros, top_n=10), width="stretch")
    with col_b:
        st.markdown("#### Eleitos × não eleitos")
        st.caption(
            "Cada ponto é um candidato. A linha tracejada marca a votação do candidato selecionado."
        )
        st.plotly_chart(chart_status_distribution(data.resumo, cand), width="stretch")


def tab_map(
    data: ElectionData,
    cand: pd.Series,
    locais: pd.DataFrame,
    sections: pd.DataFrame,
) -> None:
    options = st.session_state.get(
        "map_options",
        {
            "tile_label": "Ruas (OpenStreetMap)",
            "show_approx": True,
            "show_zero": True,
        },
    )
    st.markdown(f"#### Distribuição espacial — **{cand['NM_URNA_CANDIDATO']}**")
    st.markdown(
        "**Tamanho** = votos no local · **Cor** = participação nos votos válidos do local · "
        "**Contorno tracejado** = coordenada aproximada. Clique em um ponto para ver as seções (urnas)."
    )

    map_obj = create_map(
        locais=locais,
        sections=sections,
        candidate_label=f"{cand['NM_URNA_CANDIDATO']} ({cand['SG_PARTIDO']})",
        candidate_total=int(cand["QT_VOTOS"]),
        tile_label=options["tile_label"],
        show_approx=bool(options["show_approx"]),
        show_zero=bool(options["show_zero"]),
    )
    if map_obj is None:
        st.warning(
            "Nenhum local atende aos filtros do mapa. Ajuste as opções na barra lateral."
        )
        return
    map_center = (
        float(locais["NR_LATITUDE"].mean()),
        float(locais["NR_LONGITUDE"].mean()),
    )
    st_folium(
        map_obj,
        height=520,
        use_container_width=True,
        returned_objects=[],
        center=map_center,
        zoom=12,
        key=f"mapa_{cand['NR_VOTAVEL']}",
    )

    approx = locais[locais["COORD_APROXIMADA"] & locais["USAR_NO_MAPA"]]
    if not approx.empty:
        with st.expander(f"⚠️ {len(approx)} local(is) com coordenada aproximada"):
            st.dataframe(
                approx[
                    ["NM_LOCVOT", "NM_BAIRRO", "PRECISAO", "COORD_OBS", "DIST_KM_CENTRO"]
                ].rename(
                    columns={
                        "NM_LOCVOT": "Local",
                        "NM_BAIRRO": "Bairro",
                        "PRECISAO": "Precisão",
                        "COORD_OBS": "Motivo",
                        "DIST_KM_CENTRO": "Distância do centro (km)",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

    st.markdown("##### Top 8 locais — leitura rápida")
    view = locais.head(8)[
        [
            "NM_LOCVOT",
            "NM_BAIRRO",
            "VOTOS_CANDIDATO",
            "PCT_CANDIDATO_NO_LOCAL",
            "PCT_DO_TOTAL_CANDIDATO",
            "QTD_SECOES",
            "PRECISAO",
        ]
    ].copy()
    view["VOTOS_CANDIDATO"] = view["VOTOS_CANDIDATO"].map(format_int)
    view["PCT_CANDIDATO_NO_LOCAL"] = view["PCT_CANDIDATO_NO_LOCAL"].map(
        lambda value: format_pct(value, 1)
    )
    view["PCT_DO_TOTAL_CANDIDATO"] = view["PCT_DO_TOTAL_CANDIDATO"].map(
        lambda value: format_pct(value, 1)
    )
    st.dataframe(
        view.rename(
            columns={
                "NM_LOCVOT": "Local",
                "NM_BAIRRO": "Bairro",
                "VOTOS_CANDIDATO": "Votos",
                "PCT_CANDIDATO_NO_LOCAL": "% válidos no local",
                "PCT_DO_TOTAL_CANDIDATO": "% do candidato",
                "QTD_SECOES": "Seções",
                "PRECISAO": "Precisão da coordenada",
            }
        ),
        width="stretch",
        hide_index=True,
    )


def tab_locais(
    data: ElectionData,
    cand: pd.Series,
    locais: pd.DataFrame,
    sections: pd.DataFrame,
) -> None:
    st.markdown("#### Desempenho por local de votação")
    st.caption(
        "Cada local reúne uma ou mais seções eleitorais (urnas). "
        "A tabela ordena pelo total de votos do candidato no local."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        bairro_filter = st.multiselect(
            "Filtrar por bairro",
            options=sorted(locais["NM_BAIRRO"].dropna().unique().tolist()),
            default=[],
        )
    with col2:
        only_votes = st.toggle("Somente locais com voto", value=False)

    view = locais.copy()
    if bairro_filter:
        view = view[view["NM_BAIRRO"].isin(bairro_filter)]
    if only_votes:
        view = view[view["VOTOS_CANDIDATO"] > 0]

    if view.empty:
        st.info("Nenhum local corresponde aos filtros.")
        return

    table = view[
        [
            "NM_LOCVOT",
            "NM_BAIRRO",
            "NR_ZONA",
            "QTD_SECOES",
            "ELEITORADO",
            "VOTOS_CANDIDATO",
            "PCT_CANDIDATO_NO_LOCAL",
            "PCT_DO_TOTAL_CANDIDATO",
            "PARTICIPACAO_LOCAL",
            "PRECISAO",
        ]
    ].copy()
    st.dataframe(
        table.rename(
            columns={
                "NM_LOCVOT": "Local de votação",
                "NM_BAIRRO": "Bairro",
                "NR_ZONA": "Zona",
                "QTD_SECOES": "Seções",
                "ELEITORADO": "Eleitorado",
                "VOTOS_CANDIDATO": "Votos",
                "PCT_CANDIDATO_NO_LOCAL": "% válidos no local",
                "PCT_DO_TOTAL_CANDIDATO": "% do candidato",
                "PARTICIPACAO_LOCAL": "Válidos / eleitorado",
                "PRECISAO": "Precisão",
            }
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "Votos": st.column_config.NumberColumn(format="localized"),
            "Eleitorado": st.column_config.NumberColumn(format="localized"),
            "Seções": st.column_config.NumberColumn(format="%d"),
            "% válidos no local": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.1f%%"
            ),
            "% do candidato": st.column_config.NumberColumn(format="%.1f%%"),
            "Válidos / eleitorado": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    st.download_button(
        "Baixar tabela por local (.csv)",
        data=csv_bytes(table),
        file_name=f"locais_{cand['NR_VOTAVEL']}_novogama_2024.csv",
        mime="text/csv",
    )

    st.divider()
    st.markdown("#### Detalhamento por seção eleitoral (urna)")
    local_options = view.sort_values("VOTOS_CANDIDATO", ascending=False)
    local_labels = {
        row["LOCAL_KEY"]: f"{row['NM_LOCVOT']} · {format_int(row['VOTOS_CANDIDATO'])} votos"
        for _, row in local_options.iterrows()
    }
    selected_local = st.selectbox(
        "Escolha um local para abrir as seções",
        options=local_options["LOCAL_KEY"].tolist(),
        format_func=lambda key: local_labels.get(key, key),
        key="local_secao",
    )
    sec_view = sections[sections["LOCAL_KEY"].eq(selected_local)].copy()
    sec_view = sec_view.sort_values("NR_SECAO")
    sec_table = sec_view[
        [
            "NR_SECAO",
            "QT_ELEITOR_SECAO",
            "VOTOS_VALIDOS_SECAO",
            "VOTOS_CANDIDATO",
            "PCT_CANDIDATO_NO_SECAO",
            "PCT_DO_TOTAL_CANDIDATO",
        ]
    ].rename(
        columns={
            "NR_SECAO": "Seção",
            "QT_ELEITOR_SECAO": "Eleitorado",
            "VOTOS_VALIDOS_SECAO": "Votos válidos",
            "VOTOS_CANDIDATO": "Votos do candidato",
            "PCT_CANDIDATO_NO_SECAO": "% válidos na seção",
            "PCT_DO_TOTAL_CANDIDATO": "% do candidato",
        }
    )
    st.dataframe(
        sec_table,
        width="stretch",
        hide_index=True,
        column_config={
            "Eleitorado": st.column_config.NumberColumn(format="localized"),
            "Votos válidos": st.column_config.NumberColumn(format="localized"),
            "Votos do candidato": st.column_config.NumberColumn(format="localized"),
            "% válidos na seção": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.1f%%"
            ),
            "% do candidato": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.download_button(
        "Baixar seções deste local (.csv)",
        data=csv_bytes(sec_table),
        file_name=f"secoes_{selected_local}_novogama_2024.csv",
        mime="text/csv",
    )


def tab_candidatos(data: ElectionData, cand: pd.Series, benchmarks: Dict) -> None:
    st.markdown("#### Todos os candidatos a vereador")
    st.caption(
        "A base inclui **todos** os candidatos do registro do TSE: eleitos, suplentes "
        "e não eleitos. Use os filtros para recortar por situação, partido ou nome."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Candidatos", format_int(benchmarks.get("n_candidatos", 0)))
    c2.metric("Eleitos", format_int(benchmarks.get("n_eleitos", 0)))
    c3.metric("Suplentes", format_int(benchmarks.get("n_suplentes", 0)))
    c4.metric("Não eleitos", format_int(benchmarks.get("n_nao_eleitos", 0)))

    status_filter = st.multiselect(
        "Situação",
        options=["Eleito", "Suplente", "Não eleito", "Sem situação"],
        default=["Eleito", "Suplente", "Não eleito", "Sem situação"],
        key="status_candidatos",
    )
    partidos = sorted(data.resumo["SG_PARTIDO"].dropna().unique().tolist())
    party_filter = st.multiselect(
        "Partido", options=partidos, default=[], key="partido_candidatos"
    )
    search = st.text_input(
        "Buscar por nome, número ou partido",
        placeholder="Ex.: Renato, 15000, MDB",
        key="busca_candidatos",
    )
    only_votes = st.toggle(
        "Somente candidatos com voto", value=False, key="so_votos_candidatos"
    )

    table = filter_candidates(
        data.resumo, statuses=status_filter, partidos=party_filter, search=search
    )
    if only_votes:
        table = table[table["QT_VOTOS"] > 0]

    if table.empty:
        st.info("Nenhum candidato corresponde aos filtros.")
        return

    table = table.sort_values("RANKING").copy()
    st.dataframe(
        table[
            [
                "RANKING",
                "NR_VOTAVEL",
                "NM_URNA_CANDIDATO",
                "SG_PARTIDO",
                "SITUACAO",
                "QT_VOTOS",
                "PCT_VALIDOS",
                "QTD_LOCAIS_COM_VOTO",
                "QTD_SECOES_COM_VOTO",
                "MELHOR_LOCAL",
            ]
        ].rename(
            columns={
                "RANKING": "#",
                "NR_VOTAVEL": "Número",
                "NM_URNA_CANDIDATO": "Nome de urna",
                "SG_PARTIDO": "Partido",
                "SITUACAO": "Situação",
                "QT_VOTOS": "Votos",
                "PCT_VALIDOS": "% válidos",
                "QTD_LOCAIS_COM_VOTO": "Locais",
                "QTD_SECOES_COM_VOTO": "Seções",
                "MELHOR_LOCAL": "Melhor local",
            }
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "Votos": st.column_config.NumberColumn(format="localized"),
            "% válidos": st.column_config.NumberColumn(format="%.2f%%"),
            "Locais": st.column_config.NumberColumn(format="%d"),
            "Seções": st.column_config.NumberColumn(format="%d"),
        },
    )
    st.download_button(
        "Baixar candidatos filtrados (.csv)",
        data=csv_bytes(table),
        file_name="candidatos_novogama_2024.csv",
        mime="text/csv",
    )

    st.divider()
    col_a, col_b = st.columns([1, 1], gap="large")
    with col_a:
        st.markdown("##### Câmara eleita — vagas por partido")
        st.plotly_chart(chart_party_seats(data.resumo), width="stretch")
    with col_b:
        st.markdown("##### Não eleitos com mais votos")
        st.caption("Quem ficou de fora apesar da votação expressiva.")
        fora = (
            data.resumo[data.resumo["SITUACAO"].eq("Não eleito")]
            .sort_values("QT_VOTOS", ascending=False)
            .head(10)[["NM_URNA_CANDIDATO", "SG_PARTIDO", "QT_VOTOS", "PCT_VALIDOS"]]
        )
        st.dataframe(
            fora.rename(
                columns={
                    "NM_URNA_CANDIDATO": "Candidato",
                    "SG_PARTIDO": "Partido",
                    "QT_VOTOS": "Votos",
                    "PCT_VALIDOS": "% válidos",
                }
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Votos": st.column_config.NumberColumn(format="localized"),
                "% válidos": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

    with st.expander("Ver composição completa da Câmara e suplentes"):
        eleitos = data.resumo[data.resumo["SITUACAO"].eq("Eleito")].sort_values(
            "QT_VOTOS", ascending=False
        )
        st.markdown("**Eleitos**")
        st.dataframe(
            eleitos[
                ["NM_URNA_CANDIDATO", "SG_PARTIDO", "ELEITO_POR", "QT_VOTOS", "PCT_VALIDOS"]
            ].rename(
                columns={
                    "NM_URNA_CANDIDATO": "Candidato",
                    "SG_PARTIDO": "Partido",
                    "ELEITO_POR": "Forma de eleição",
                    "QT_VOTOS": "Votos",
                    "PCT_VALIDOS": "% válidos",
                }
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Votos": st.column_config.NumberColumn(format="localized"),
                "% válidos": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        suplentes = data.resumo[data.resumo["SITUACAO"].eq("Suplente")].sort_values(
            "QT_VOTOS", ascending=False
        )
        st.markdown("**Suplentes**")
        st.dataframe(
            suplentes[
                ["NM_URNA_CANDIDATO", "SG_PARTIDO", "QT_VOTOS", "PCT_VALIDOS"]
            ].rename(
                columns={
                    "NM_URNA_CANDIDATO": "Candidato",
                    "SG_PARTIDO": "Partido",
                    "QT_VOTOS": "Votos",
                    "PCT_VALIDOS": "% válidos",
                }
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Votos": st.column_config.NumberColumn(format="localized"),
                "% válidos": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )


def tab_qualidade(data: ElectionData) -> None:
    st.markdown("#### Qualidade e procedência dos dados")
    st.caption(
        "Checklist automático da base e da geolocalização. "
        "O objetivo é tornar visível o que é coordenada oficial e o que é estimativa."
    )

    checks = build_quality_report(data.votacao, data.locais, data.resumo)
    st.dataframe(
        checks.rename(
            columns={
                "VERIFICACAO": "Verificação",
                "STATUS": "Status",
                "VALOR": "Valor",
                "DETALHE": "Detalhe",
            }
        ),
        width="stretch",
        hide_index=True,
        column_config={"Status": st.column_config.TextColumn(width="small")},
    )

    st.divider()
    col_a, col_b = st.columns([1, 1], gap="large")
    with col_a:
        st.markdown("##### Procedência das coordenadas")
        provenance = coordinate_provenance(data.locais)
        if provenance.empty:
            st.info("Sem informação de procedência.")
        else:
            st.dataframe(
                provenance.rename(
                    columns={
                        "PRECISAO": "Precisão",
                        "LOCAIS": "Locais",
                        "SECOES": "Seções",
                    }
                ),
                width="stretch",
                hide_index=True,
                column_config={
                    "Locais": st.column_config.NumberColumn(format="%d"),
                    "Seções": st.column_config.NumberColumn(format="%d"),
                },
            )
    with col_b:
        st.markdown("##### Metadados da base")
        meta = data.metadata or {}
        info = pd.DataFrame(
            [
                ["Gerado em", str(meta.get("gerado_em", "—")).replace("T", " ")],
                ["Eleição", f"{meta.get('ano', 2024)} · {meta.get('turno', 1)}º turno"],
                [
                    "Município",
                    f"{meta.get('municipio', 'NOVO GAMA')} / {meta.get('uf', 'GO')}",
                ],
                ["Cargo", str(meta.get("cargo", "Vereador"))],
                [
                    "Registros de votação",
                    format_int(meta.get("registros", {}).get("votacao", 0)),
                ],
                [
                    "Locais distintos",
                    format_int(
                        meta.get("geolocalizacao", {}).get("locais_distintos", 0)
                    ),
                ],
                [
                    "Coordenadas oficiais",
                    format_int(
                        meta.get("geolocalizacao", {}).get("coordenadas_oficiais", 0)
                    ),
                ],
                [
                    "Coordenadas aproximadas",
                    format_int(
                        meta.get("geolocalizacao", {}).get("coordenadas_aproximadas", 0)
                    ),
                ],
            ],
            columns=["Item", "Valor"],
        )
        st.dataframe(info, width="stretch", hide_index=True)

    approx = approximate_locations(data.locais)
    st.markdown("##### Locais com coordenada aproximada")
    if approx.empty:
        st.success("Todos os locais de votação usam coordenadas oficiais do TSE.")
    else:
        st.dataframe(
            approx.rename(
                columns={
                    "NM_LOCVOT": "Local",
                    "DS_ENDERECO": "Endereço",
                    "NM_BAIRRO": "Bairro",
                    "PRECISAO": "Precisão",
                    "COORD_OBS": "Motivo",
                    "NR_LATITUDE": "Latitude",
                    "NR_LONGITUDE": "Longitude",
                    "DIST_KM_CENTRO": "Distância do centro (km)",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    with st.expander("Como a geolocalização foi corrigida"):
        st.markdown(
            """
            1. A coordenada oficial do TSE (`NR_LATITUDE` / `NR_LONGITUDE`) é lida do
               cadastro de locais de votação e **agregada por local** (`NR_LOCAL_VOTACAO`).
               Assim, todas as seções do mesmo prédio apontam para o mesmo ponto, sem
               espalhar marcadores artificialmente.
            2. Coordenadas vazias, `0`, `-1`, fora do Brasil ou muito distantes de
               Novo Gama são rejeitadas. O pipeline tenta, em ordem: geocodificação
               OSM/Nominatim (se habilitada), centróide do bairro e centróide municipal.
            3. Todo ponto substituto é marcado como **aproximado**, recebe contorno
               tracejado no mapa e aparece na lista de auditoria acima.
            4. Seções agregadas do TSE são descartadas para não duplicar urnas; o join
               final é feito por `NR_ZONA` + `NR_SECAO`.
            """
        )

    st.caption(
        "Fontes: [Votação por seção 2024](https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2024_GO.zip) · "
        "[Locais de votação 2024](https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_2024.zip) · "
        "[Candidaturas 2024](https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2024.zip)"
    )


# ---------------------------------------------------------------------------
# Estado vazio
# ---------------------------------------------------------------------------
def render_empty_state() -> None:
    st.title("Vereadores de Novo Gama — 2024")
    st.warning(
        "Nenhuma base processada foi encontrada. Baixe os dados oficiais do TSE "
        "na barra lateral ou coloque os arquivos em `data/raw/`."
    )
    st.markdown(
        """
        ### Como carregar os dados
        1. Na barra lateral, abra **Atualizar base oficial do TSE** e clique em
           **Baixar e processar dados do TSE**; ou
        2. Envie manualmente os três arquivos oficiais (votação, locais e candidaturas); ou
        3. Pelo terminal:

        ```powershell
        python -m src.data_loader --download-tse
        ```
        """
    )
    st.info(
        "A base inclui todos os candidatos do registro do TSE — eleitos, suplentes "
        "e não eleitos — e usa as coordenadas oficiais dos locais de votação."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    inject_css()
    data = get_data()

    if "selected_candidate" not in st.session_state and "selected_nr" not in st.session_state:
        st.session_state["selected_candidate"] = DEFAULT_CANDIDATO_NR
        st.session_state["selected_nr"] = DEFAULT_CANDIDATO_NR

    with st.sidebar:
        render_data_management(data)

    if data.empty:
        render_empty_state()
        return

    selected_nr = st.session_state.get("selected_nr")
    all_nrs = set(data.resumo["NR_VOTAVEL"].astype(str))
    if not selected_nr or selected_nr not in all_nrs:
        if DEFAULT_CANDIDATO_NR in all_nrs:
            selected_nr = DEFAULT_CANDIDATO_NR
        else:
            selected_nr = data.resumo.sort_values("QT_VOTOS", ascending=False).iloc[0][
                "NR_VOTAVEL"
            ]
    cand = data.resumo[
        data.resumo["NR_VOTAVEL"].astype(str).eq(str(selected_nr))
    ].iloc[0]

    totals = get_totals(data.votacao)
    benchmarks = get_benchmarks(data.resumo)
    locais = aggregate_candidate_by_local(data.votacao, str(selected_nr))
    bairros = aggregate_candidate_by_bairro(data.votacao, str(selected_nr))
    sections = aggregate_candidate_by_section(data.votacao, str(selected_nr))

    render_header(data, cand, totals, benchmarks)

    container_visao, container_mapa, container_locais, container_candidatos, container_qualidade = st.tabs(
        [
            "📊 Visão geral",
            "🗺️ Mapa",
            "🏫 Locais e seções",
            "🏆 Candidatos",
            "✅ Qualidade dos dados",
        ]
    )
    with container_visao:
        tab_overview(data, cand, totals, benchmarks, locais, bairros)
    with container_mapa:
        tab_map(data, cand, locais, sections)
    with container_locais:
        tab_locais(data, cand, locais, sections)
    with container_candidatos:
        tab_candidatos(data, cand, benchmarks)
    with container_qualidade:
        tab_qualidade(data)


if __name__ == "__main__":
    main()
