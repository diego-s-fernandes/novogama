@echo off
chcp 65001 >nul
title Painel Geoespacial Eleicoes 2024 - Novo Gama (GO)

:: Forca encoding UTF-8 no Python para evitar erros de acentos e caracteres especiais
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ============================================================================
echo   MAPA GEOESPACIAL ELEICOES 2024 - VEREADORES DE NOVO GAMA (GO)
echo ============================================================================
echo.

:: Garante execucao a partir da pasta deste arquivo
cd /d "%~dp0"

:: 1. Verifica se o Python esta acessivel
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] O comando python nao foi encontrado no sistema.
    echo Certifique-se de que o Python esta instalado e adicionado ao PATH do Windows.
    echo.
    pause
    exit /b 1
)

:: 2. Ativa ambiente virtual se existir
if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Ativando ambiente virtual local: pasta .venv
    call ".venv\Scripts\activate.bat"
)

:: 3. Libera a porta 8501 caso haja processo anterior travado (ex: fechado no X)
python -c "import subprocess, time; [subprocess.run(f'taskkill /f /pid {l.strip().split()[-1]}', shell=True, capture_output=True) for l in subprocess.check_output('netstat -ano', text=True).splitlines() if ':8501' in l and 'LISTENING' in l]; time.sleep(1)" 2>nul

:: 4. Verifica se as bibliotecas necessarias estao instaladas
python -c "import streamlit, folium, streamlit_folium, plotly, pandas, branca, geopy" 2>nul
if errorlevel 1 (
    echo [INFO] Instalando dependencias do projeto via pip...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRO] Falha ao instalar dependencias do requirements.txt.
        pause
        exit /b 1
    )
)

echo [INFO] Iniciando servidor Streamlit em http://localhost:8501 ...
echo [DICA] Para encerrar o painel, pressione CTRL+C nesta janela ou feche-a.
echo.

python -m streamlit run app.py --server.port 8501

if errorlevel 1 (
    echo.
    echo [ERRO] Ocorreu um problema ao executar o painel.
    pause
)
