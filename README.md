# 🗳️ Painel Eleitoral 2024 — Vereadores de Novo Gama (GO)

Painel interativo em **Python + Streamlit** para analisar a votação de **Vereador** em
**Novo Gama (GO)** no **1º turno de 2024**, com mapa dos locais de votação, detalhamento
por seção (urna), ranking completo de candidatos e auditoria da geolocalização.

A base inclui **todos os candidatos do registro do TSE**: eleitos, suplentes e
**não eleitos**. O objetivo é permitir comparação honesta entre quem ocupou as
15 vagas e quem ficou de fora, sem esconder a disputa completa.

---

## 📁 Estrutura do Projeto

```text
novogama/
├── app.py                      # Interface Streamlit (KPIs, mapa, gráficos e tabelas)
├── requirements.txt            # Dependências
├── README.md
├── iniciar_painel.bat          # Atalho para Windows
├── .streamlit/
│   └── config.toml             # Tema visual (azul, alto contraste, sem vermelho/verde)
├── src/
│   ├── config.py               # Constantes, URLs do TSE, bounds e paleta
│   ├── data_loader.py          # Download, filtros, pipeline e persistência
│   ├── geo_processor.py        # Validação de coordenadas, fallback e join
│   └── analytics.py            # Agregações, benchmarks, qualidade e formatação pt-BR
└── data/
    ├── raw/                    # Pacotes oficiais do TSE (.zip)
    └── processed/              # Camada processada pronta para o painel
```

---

## 🧠 O que foi revisado

### 1. Dados completos, inclusive não eleitos

O pipeline passou a ler também a **consulta de candidaturas** do TSE
(`consulta_cand_2024.zip`) e a cruzar `NR_VOTAVEL` com a votação. Com isso, o painel
mostra:

- **15 eleitos** (por quociente partidário ou média);
- **94 suplentes**;
- **138 não eleitos**;
- **13 registros sem situação informada** (ex.: número nulo).

O seletor de candidato, a tabela e o ranking incluem todos eles. A situação oficial é
extraída de `DS_SIT_TOT_TURNO` e não é deduzida por “top N” — o que seria incorreto na
eleição proporcional.

### 2. Geolocalização das urnas corrigida

Antes, o painel usava coordenadas de uma base demonstrativa e tratava cada seção como
um ponto. Agora:

- a coordenada oficial (`NR_LATITUDE` / `NR_LONGITUDE`) é lida do cadastro de
  **locais de votação** do TSE;
- o ponto é **agregado por `NR_LOCAL_VOTACAO`**: todas as seções do mesmo prédio
  apontam para o mesmo local, sem espalhar marcadores artificiais;
- seções agregadas (`CD_TIPO_SECAO_AGREGADA = 2`) são descartadas para não duplicar
  urnas; o join final é por `NR_ZONA + NR_SECAO`;
- coordenadas `0`, `-1`, vazias, fora do Brasil ou muito distantes do município são
  rejeitadas;
- quando necessário, o pipeline tenta, em ordem: **Nominatim/OSM** (opcional),
  **centróide do bairro** e **centróide municipal**;
- todo ponto substituto é marcado como **aproximado**, aparece com **contorno
  tracejado** no mapa e é listado na aba **Qualidade dos dados**.

Na base oficial de 2024, os **28 locais** de Novo Gama têm coordenada oficial do TSE.

### 3. Painel orientado a boas práticas de visualização

- **Hierarquia clara:** contexto → KPIs → mapa → análise → tabelas → auditoria.
- **Uma pergunta por gráfico:** rankings ordenados, sem pizza/3D, com rótulos diretos.
- **Codificação consciente:** tamanho = volume de votos; cor = participação nos votos
  válidos do local; contorno tracejado = estimativa.
- **Paleta acessível:** azul/âmbar/cinza, sem depender de vermelho/verde para status.
- **Números em pt-BR:** milhar com ponto e decimal com vírgula.
- **Comparação com referências:** menor votação entre eleitos, maior votação entre não
  eleitos e média dos eleitos, com explicação do efeito do quociente partidário.
- **Transparência:** origem de cada coordenada, contagem de aproximações e checklist
  automático de qualidade.
- **Mapa limpo:** um único mapa base por vez, legenda dentro do iframe, controles de
  tela cheia/medição e nenhum heatmap enganoso para apenas 28 pontos.

---

## ⚙️ Arquitetura de Dados

1. **Votação nominal por seção** — `votacao_secao_2024_GO.zip`
   - filtros: `NM_MUNICIPIO = NOVO GAMA` (ou `CD_MUNICIPIO = 93327`), `CD_CARGO = 13`,
     `NR_TURNO = 1`;
   - classificação do voto: nominal, legenda, branco, nulo.
2. **Locais de votação / eleitorado por seção** — `eleitorado_local_votacao_2024.zip`
   - coordenadas oficiais, bairro, endereço, eleitorado por seção;
   - limpeza, validação e fallback geoespacial.
3. **Consulta de candidaturas** — `consulta_cand_2024.zip`
   - nome de urna, nome completo, partido, coligação e situação eleitoral;
   - inclui eleitos, suplentes e não eleitos.
4. **Saídas processadas**
   - `votacao_georreferenciada_novogama_2024.csv`
   - `locais_votacao_novogama_2024.csv`
   - `candidatos_novogama_2024.csv`
   - `resumo_candidatos_novogama_2024.csv`
   - `metadata_novogama_2024.json`

### Regras de cálculo

- **Votos válidos** = votos nominais + votos de legenda.
- **% dos válidos** = votos do candidato ÷ votos válidos do município ou do local.
- **Ranking** = posição entre todos os candidatos do registro, por votos nominais.
- **Eleito** = situação oficial do TSE (`ELEITO POR QP`, `ELEITO POR MÉDIA`).
  **Suplente** e **não eleito** são situações distintas.

---

## 🚀 Como Executar

### 1. Ambiente

```powershell
cd "D:\trabalho\Outros\novogama"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Baixar e processar os dados oficiais

Pelo terminal:

```powershell
python -m src.data_loader --download-tse
```

Ou, com o painel aberto, use **Atualizar base oficial do TSE** na barra lateral.
O download completo tem cerca de **170 MB** (votação, locais e candidaturas).

Se os arquivos já estiverem em `data/raw/`, basta reprocessar:

```powershell
python -m src.data_loader --reprocess
```

### 3. Iniciar o painel

```powershell
python -m streamlit run app.py
```

O navegador abre em `http://localhost:8501`. No Windows, também é possível usar
`iniciar_painel.bat`.

---

## 🖥️ O que o painel entrega

| Aba | Conteúdo |
|---|---|
| **Visão geral** | KPIs do candidato, ranking por local, comparação com eleitos/não eleitos, votos por bairro e distribuição por situação. |
| **Mapa** | Um ponto por local de votação; tamanho = votos, cor = participação no local, contorno tracejado = coordenada aproximada. Popup com as seções (urnas). |
| **Locais e seções** | Tabela por local, detalhamento por seção, eleitorado, votos válidos e download em CSV. |
| **Candidatos** | Todos os 260 candidatos, filtros por situação/partido/nome, câmara eleita, suplentes e não eleitos com mais votos. |
| **Qualidade dos dados** | Checklist, procedência das coordenadas, metadados, locais aproximados e explicação do tratamento. |

---

## 🔎 Fonte Oficial

- [Votação por seção — 2024 (GO)](https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2024_GO.zip)
- [Locais de votação — 2024](https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_2024.zip)
- [Consulta de candidaturas — 2024](https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2024.zip)

> **Nota metodológica:** a eleição para vereador é proporcional. A ordem geral de
> votos não define, sozinha, quem se elege: o quociente partidário e a média podem
> eleger candidatos com menos votos que outros não eleitos. O painel explicita essa
> diferença em vez de escondê-la.
